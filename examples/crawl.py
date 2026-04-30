from __future__ import annotations

import argparse
import asyncio
import re
import sys
import time
from typing import Literal
from urllib.parse import urlparse

from meshagent.api import RoomClient
from meshagent.api.http import new_client_session
from meshagent.commoncrawl import (
    CommonCrawlImportProgress,
    import_domain_from_commoncrawl,
)
from meshagent.commoncrawl.commoncrawl import (
    COMMONCRAWL_COLUMNAR_INDEX_PATH,
    COMMONCRAWL_COLUMNAR_SCAN_PARTITIONS,
    COMMONCRAWL_USER_AGENT,
)

Scope = Literal["host", "domain"]


def _namespace(value: str | None) -> list[str] | None:
    if value is None or value.strip() == "":
        return None
    return [part for part in value.split("::") if part != ""]


def _domain(value: str, *, scope: Scope = "host") -> str:
    host, _ = _host_and_path(value)
    if scope == "domain":
        return _domain_scope_host(host)
    return host


def _url_filter(value: str, *, scope: Scope = "host") -> str:
    host, path = _host_and_path(value)
    if host == "":
        raise ValueError("url must be non-empty")
    path = path.rstrip("/")
    if scope == "domain":
        host_pattern = f"([^/]+\\.)?{re.escape(_domain_scope_host(host))}"
    else:
        host_pattern = re.escape(host)
    if path == "":
        return f"^https?://{host_pattern}(/.*)?$"
    return f"^https?://{host_pattern}{re.escape(path)}(/.*)?$"


def _host_and_path(value: str) -> tuple[str, str]:
    parsed = urlparse(value)
    host = parsed.netloc or parsed.path.split("/", maxsplit=1)[0]
    path = parsed.path if parsed.netloc else parsed.path.removeprefix(host)
    return host, path


def _domain_scope_host(host: str) -> str:
    if host == "":
        raise ValueError("url must be non-empty")
    return host.removeprefix("www.")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Import a domain from Common Crawl into a Meshagent room dataset.",
    )
    parser.add_argument(
        "url", help="Domain or URL to import, e.g. http://www.meshagent.com"
    )
    parser.add_argument(
        "--scope",
        choices=["host", "domain"],
        default="host",
        help=(
            "Crawl boundary. 'host' imports only the requested host; 'domain' "
            "imports the registrable domain and sibling subdomains."
        ),
    )
    parser.add_argument(
        "--index",
        default=None,
        help="Common Crawl index id, e.g. CC-MAIN-2025-08. Defaults to the latest index.",
    )
    parser.add_argument("--table", default="commoncrawl", help="Dataset table name")
    parser.add_argument(
        "--namespace",
        default=None,
        help="Dataset namespace, using :: between nested segments",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum number of unique Common Crawl URLs to import",
    )
    parser.add_argument(
        "--sql",
        default=None,
        help=(
            "Advanced DataFusion SQL query for URL selection. The query must "
            "return url plus WARC pointer columns."
        ),
    )
    parser.add_argument(
        "--columnar-index-path",
        default=COMMONCRAWL_COLUMNAR_INDEX_PATH,
        help="Common Crawl columnar index Parquet path",
    )
    parser.add_argument(
        "--scan-partitions",
        type=int,
        default=COMMONCRAWL_COLUMNAR_SCAN_PARTITIONS,
        help="DataFusion target partitions for columnar index scans",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=16,
        help="Maximum number of concurrent WARC range reads",
    )
    parser.add_argument(
        "--warc-retries",
        type=int,
        default=3,
        help="Retry count for transient WARC read failures",
    )
    parser.add_argument(
        "--warc-retry-delay",
        type=float,
        default=1.0,
        help="Initial WARC retry delay in seconds",
    )
    parser.add_argument(
        "--silent",
        action="store_true",
        help="Suppress progress output",
    )
    return parser


class _ProgressReporter:
    def __init__(self) -> None:
        self._is_tty = sys.stderr.isatty()
        self._last_emit = 0.0
        self._needs_newline = False

    async def __call__(self, progress: CommonCrawlImportProgress) -> None:
        now = time.monotonic()
        if (
            progress.stage
            not in {
                "started",
                "index_registering",
                "index_listing",
                "index_querying",
                "batch_merged",
                "completed",
            }
            and now - self._last_emit < 0.25
        ):
            return
        self._last_emit = now
        line = self._format(progress)
        if self._is_tty:
            sys.stderr.write(f"\r\033[2K{line}")
            self._needs_newline = progress.stage != "completed"
            if progress.stage == "completed":
                sys.stderr.write("\n")
        else:
            sys.stderr.write(f"{line}\n")
        sys.stderr.flush()

    def close(self) -> None:
        if self._needs_newline:
            sys.stderr.write("\n")
            sys.stderr.flush()
            self._needs_newline = False

    def _format(self, progress: CommonCrawlImportProgress) -> str:
        status = {
            "started": "starting",
            "index_registering": "opening-index",
            "index_listing": "listing-index",
            "index_querying": "scanning-index",
            "index_batch_scanned": "reading-index",
            "record_matched": "fetching",
            "record_extracted": "extracting",
            "record_skipped": "skipping",
            "batch_merged": "merged",
            "completed": "complete",
        }.get(progress.stage, progress.stage)
        parts = [
            f"{status}",
            f"matched={progress.matched_records}",
            f"imported={progress.imported_records}",
            f"skipped={progress.skipped_records}",
            f"queued={progress.pending_records}",
        ]
        if progress.bytes_downloaded > 0:
            parts.append(f"downloaded={_format_bytes(progress.bytes_downloaded)}")
        if progress.warc_requests > 0:
            parts.append(f"requests={progress.warc_requests}")
        if progress.current_url:
            parts.append(_ellipsize(progress.current_url, 88))
        elif progress.current_file and progress.stage.startswith("index_"):
            parts.append(_ellipsize(progress.current_file, 88))
        return " | ".join(parts)


def _ellipsize(value: str, max_length: int) -> str:
    if len(value) <= max_length:
        return value
    return f"{value[: max_length - 1]}..."


def _format_bytes(value: int) -> str:
    amount = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if amount < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(amount)}B"
            return f"{amount:.1f}{unit}"
        amount /= 1024
    return f"{amount:.1f}TB"


async def _latest_index() -> str:
    async with new_client_session() as session:
        async with session.get(
            "https://index.commoncrawl.org/collinfo.json",
            headers={"User-Agent": COMMONCRAWL_USER_AGENT},
        ) as response:
            response.raise_for_status()
            collections = await response.json()

    if not isinstance(collections, list) or len(collections) == 0:
        raise RuntimeError("Common Crawl returned no index collections")

    first = collections[0]
    if not isinstance(first, dict):
        raise RuntimeError("Common Crawl returned an unexpected index collection")

    index = first.get("id")
    if not isinstance(index, str) or index == "":
        raise RuntimeError("Common Crawl latest index is missing an id")
    return index


async def _main() -> None:
    args = _parser().parse_args()
    index = args.index or await _latest_index()
    reporter = None if args.silent else _ProgressReporter()

    try:
        async with RoomClient() as room:
            result = await import_domain_from_commoncrawl(
                room,
                index=index,
                domain=_domain(args.url, scope=args.scope),
                table=args.table,
                namespace=_namespace(args.namespace),
                url_filter=_url_filter(args.url, scope=args.scope),
                limit=args.limit,
                match_type=args.scope,
                columnar_index_path=args.columnar_index_path,
                columnar_sql=args.sql,
                columnar_scan_partitions=args.scan_partitions,
                warc_concurrency=args.concurrency,
                warc_retries=args.warc_retries,
                warc_retry_delay=args.warc_retry_delay,
                progress=reporter,
            )
    finally:
        if reporter is not None:
            reporter.close()

    print(
        "imported "
        f"{result.imported_records} unique records from {result.matched_records} matched captures "
        f"from {index} into {args.namespace + '::' if args.namespace else ''}{args.table} "
        f"({result.skipped_records} skipped, {_format_bytes(result.bytes_downloaded)} downloaded, "
        f"{result.warc_requests} WARC requests)"
    )


if __name__ == "__main__":
    asyncio.run(_main())

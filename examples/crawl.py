from __future__ import annotations

import argparse
import asyncio
import re
import sys
import time
from urllib.parse import urlparse

from meshagent.api import RoomClient
from meshagent.api.http import new_client_session
from meshagent.commoncrawl import (
    CommonCrawlImportProgress,
    import_domain_from_commoncrawl,
)
from meshagent.commoncrawl.commoncrawl import COMMONCRAWL_USER_AGENT


def _namespace(value: str | None) -> list[str] | None:
    if value is None or value.strip() == "":
        return None
    return [part for part in value.split("::") if part != ""]


def _domain(value: str) -> str:
    parsed = urlparse(value)
    return parsed.netloc or parsed.path.split("/", maxsplit=1)[0]


def _url_filter(value: str) -> str:
    parsed = urlparse(value)
    host = parsed.netloc or parsed.path.split("/", maxsplit=1)[0]
    if host == "":
        raise ValueError("url must be non-empty")
    path = parsed.path if parsed.netloc else parsed.path.removeprefix(host)
    path = path.rstrip("/")
    if path == "":
        return f"^https?://{re.escape(host)}(/.*)?$"
    return f"^https?://{re.escape(host)}{re.escape(path)}(/.*)?$"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Import a domain from Common Crawl into a Meshagent room dataset.",
    )
    parser.add_argument(
        "url", help="Domain or URL to import, e.g. http://www.meshagent.com"
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
        help="Maximum number of Common Crawl index records to import",
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
            progress.stage not in {"started", "batch_merged", "completed"}
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
            f"pending={progress.pending_records}",
        ]
        if progress.current_url:
            parts.append(_ellipsize(progress.current_url, 88))
        return " | ".join(parts)


def _ellipsize(value: str, max_length: int) -> str:
    if len(value) <= max_length:
        return value
    return f"{value[: max_length - 1]}..."


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
                domain=_domain(args.url),
                table=args.table,
                namespace=_namespace(args.namespace),
                url_filter=_url_filter(args.url),
                limit=args.limit,
                progress=reporter,
            )
    finally:
        if reporter is not None:
            reporter.close()

    print(
        "imported "
        f"{result.imported_records}/{result.matched_records} records "
        f"from {index} into {args.namespace + '::' if args.namespace else ''}{args.table} "
        f"({result.skipped_records} skipped)"
    )


if __name__ == "__main__":
    asyncio.run(_main())

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from io import BytesIO
import asyncio
import json
import logging
import os
from typing import TYPE_CHECKING, Any, Literal, TypeAlias
from urllib.parse import parse_qsl, urlencode, urlparse

import pyarrow as pa

from meshagent.api import RoomClient
from meshagent.api.http import new_client_session
from meshagent.commoncrawl.version import __version__

if TYPE_CHECKING:
    from aiohttp import ClientSession
    from warcio.recordloader import ArcWarcRecord

logger = logging.getLogger(__name__)

COMMONCRAWL_INDEX_BASE_URL = "https://index.commoncrawl.org"
COMMONCRAWL_DATA_BASE_URL = "https://data.commoncrawl.org"
COMMONCRAWL_COLUMNAR_INDEX_PATH = "s3://commoncrawl/cc-index/table/cc-main/warc/"
COMMONCRAWL_INDEX_REQUEST_DELAY_SECONDS = 1.0
COMMONCRAWL_INDEX_RETRIES = 1
COMMONCRAWL_INDEX_RETRY_DELAY_SECONDS = 60.0
COMMONCRAWL_INDEX_SCAN_PROGRESS_SECONDS = 5.0
COMMONCRAWL_COLUMNAR_SCAN_PARTITIONS = 64
COMMONCRAWL_WARC_CONCURRENCY = 16
COMMONCRAWL_WARC_RETRIES = 3
COMMONCRAWL_WARC_RETRY_DELAY_SECONDS = 1.0
COMMONCRAWL_WARC_TRANSIENT_STATUSES = {408, 409, 425, 429, 500, 502, 503, 504}
COMMONCRAWL_USER_AGENT = (
    f"meshagent-commoncrawl/{__version__} (+https://www.meshagent.com)"
)

ExtractedRecord: TypeAlias = Mapping[str, Any]
ExtractCallback: TypeAlias = Callable[
    ["ArcWarcRecord", bytes],
    Awaitable[ExtractedRecord | None],
]
IndexSource: TypeAlias = Literal["cdx", "columnar"]
IndexMatchType: TypeAlias = Literal["domain", "host"]


@dataclass(frozen=True)
class CommonCrawlImportResult:
    matched_records: int
    imported_records: int
    skipped_records: int
    files_read: int
    bytes_downloaded: int = 0
    warc_requests: int = 0


@dataclass(frozen=True)
class CommonCrawlImportProgress:
    stage: str
    matched_records: int
    imported_records: int
    skipped_records: int
    files_read: int
    pending_records: int
    current_url: str | None = None
    current_file: str | None = None
    bytes_downloaded: int = 0
    warc_requests: int = 0


ProgressCallback: TypeAlias = Callable[
    [CommonCrawlImportProgress],
    Awaitable[None],
]


@dataclass(frozen=True)
class _CdxRecord:
    url: str
    timestamp: str
    mime: str | None
    filename: str
    offset: int
    length: int

    @staticmethod
    def from_json(value: Mapping[str, Any]) -> _CdxRecord:
        url = value["url"]
        timestamp = value["timestamp"]
        filename = value["filename"]
        offset = value["offset"]
        length = value["length"]
        if not isinstance(url, str):
            raise ValueError("Common Crawl index record has non-string url")
        if not isinstance(timestamp, str):
            raise ValueError("Common Crawl index record has non-string timestamp")
        if not isinstance(filename, str):
            raise ValueError("Common Crawl index record has non-string filename")

        mime_value = value.get("mime")
        if mime_value is not None and not isinstance(mime_value, str):
            mime_value = str(mime_value)

        return _CdxRecord(
            url=url,
            timestamp=timestamp,
            mime=mime_value,
            filename=filename,
            offset=int(offset),
            length=int(length),
        )


@dataclass(frozen=True)
class _ProcessedIndexRecord:
    index_record: _CdxRecord
    rows: list[dict[str, Any]]
    skipped_records: int
    bytes_downloaded: int
    warc_requests: int


@dataclass
class _WarcFetchMetrics:
    bytes_downloaded: int = 0
    requests: int = 0


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._hidden_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag.lower() in {"script", "style", "noscript"}:
            self._hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript"} and self._hidden_depth > 0:
            self._hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._hidden_depth == 0:
            stripped = data.strip()
            if stripped:
                self._parts.append(stripped)

    def text(self) -> str:
        return " ".join(self._parts)


async def import_domain_from_commoncrawl(
    room: RoomClient,
    *,
    index: str,
    domain: str,
    table: str = "commoncrawl",
    url_filter: str | Sequence[str] | None = None,
    extract: ExtractCallback | None = None,
    schema: pa.Schema | None = None,
    primary_key: str = "url",
    namespace: list[str] | None = None,
    branch: str | None = None,
    limit: int | None = None,
    batch_size: int = 100,
    index_source: IndexSource = "columnar",
    match_type: IndexMatchType = "domain",
    columnar_index_path: str = COMMONCRAWL_COLUMNAR_INDEX_PATH,
    columnar_sql: str | None = None,
    columnar_scan_partitions: int = COMMONCRAWL_COLUMNAR_SCAN_PARTITIONS,
    index_request_delay: float = COMMONCRAWL_INDEX_REQUEST_DELAY_SECONDS,
    index_retries: int = COMMONCRAWL_INDEX_RETRIES,
    index_retry_delay: float = COMMONCRAWL_INDEX_RETRY_DELAY_SECONDS,
    warc_concurrency: int = COMMONCRAWL_WARC_CONCURRENCY,
    warc_retries: int = COMMONCRAWL_WARC_RETRIES,
    warc_retry_delay: float = COMMONCRAWL_WARC_RETRY_DELAY_SECONDS,
    session: "ClientSession | None" = None,
    progress: ProgressCallback | None = None,
) -> CommonCrawlImportResult:
    """Import Common Crawl captures for a domain into a room dataset.

    The default index source is Common Crawl's Parquet columnar index through
    DataFusion, which is better suited to broad URL selection than the CDX API.
    `url_filter` is passed to the generated DataFusion query as
    `regexp_like(url, <value>)`. Supply a sequence to pass multiple URL filters.
    `columnar_sql` may provide a custom DataFusion query; it must return URL and
    WARC pointer columns. The default extractor writes `url`, `date`,
    `content_type`, and `text`, merging on `url`. Pass `schema` when a custom
    extractor should create an empty table before the first row. Pass `progress`
    to receive async progress updates during the import.
    """

    if batch_size <= 0:
        raise ValueError("batch_size must be greater than zero")
    if primary_key == "":
        raise ValueError("primary_key must be non-empty")
    if index_request_delay < 0:
        raise ValueError("index_request_delay must be greater than or equal to zero")
    if index_retries < 0:
        raise ValueError("index_retries must be greater than or equal to zero")
    if index_retry_delay < 0:
        raise ValueError("index_retry_delay must be greater than or equal to zero")
    if columnar_scan_partitions <= 0:
        raise ValueError("columnar_scan_partitions must be greater than zero")
    if warc_concurrency <= 0:
        raise ValueError("warc_concurrency must be greater than zero")
    if warc_retries < 0:
        raise ValueError("warc_retries must be greater than or equal to zero")
    if warc_retry_delay < 0:
        raise ValueError("warc_retry_delay must be greater than or equal to zero")
    if index_source not in {"cdx", "columnar"}:
        raise ValueError("index_source must be 'cdx' or 'columnar'")
    if match_type not in {"domain", "host"}:
        raise ValueError("match_type must be 'domain' or 'host'")

    close_session = session is None
    http_session = session or new_client_session()
    try:
        return await _import_with_session(
            room=room,
            session=http_session,
            index=index,
            domain=domain,
            table=table,
            url_filter=url_filter,
            extract=extract,
            schema=schema,
            primary_key=primary_key,
            namespace=namespace,
            branch=branch,
            limit=limit,
            batch_size=batch_size,
            index_source=index_source,
            match_type=match_type,
            columnar_index_path=columnar_index_path,
            columnar_sql=columnar_sql,
            columnar_scan_partitions=columnar_scan_partitions,
            index_request_delay=index_request_delay,
            index_retries=index_retries,
            index_retry_delay=index_retry_delay,
            warc_concurrency=warc_concurrency,
            warc_retries=warc_retries,
            warc_retry_delay=warc_retry_delay,
            progress=progress,
        )
    finally:
        if close_session:
            await http_session.close()


async def _import_with_session(
    *,
    room: RoomClient,
    session: "ClientSession",
    index: str,
    domain: str,
    table: str,
    url_filter: str | Sequence[str] | None,
    extract: ExtractCallback | None,
    schema: pa.Schema | None,
    primary_key: str,
    namespace: list[str] | None,
    branch: str | None,
    limit: int | None,
    batch_size: int,
    index_source: IndexSource,
    match_type: IndexMatchType,
    columnar_index_path: str,
    columnar_sql: str | None,
    columnar_scan_partitions: int,
    index_request_delay: float,
    index_retries: int,
    index_retry_delay: float,
    warc_concurrency: int,
    warc_retries: int,
    warc_retry_delay: float,
    progress: ProgressCallback | None,
) -> CommonCrawlImportResult:
    extractor = extract or _default_extract
    schema = schema or (_default_schema() if extract is None else None)
    if schema is not None:
        await _ensure_table(
            room=room,
            table=table,
            schema=schema,
            namespace=namespace,
            branch=branch,
        )
    matched_records = 0
    imported_records = 0
    skipped_records = 0
    files_read = 0
    bytes_downloaded = 0
    warc_requests = 0
    batch: list[dict[str, Any]] = []
    pending_tasks: dict[asyncio.Task[_ProcessedIndexRecord], _CdxRecord] = {}
    pending_order: list[asyncio.Task[_ProcessedIndexRecord]] = []
    await _report_progress(
        progress,
        stage="started",
        matched_records=matched_records,
        imported_records=imported_records,
        skipped_records=skipped_records,
        files_read=files_read,
        pending_records=0,
        bytes_downloaded=bytes_downloaded,
        warc_requests=warc_requests,
    )

    async def report_batch_merged(
        *,
        current_url: str | None = None,
        current_file: str | None = None,
    ) -> None:
        await _report_progress(
            progress,
            stage="batch_merged",
            matched_records=matched_records,
            imported_records=imported_records,
            skipped_records=skipped_records,
            files_read=files_read,
            pending_records=len(pending_tasks) + len(batch),
            current_url=current_url,
            current_file=current_file,
            bytes_downloaded=bytes_downloaded,
            warc_requests=warc_requests,
        )

    async def merge_pending_batch(
        *,
        current_url: str | None = None,
        current_file: str | None = None,
        force: bool = False,
    ) -> None:
        nonlocal batch, imported_records, schema
        if len(batch) < batch_size and not force:
            return
        if len(batch) == 0:
            return
        rows_to_merge = _dedupe_rows_by_primary_key(
            rows=batch,
            primary_key=primary_key,
        )
        schema = await _merge_batch(
            room=room,
            table=table,
            rows=rows_to_merge,
            schema=schema,
            primary_key=primary_key,
            namespace=namespace,
            branch=branch,
        )
        imported_records += len(rows_to_merge)
        batch = []
        await report_batch_merged(current_url=current_url, current_file=current_file)

    async def handle_processed_record(processed: _ProcessedIndexRecord) -> None:
        nonlocal bytes_downloaded, warc_requests, skipped_records
        bytes_downloaded += processed.bytes_downloaded
        warc_requests += processed.warc_requests
        if processed.skipped_records > 0:
            skipped_records += processed.skipped_records
            await _report_progress(
                progress,
                stage="record_skipped",
                matched_records=matched_records,
                imported_records=imported_records,
                skipped_records=skipped_records,
                files_read=files_read,
                pending_records=len(pending_tasks) + len(batch),
                current_url=processed.index_record.url,
                current_file=processed.index_record.filename,
                bytes_downloaded=bytes_downloaded,
                warc_requests=warc_requests,
            )
        for row in processed.rows:
            batch.append(row)
            await _report_progress(
                progress,
                stage="record_extracted",
                matched_records=matched_records,
                imported_records=imported_records,
                skipped_records=skipped_records,
                files_read=files_read,
                pending_records=len(pending_tasks) + len(batch),
                current_url=processed.index_record.url,
                current_file=processed.index_record.filename,
                bytes_downloaded=bytes_downloaded,
                warc_requests=warc_requests,
            )
            await merge_pending_batch(
                current_url=processed.index_record.url,
                current_file=processed.index_record.filename,
            )

    async def cancel_pending_tasks() -> None:
        if len(pending_tasks) == 0:
            return
        tasks = list(pending_tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        pending_tasks.clear()
        pending_order.clear()

    async def wait_for_processed_record() -> None:
        while len(pending_order) > 0:
            task = pending_order[0]
            if not task.done():
                await asyncio.wait(
                    {task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                continue
            pending_order.pop(0)
            index_record = pending_tasks.pop(task)
            try:
                await handle_processed_record(task.result())
            except Exception:
                logger.exception(
                    "failed to import Common Crawl record %s from %s",
                    index_record.url,
                    index_record.filename,
                )
                await cancel_pending_tasks()
                raise
            return

    try:
        async for index_record in _iter_index_records(
            session=session,
            index=index,
            domain=domain,
            url_filter=url_filter,
            limit=limit,
            index_source=index_source,
            match_type=match_type,
            columnar_index_path=columnar_index_path,
            columnar_sql=columnar_sql,
            columnar_scan_partitions=columnar_scan_partitions,
            request_delay=index_request_delay,
            retries=index_retries,
            retry_delay=index_retry_delay,
            progress=progress,
        ):
            matched_records += 1
            files_read += 1
            task = asyncio.create_task(
                _process_index_record(
                    session=session,
                    index_record=index_record,
                    extractor=extractor,
                    primary_key=primary_key,
                    warc_retries=warc_retries,
                    warc_retry_delay=warc_retry_delay,
                )
            )
            pending_tasks[task] = index_record
            pending_order.append(task)
            await _report_progress(
                progress,
                stage="record_matched",
                matched_records=matched_records,
                imported_records=imported_records,
                skipped_records=skipped_records,
                files_read=files_read,
                pending_records=len(pending_tasks) + len(batch),
                current_url=index_record.url,
                current_file=index_record.filename,
                bytes_downloaded=bytes_downloaded,
                warc_requests=warc_requests,
            )
            if len(pending_tasks) >= warc_concurrency:
                await wait_for_processed_record()

        while len(pending_tasks) > 0:
            await wait_for_processed_record()
    except Exception:
        await cancel_pending_tasks()
        raise

    await merge_pending_batch(force=True)

    result = CommonCrawlImportResult(
        matched_records=matched_records,
        imported_records=imported_records,
        skipped_records=skipped_records,
        files_read=files_read,
        bytes_downloaded=bytes_downloaded,
        warc_requests=warc_requests,
    )
    await _report_progress(
        progress,
        stage="completed",
        matched_records=result.matched_records,
        imported_records=result.imported_records,
        skipped_records=result.skipped_records,
        files_read=result.files_read,
        pending_records=0,
        bytes_downloaded=result.bytes_downloaded,
        warc_requests=result.warc_requests,
    )
    return result


async def _report_progress(
    progress: ProgressCallback | None,
    *,
    stage: str,
    matched_records: int,
    imported_records: int,
    skipped_records: int,
    files_read: int,
    pending_records: int,
    current_url: str | None = None,
    current_file: str | None = None,
    bytes_downloaded: int = 0,
    warc_requests: int = 0,
) -> None:
    if progress is None:
        return
    await progress(
        CommonCrawlImportProgress(
            stage=stage,
            matched_records=matched_records,
            imported_records=imported_records,
            skipped_records=skipped_records,
            files_read=files_read,
            pending_records=pending_records,
            current_url=current_url,
            current_file=current_file,
            bytes_downloaded=bytes_downloaded,
            warc_requests=warc_requests,
        )
    )


async def _process_index_record(
    *,
    session: "ClientSession",
    index_record: _CdxRecord,
    extractor: ExtractCallback,
    primary_key: str,
    warc_retries: int,
    warc_retry_delay: float,
) -> _ProcessedIndexRecord:
    rows: list[dict[str, Any]] = []
    skipped_records = 0
    metrics = _WarcFetchMetrics()
    async for warc_record, content in _iter_warc_records(
        session=session,
        index_record=index_record,
        retries=warc_retries,
        retry_delay=warc_retry_delay,
        metrics=metrics,
    ):
        extracted = await extractor(warc_record, content)
        if extracted is None:
            skipped_records += 1
            continue
        row = dict(extracted)
        if primary_key not in row:
            raise ValueError(
                f"extract callback must return primary key column {primary_key!r}"
            )
        rows.append(row)
    return _ProcessedIndexRecord(
        index_record=index_record,
        rows=rows,
        skipped_records=skipped_records,
        bytes_downloaded=metrics.bytes_downloaded,
        warc_requests=metrics.requests,
    )


async def _merge_batch(
    *,
    room: RoomClient,
    table: str,
    rows: list[dict[str, Any]],
    schema: pa.Schema | None,
    primary_key: str,
    namespace: list[str] | None,
    branch: str | None,
) -> pa.Schema:
    next_schema = _merge_schema(
        base=schema,
        rows=rows,
        primary_key=primary_key,
    )
    await _ensure_table(
        room=room,
        table=table,
        schema=next_schema,
        namespace=namespace,
        branch=branch,
    )
    await room.datasets.merge(
        table=table,
        on=primary_key,
        records=pa.Table.from_pylist(rows, schema=next_schema),
        namespace=namespace,
        branch=branch,
    )
    return next_schema


async def _ensure_table(
    *,
    room: RoomClient,
    table: str,
    schema: pa.Schema,
    namespace: list[str] | None,
    branch: str | None,
) -> None:
    await room.datasets.create_table_with_schema(
        name=table,
        schema=schema,
        mode="create_if_not_exists",
        namespace=namespace,
        branch=branch,
    )
    existing_schema = await room.datasets.inspect(
        table=table,
        namespace=namespace,
        branch=branch,
    )
    existing_names = set(existing_schema.names)
    missing_fields = {
        field.name: field for field in schema if field.name not in existing_names
    }
    if missing_fields:
        await room.datasets.add_columns(
            table=table,
            new_columns=missing_fields,
            namespace=namespace,
            branch=branch,
        )


async def _iter_index_records(
    *,
    session: "ClientSession",
    index: str,
    domain: str,
    url_filter: str | Sequence[str] | None,
    limit: int | None,
    index_source: IndexSource = "cdx",
    match_type: IndexMatchType = "domain",
    columnar_index_path: str = COMMONCRAWL_COLUMNAR_INDEX_PATH,
    columnar_sql: str | None = None,
    columnar_scan_partitions: int = COMMONCRAWL_COLUMNAR_SCAN_PARTITIONS,
    request_delay: float = COMMONCRAWL_INDEX_REQUEST_DELAY_SECONDS,
    retries: int = COMMONCRAWL_INDEX_RETRIES,
    retry_delay: float = COMMONCRAWL_INDEX_RETRY_DELAY_SECONDS,
    progress: ProgressCallback | None = None,
) -> AsyncIterator[_CdxRecord]:
    if index_source == "columnar":
        async for row in _iter_columnar_index_records(
            index=index,
            domain=domain,
            url_filter=url_filter,
            limit=limit,
            match_type=match_type,
            index_path=columnar_index_path,
            sql=columnar_sql,
            scan_partitions=columnar_scan_partitions,
            progress=progress,
        ):
            yield row
        return

    async for row in _iter_cdx_index_records(
        session=session,
        index=index,
        domain=domain,
        url_filter=url_filter,
        limit=limit,
        match_type=match_type,
        request_delay=request_delay,
        retries=retries,
        retry_delay=retry_delay,
    ):
        yield row


async def _iter_cdx_index_records(
    *,
    session: "ClientSession",
    index: str,
    domain: str,
    url_filter: str | Sequence[str] | None,
    limit: int | None,
    match_type: IndexMatchType,
    request_delay: float = COMMONCRAWL_INDEX_REQUEST_DELAY_SECONDS,
    retries: int = COMMONCRAWL_INDEX_RETRIES,
    retry_delay: float = COMMONCRAWL_INDEX_RETRY_DELAY_SECONDS,
) -> AsyncIterator[_CdxRecord]:
    params: list[tuple[str, str]] = [
        ("url", _domain_index_query(domain)),
        ("matchType", match_type),
        ("output", "json"),
        ("fl", "url,timestamp,mime,filename,offset,length"),
        ("filter", "status:200"),
    ]
    for filter_value in _url_filters(url_filter):
        params.append(("filter", f"~url:{filter_value}"))

    page_count_url = (
        f"{_index_base_url(index)}?{urlencode([*params, ('showNumPages', 'true')])}"
    )
    last_index_request_at: float | None = None

    async def wait_for_index_request() -> None:
        nonlocal last_index_request_at
        loop = asyncio.get_running_loop()
        if last_index_request_at is not None:
            elapsed = loop.time() - last_index_request_at
            if elapsed < request_delay:
                await asyncio.sleep(request_delay - elapsed)
        last_index_request_at = loop.time()

    page_count_text = await _read_commoncrawl_index_text(
        session=session,
        url=page_count_url,
        wait_for_request=wait_for_index_request,
        retries=retries,
        retry_delay=retry_delay,
    )
    if page_count_text is None:
        return
    page_count = json.loads(page_count_text)
    pages = int(page_count.get("pages", 1))

    emitted = 0
    for page in range(pages):
        page_params = [*params, ("page", str(page))]
        if limit is not None:
            remaining = limit - emitted
            if remaining <= 0:
                return
            page_params.append(("limit", str(remaining)))

        url = f"{_index_base_url(index)}?{urlencode(page_params)}"
        page_text = await _read_commoncrawl_index_text(
            session=session,
            url=url,
            wait_for_request=wait_for_index_request,
            retries=retries,
            retry_delay=retry_delay,
        )
        if page_text is None:
            continue
        for line in page_text.splitlines():
            line = line.strip()
            if line == "":
                continue
            yield _CdxRecord.from_json(json.loads(line))
            emitted += 1
            if limit is not None and emitted >= limit:
                return


async def _iter_columnar_index_records(
    *,
    index: str,
    domain: str,
    url_filter: str | Sequence[str] | None,
    limit: int | None,
    match_type: IndexMatchType,
    index_path: str,
    sql: str | None,
    scan_partitions: int,
    progress: ProgressCallback | None,
) -> AsyncIterator[_CdxRecord]:
    try:
        from datafusion import SessionConfig, SessionContext
    except ImportError as exc:
        raise RuntimeError(
            "Common Crawl columnar index queries require the `datafusion` package."
        ) from exc

    config = (
        SessionConfig()
        .with_target_partitions(scan_partitions)
        .with_repartition_file_scans(True)
        .with_parquet_pruning(True)
    )
    ctx = SessionContext(config)
    table_path = _columnar_table_path(
        index_path=index_path,
        index=index,
        sql=sql,
    )
    await _report_progress(
        progress,
        stage="index_registering",
        matched_records=0,
        imported_records=0,
        skipped_records=0,
        files_read=0,
        pending_records=0,
        current_file=table_path,
    )
    if table_path.startswith("s3://"):
        from datafusion.object_store import AmazonS3

        bucket = _s3_bucket_name(table_path)
        os.environ.setdefault("AWS_REQUEST_PAYER", "true")
        if not _has_aws_credentials():
            os.environ.setdefault("AWS_SKIP_SIGNATURE", "true")
        ctx.register_object_store(
            "s3://",
            AmazonS3(bucket_name=bucket, region="us-east-1"),
            None,
        )
    await _report_progress(
        progress,
        stage="index_listing",
        matched_records=0,
        imported_records=0,
        skipped_records=0,
        files_read=0,
        pending_records=0,
        current_file=table_path,
    )
    ctx.register_parquet(
        "ccindex",
        table_path,
        table_partition_cols=_columnar_partition_columns(sql=sql),
    )
    query = _columnar_index_sql(
        index=index,
        domain=domain,
        url_filter=url_filter,
        limit=limit,
        match_type=match_type,
        sql=sql,
    )
    await _report_progress(
        progress,
        stage="index_querying",
        matched_records=0,
        imported_records=0,
        skipped_records=0,
        files_read=0,
        pending_records=0,
        current_file=table_path,
    )
    emitted = 0
    async for batch in _iter_datafusion_batches_with_progress(
        stream=ctx.sql(query).execute_stream(),
        progress=progress,
        table_path=table_path,
        emitted_count=lambda: emitted,
    ):
        rows = _datafusion_batch_to_pylist(batch)
        await _report_progress(
            progress,
            stage="index_batch_scanned",
            matched_records=emitted,
            imported_records=0,
            skipped_records=0,
            files_read=emitted,
            pending_records=len(rows),
            current_file=table_path,
        )
        for row in rows:
            yield _columnar_row_to_cdx_record(row)
            emitted += 1
            if limit is not None and emitted >= limit:
                return


async def _iter_datafusion_batches_with_progress(
    *,
    stream: AsyncIterator[Any],
    progress: ProgressCallback | None,
    table_path: str,
    emitted_count: Callable[[], int],
) -> AsyncIterator[Any]:
    iterator = stream.__aiter__()
    while True:
        batch_task = asyncio.create_task(iterator.__anext__())
        try:
            while True:
                done, _ = await asyncio.wait(
                    {batch_task},
                    timeout=COMMONCRAWL_INDEX_SCAN_PROGRESS_SECONDS,
                )
                if len(done) > 0:
                    break
                emitted = emitted_count()
                await _report_progress(
                    progress,
                    stage="index_querying",
                    matched_records=emitted,
                    imported_records=0,
                    skipped_records=0,
                    files_read=emitted,
                    pending_records=0,
                    current_file=table_path,
                )
            try:
                yield batch_task.result()
            except StopAsyncIteration:
                return
        finally:
            if not batch_task.done():
                batch_task.cancel()
                await asyncio.gather(batch_task, return_exceptions=True)


def _columnar_index_sql(
    *,
    index: str,
    domain: str,
    url_filter: str | Sequence[str] | None,
    limit: int | None,
    match_type: IndexMatchType,
    sql: str | None,
) -> str:
    if sql is not None and sql.strip() != "":
        query = sql.strip().rstrip(";")
        if limit is not None:
            return f"SELECT * FROM ({query}) AS meshagent_columnar_query LIMIT {limit}"
        return query

    where_clauses = [
        "fetch_status = 200",
        "content_mime_detected = 'text/html'",
        "coalesce(lower(url_path), '') <> '/robots.txt'",
        _columnar_match_clause(domain=domain, match_type=match_type),
    ]
    where_clauses.extend(
        f"regexp_like(url, {_sql_string(filter_value)})"
        for filter_value in _url_filters(url_filter)
    )
    limit_clause = f"\nLIMIT {limit}" if limit is not None else ""
    return f"""
SELECT
  url,
  timestamp,
  mime,
  filename,
  "offset",
  length
FROM (
  SELECT
    url,
    fetch_time AS timestamp,
    content_mime_detected AS mime,
    warc_filename AS filename,
    warc_record_offset AS "offset",
    warc_record_length AS length,
    row_number() OVER (
      PARTITION BY url
      ORDER BY fetch_time DESC
    ) AS meshagent_url_rank
  FROM ccindex
  WHERE {" AND ".join(where_clauses)}
) AS meshagent_latest_urls
WHERE meshagent_url_rank = 1
ORDER BY url{limit_clause}
""".strip()


def _columnar_match_clause(*, domain: str, match_type: IndexMatchType) -> str:
    normalized = _domain_index_query(domain)
    if match_type == "host":
        return f"url_host_name = {_sql_string(normalized)}"
    return f"url_host_registered_domain = {_sql_string(normalized)}"


def _s3_bucket_name(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "s3" or parsed.netloc == "":
        raise ValueError("columnar S3 index path must include a bucket name")
    return parsed.netloc


def _columnar_table_path(*, index_path: str, index: str, sql: str | None) -> str:
    if sql is not None and sql.strip() != "":
        return index_path
    normalized = index_path.rstrip("/")
    if normalized.endswith("/subset=warc") or "/crawl=" in normalized:
        return f"{normalized}/"
    return f"{normalized}/crawl={index}/subset=warc/"


def _columnar_partition_columns(*, sql: str | None) -> list[tuple[str, pa.DataType]]:
    if sql is not None and sql.strip() != "":
        return [("crawl", pa.string()), ("subset", pa.string())]
    return []


def _has_aws_credentials() -> bool:
    return (
        "AWS_ACCESS_KEY_ID" in os.environ
        or "AWS_PROFILE" in os.environ
        or "AWS_WEB_IDENTITY_TOKEN_FILE" in os.environ
        or "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI" in os.environ
        or "AWS_CONTAINER_CREDENTIALS_FULL_URI" in os.environ
    )


def _columnar_row_to_cdx_record(row: Mapping[str, Any]) -> _CdxRecord:
    url = _columnar_required_string(row=row, names=("url",))
    filename = _columnar_required_string(row=row, names=("filename", "warc_filename"))
    timestamp = _columnar_timestamp(
        _columnar_optional_value(row=row, names=("timestamp", "fetch_time"))
    )
    mime_value = _columnar_optional_value(
        row=row,
        names=("mime", "content_mime_detected"),
    )
    return _CdxRecord(
        url=url,
        timestamp=timestamp,
        mime=str(mime_value) if mime_value is not None else None,
        filename=filename,
        offset=_columnar_required_int(
            row=row,
            names=("offset", "warc_record_offset"),
        ),
        length=_columnar_required_int(
            row=row,
            names=("length", "warc_record_length"),
        ),
    )


def _datafusion_batch_to_pylist(batch: Any) -> list[dict[str, Any]]:
    if isinstance(batch, pa.RecordBatch):
        return batch.to_pylist()
    return batch.to_pyarrow().to_pylist()


def _columnar_required_string(
    *,
    row: Mapping[str, Any],
    names: tuple[str, ...],
) -> str:
    value = _columnar_optional_value(row=row, names=names)
    if not isinstance(value, str) or value == "":
        raise ValueError(f"columnar index query must return {names[0]!r}")
    return value


def _columnar_required_int(
    *,
    row: Mapping[str, Any],
    names: tuple[str, ...],
) -> int:
    value = _columnar_optional_value(row=row, names=names)
    if value is None:
        raise ValueError(f"columnar index query must return {names[0]!r}")
    return int(value)


def _columnar_optional_value(
    *,
    row: Mapping[str, Any],
    names: tuple[str, ...],
) -> Any | None:
    for name in names:
        if name in row:
            return row[name]
    return None


def _columnar_timestamp(value: Any | None) -> str:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).strftime("%Y%m%d%H%M%S")
    if value is None:
        return ""
    text = str(value)
    digits = "".join(character for character in text if character.isdigit())
    if len(digits) >= 14:
        return digits[:14]
    return text


def _sql_string(value: str) -> str:
    return f"'{value.replace("'", "''")}'"


async def _read_commoncrawl_index_text(
    *,
    session: "ClientSession",
    url: str,
    wait_for_request: Callable[[], Awaitable[None]],
    retries: int,
    retry_delay: float,
) -> str | None:
    for attempt in range(retries + 1):
        await wait_for_request()
        async with session.get(url, headers=_commoncrawl_index_headers()) as response:
            if response.status == 404:
                return None
            if response.status == 503:
                await _handle_commoncrawl_index_503(
                    url=url,
                    attempt=attempt,
                    retries=retries,
                    retry_delay=retry_delay,
                )
                continue
            response.raise_for_status()
            return await response.text()
    raise RuntimeError("unreachable Common Crawl index retry state")


async def _handle_commoncrawl_index_503(
    *,
    url: str,
    attempt: int,
    retries: int,
    retry_delay: float,
) -> None:
    if attempt >= retries:
        raise RuntimeError(
            "Common Crawl CDX API returned HTTP 503. Slow down index requests; "
            "if your IP was temporarily blocked, Common Crawl recommends waiting "
            "24 hours before trying again. For broad filtering, use the columnar "
            "index with Athena or Spark instead."
        )
    delay = retry_delay * (2**attempt)
    logger.warning(
        "Common Crawl CDX API returned HTTP 503 for %s; retrying in %.1fs",
        url,
        delay,
    )
    if delay > 0:
        await asyncio.sleep(delay)


def _commoncrawl_index_headers() -> dict[str, str]:
    return {
        "Accept": "application/json, text/plain;q=0.9, */*;q=0.1",
        "User-Agent": COMMONCRAWL_USER_AGENT,
    }


async def _iter_warc_records(
    *,
    session: "ClientSession",
    index_record: _CdxRecord,
    retries: int = COMMONCRAWL_WARC_RETRIES,
    retry_delay: float = COMMONCRAWL_WARC_RETRY_DELAY_SECONDS,
    metrics: _WarcFetchMetrics | None = None,
) -> AsyncIterator[tuple["ArcWarcRecord", bytes]]:
    from warcio.archiveiterator import ArchiveIterator

    end = index_record.offset + index_record.length - 1
    headers = {"Range": f"bytes={index_record.offset}-{end}"}
    url = f"{COMMONCRAWL_DATA_BASE_URL}/{index_record.filename}"
    data = await _read_warc_range(
        session=session,
        url=url,
        headers=headers,
        retries=retries,
        retry_delay=retry_delay,
        metrics=metrics,
    )

    for warc_record in ArchiveIterator(BytesIO(data)):
        if warc_record.rec_type != "response":
            continue
        yield warc_record, warc_record.content_stream().read()


async def _read_warc_range(
    *,
    session: "ClientSession",
    url: str,
    headers: Mapping[str, str],
    retries: int,
    retry_delay: float,
    metrics: _WarcFetchMetrics | None,
) -> bytes:
    from aiohttp import ClientError

    for attempt in range(retries + 1):
        if metrics is not None:
            metrics.requests += 1
        try:
            async with session.get(url, headers=headers) as response:
                if response.status in COMMONCRAWL_WARC_TRANSIENT_STATUSES:
                    await _handle_commoncrawl_warc_transient(
                        url=url,
                        status=response.status,
                        attempt=attempt,
                        retries=retries,
                        retry_delay=retry_delay,
                    )
                    continue
                response.raise_for_status()
                data = await response.read()
                if metrics is not None:
                    metrics.bytes_downloaded += len(data)
                return data
        except (asyncio.TimeoutError, ClientError, OSError) as exc:
            if attempt >= retries:
                raise
            delay = retry_delay * (2**attempt)
            logger.warning(
                "Common Crawl WARC read failed for %s; retrying in %.1fs: %s",
                url,
                delay,
                exc,
            )
            if delay > 0:
                await asyncio.sleep(delay)
    raise RuntimeError("unreachable Common Crawl WARC retry state")


async def _handle_commoncrawl_warc_transient(
    *,
    url: str,
    status: int,
    attempt: int,
    retries: int,
    retry_delay: float,
) -> None:
    if attempt >= retries:
        raise RuntimeError(f"Common Crawl WARC read returned HTTP {status} for {url}")
    delay = retry_delay * (2**attempt)
    logger.warning(
        "Common Crawl WARC read returned HTTP %s for %s; retrying in %.1fs",
        status,
        url,
        delay,
    )
    if delay > 0:
        await asyncio.sleep(delay)


async def _default_extract(record: "ArcWarcRecord", content: bytes) -> dict[str, str]:
    content_type = _content_type(record)
    text = _content_text(content=content, content_type=content_type)
    return {
        "url": record.rec_headers.get_header("WARC-Target-URI") or "",
        "date": _warc_date(record.rec_headers.get_header("WARC-Date")),
        "content_type": content_type,
        "text": text,
    }


def _content_type(record: "ArcWarcRecord") -> str:
    content_type = ""
    if record.http_headers is not None:
        content_type = record.http_headers.get_header("Content-Type") or ""
    if content_type == "":
        content_type = record.rec_headers.get_header("Content-Type") or ""
    return content_type


def _warc_date(value: str | None) -> str:
    if value is None or value == "":
        return ""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _content_text(*, content: bytes, content_type: str) -> str:
    charset = _charset(content_type)
    decoded = content.decode(charset, errors="replace")
    normalized_content_type = content_type.lower()
    if "html" not in normalized_content_type and "xml" not in normalized_content_type:
        return decoded

    parser = _TextExtractor()
    parser.feed(decoded)
    parser.close()
    return parser.text()


def _charset(content_type: str) -> str:
    for key, value in parse_qsl(content_type.replace(";", "&"), keep_blank_values=True):
        if key.strip().lower() == "charset" and value.strip() != "":
            return value.strip()
    return "utf-8"


def _default_schema() -> pa.Schema:
    return pa.schema(
        [
            pa.field("url", pa.string(), nullable=False),
            pa.field("date", pa.string()),
            pa.field("content_type", pa.string()),
            pa.field("text", pa.string()),
        ]
    )


def _merge_schema(
    *,
    base: pa.Schema | None,
    rows: list[dict[str, Any]],
    primary_key: str,
) -> pa.Schema:
    inferred = pa.Table.from_pylist(rows).schema
    fields_by_name = {field.name: field for field in base} if base is not None else {}
    for field in inferred:
        if pa.types.is_null(field.type):
            field = pa.field(field.name, pa.string(), nullable=field.nullable)
        if field.name == primary_key:
            field = pa.field(field.name, field.type, nullable=False)
        fields_by_name.setdefault(field.name, field)

    if primary_key not in fields_by_name:
        raise ValueError(f"rows must include primary key column {primary_key!r}")
    return pa.schema(list(fields_by_name.values()))


def _dedupe_rows_by_primary_key(
    *,
    rows: list[dict[str, Any]],
    primary_key: str,
) -> list[dict[str, Any]]:
    rows_by_key: dict[Any, dict[str, Any]] = {}
    ordered_keys: list[Any] = []
    for row in rows:
        key = row[primary_key]
        if key not in rows_by_key:
            ordered_keys.append(key)
        rows_by_key[key] = row
    return [rows_by_key[key] for key in ordered_keys]


def _domain_index_query(domain: str) -> str:
    parsed = urlparse(domain)
    host = parsed.netloc or parsed.path.split("/", maxsplit=1)[0]
    normalized = host.strip().strip(".").lower()
    if normalized == "":
        raise ValueError("domain must be non-empty")
    return normalized


def _url_filters(url_filter: str | Sequence[str] | None) -> list[str]:
    if url_filter is None:
        return []
    if isinstance(url_filter, str):
        return [url_filter]
    return list(url_filter)


def _index_base_url(index: str) -> str:
    if index.startswith("http://"):
        raise ValueError("Common Crawl index URL must use HTTPS")
    if index.startswith("https://"):
        return index
    normalized = index if index.endswith("-index") else f"{index}-index"
    return f"{COMMONCRAWL_INDEX_BASE_URL}/{normalized}"

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from io import BytesIO
import json
import logging
from typing import TYPE_CHECKING, Any, TypeAlias
from urllib.parse import parse_qsl, urlencode, urlparse

import pyarrow as pa

from meshagent.api import RoomClient
from meshagent.api.http import new_client_session

if TYPE_CHECKING:
    from aiohttp import ClientSession
    from warcio.recordloader import ArcWarcRecord

logger = logging.getLogger(__name__)

COMMONCRAWL_INDEX_BASE_URL = "https://index.commoncrawl.org"
COMMONCRAWL_DATA_BASE_URL = "https://data.commoncrawl.org"

ExtractedRecord: TypeAlias = Mapping[str, Any]
ExtractCallback: TypeAlias = Callable[
    ["ArcWarcRecord", bytes],
    Awaitable[ExtractedRecord | None],
]


@dataclass(frozen=True)
class CommonCrawlImportResult:
    matched_records: int
    imported_records: int
    skipped_records: int
    files_read: int


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
    session: "ClientSession | None" = None,
    progress: ProgressCallback | None = None,
) -> CommonCrawlImportResult:
    """Import Common Crawl captures for a domain into a room dataset.

    `url_filter` is passed to the Common Crawl CDX API as `filter=~url:<value>`.
    Supply a sequence to pass multiple URL filters. The default extractor writes
    `url`, `date`, `content_type`, and `text`, merging on `url`. Pass `schema`
    when a custom extractor should create an empty table before the first row.
    Pass `progress` to receive async progress updates during the import.
    """

    if batch_size <= 0:
        raise ValueError("batch_size must be greater than zero")
    if primary_key == "":
        raise ValueError("primary_key must be non-empty")

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
    batch: list[dict[str, Any]] = []
    await _report_progress(
        progress,
        stage="started",
        matched_records=matched_records,
        imported_records=imported_records,
        skipped_records=skipped_records,
        files_read=files_read,
        pending_records=len(batch),
    )

    async for index_record in _iter_index_records(
        session=session,
        index=index,
        domain=domain,
        url_filter=url_filter,
        limit=limit,
    ):
        matched_records += 1
        files_read += 1
        await _report_progress(
            progress,
            stage="record_matched",
            matched_records=matched_records,
            imported_records=imported_records,
            skipped_records=skipped_records,
            files_read=files_read,
            pending_records=len(batch),
            current_url=index_record.url,
            current_file=index_record.filename,
        )
        try:
            async for warc_record, content in _iter_warc_records(
                session=session,
                index_record=index_record,
            ):
                extracted = await extractor(warc_record, content)
                if extracted is None:
                    skipped_records += 1
                    await _report_progress(
                        progress,
                        stage="record_skipped",
                        matched_records=matched_records,
                        imported_records=imported_records,
                        skipped_records=skipped_records,
                        files_read=files_read,
                        pending_records=len(batch),
                        current_url=index_record.url,
                        current_file=index_record.filename,
                    )
                    continue
                row = dict(extracted)
                if primary_key not in row:
                    raise ValueError(
                        f"extract callback must return primary key column {primary_key!r}"
                    )
                batch.append(row)
                await _report_progress(
                    progress,
                    stage="record_extracted",
                    matched_records=matched_records,
                    imported_records=imported_records,
                    skipped_records=skipped_records,
                    files_read=files_read,
                    pending_records=len(batch),
                    current_url=index_record.url,
                    current_file=index_record.filename,
                )
                if len(batch) >= batch_size:
                    schema = await _merge_batch(
                        room=room,
                        table=table,
                        rows=batch,
                        schema=schema,
                        primary_key=primary_key,
                        namespace=namespace,
                        branch=branch,
                    )
                    imported_records += len(batch)
                    batch = []
                    await _report_progress(
                        progress,
                        stage="batch_merged",
                        matched_records=matched_records,
                        imported_records=imported_records,
                        skipped_records=skipped_records,
                        files_read=files_read,
                        pending_records=len(batch),
                        current_url=index_record.url,
                        current_file=index_record.filename,
                    )
        except Exception:
            logger.exception(
                "failed to import Common Crawl record %s from %s",
                index_record.url,
                index_record.filename,
            )
            raise

    if batch:
        await _merge_batch(
            room=room,
            table=table,
            rows=batch,
            schema=schema,
            primary_key=primary_key,
            namespace=namespace,
            branch=branch,
        )
        imported_records += len(batch)
        batch = []
        await _report_progress(
            progress,
            stage="batch_merged",
            matched_records=matched_records,
            imported_records=imported_records,
            skipped_records=skipped_records,
            files_read=files_read,
            pending_records=len(batch),
        )

    result = CommonCrawlImportResult(
        matched_records=matched_records,
        imported_records=imported_records,
        skipped_records=skipped_records,
        files_read=files_read,
    )
    await _report_progress(
        progress,
        stage="completed",
        matched_records=result.matched_records,
        imported_records=result.imported_records,
        skipped_records=result.skipped_records,
        files_read=result.files_read,
        pending_records=0,
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
        )
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
) -> AsyncIterator[_CdxRecord]:
    params: list[tuple[str, str]] = [
        ("url", _domain_index_query(domain)),
        ("matchType", "domain"),
        ("output", "json"),
        ("fl", "url,timestamp,mime,filename,offset,length"),
        ("filter", "status:200"),
    ]
    for filter_value in _url_filters(url_filter):
        params.append(("filter", f"~url:{filter_value}"))
    if limit is not None:
        params.append(("limit", str(limit)))

    url = f"{_index_base_url(index)}?{urlencode(params)}"
    async with session.get(url) as response:
        if response.status == 404:
            return
        response.raise_for_status()
        async for raw_line in response.content:
            line = raw_line.decode("utf-8").strip()
            if line == "":
                continue
            yield _CdxRecord.from_json(json.loads(line))


async def _iter_warc_records(
    *,
    session: "ClientSession",
    index_record: _CdxRecord,
) -> AsyncIterator[tuple["ArcWarcRecord", bytes]]:
    from warcio.archiveiterator import ArchiveIterator

    end = index_record.offset + index_record.length - 1
    headers = {"Range": f"bytes={index_record.offset}-{end}"}
    url = f"{COMMONCRAWL_DATA_BASE_URL}/{index_record.filename}"

    async with session.get(url, headers=headers) as response:
        response.raise_for_status()
        data = await response.read()

    for warc_record in ArchiveIterator(BytesIO(data)):
        if warc_record.rec_type != "response":
            continue
        yield warc_record, warc_record.content_stream().read()


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
    if index.startswith("http://") or index.startswith("https://"):
        return index
    normalized = index if index.endswith("-index") else f"{index}-index"
    return f"{COMMONCRAWL_INDEX_BASE_URL}/{normalized}"

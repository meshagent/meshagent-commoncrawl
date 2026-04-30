from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timezone
import os
import sys
import types
from typing import Any

import pyarrow as pa
import pytest

from meshagent.commoncrawl import commoncrawl
from meshagent.commoncrawl.commoncrawl import CommonCrawlImportProgress, _CdxRecord


class _Headers:
    def __init__(self, values: dict[str, str]) -> None:
        self._values = values

    def get_header(self, name: str) -> str | None:
        return self._values.get(name)


class _WarcRecord:
    rec_type = "response"

    def __init__(self, *, url: str, date: str, content_type: str) -> None:
        self.rec_headers = _Headers(
            {
                "WARC-Target-URI": url,
                "WARC-Date": date,
                "Content-Type": "application/http; msgtype=response",
            }
        )
        self.http_headers = _Headers({"Content-Type": content_type})


class _FakeDatasets:
    def __init__(self) -> None:
        self.schema: pa.Schema | None = None
        self.create_calls: list[dict[str, Any]] = []
        self.add_columns_calls: list[dict[str, Any]] = []
        self.merge_calls: list[dict[str, Any]] = []

    async def create_table_with_schema(
        self,
        *,
        name: str,
        schema: pa.Schema,
        mode: str,
        namespace: list[str] | None = None,
        branch: str | None = None,
    ) -> None:
        self.create_calls.append(
            {
                "name": name,
                "schema": schema,
                "mode": mode,
                "namespace": namespace,
                "branch": branch,
            }
        )
        if self.schema is None:
            self.schema = schema

    async def inspect(
        self,
        *,
        table: str,
        namespace: list[str] | None = None,
        branch: str | None = None,
    ) -> pa.Schema:
        del table, namespace, branch
        return self.schema or pa.schema([])

    async def add_columns(
        self,
        *,
        table: str,
        new_columns: dict[str, pa.Field],
        namespace: list[str] | None = None,
        branch: str | None = None,
    ) -> None:
        self.add_columns_calls.append(
            {
                "table": table,
                "new_columns": new_columns,
                "namespace": namespace,
                "branch": branch,
            }
        )
        assert self.schema is not None
        self.schema = self.schema.append(next(iter(new_columns.values())))

    async def merge(
        self,
        *,
        table: str,
        on: str,
        records: pa.Table,
        namespace: list[str] | None = None,
        branch: str | None = None,
    ) -> None:
        self.merge_calls.append(
            {
                "table": table,
                "on": on,
                "records": records,
                "namespace": namespace,
                "branch": branch,
            }
        )


@dataclass
class _FakeRoom:
    datasets: _FakeDatasets


class _FakeSession:
    async def close(self) -> None:
        return None


class _FakeColumnarBatchStream:
    def __init__(self, batches: list[pa.RecordBatch]) -> None:
        self._batches = batches

    def __aiter__(self) -> AsyncIterator[pa.RecordBatch]:
        return self._iter()

    async def _iter(self) -> AsyncIterator[pa.RecordBatch]:
        for batch in self._batches:
            yield batch


class _FakeColumnarDataFrame:
    def __init__(self, batches: list[pa.RecordBatch]) -> None:
        self._batches = batches

    def execute_stream(self) -> _FakeColumnarBatchStream:
        return _FakeColumnarBatchStream(self._batches)


class _FakeSessionConfig:
    instances: list[_FakeSessionConfig] = []

    def __init__(self) -> None:
        self.target_partitions: int | None = None
        self.repartition_file_scans: bool | None = None
        self.parquet_pruning: bool | None = None
        _FakeSessionConfig.instances.append(self)

    def with_target_partitions(self, target_partitions: int) -> _FakeSessionConfig:
        self.target_partitions = target_partitions
        return self

    def with_repartition_file_scans(self, enabled: bool) -> _FakeSessionConfig:
        self.repartition_file_scans = enabled
        return self

    def with_parquet_pruning(self, enabled: bool) -> _FakeSessionConfig:
        self.parquet_pruning = enabled
        return self


class _FakeSessionContext:
    instances: list[_FakeSessionContext] = []
    batches: list[pa.RecordBatch] = []

    def __init__(self, config: _FakeSessionConfig | None = None) -> None:
        self.config = config
        self.object_store_calls: list[dict[str, Any]] = []
        self.register_calls: list[dict[str, Any]] = []
        self.queries: list[str] = []
        _FakeSessionContext.instances.append(self)

    def register_object_store(self, schema: str, store: Any, host: str | None) -> None:
        self.object_store_calls.append(
            {
                "schema": schema,
                "store": store,
                "host": host,
            }
        )

    def register_parquet(
        self,
        name: str,
        path: str,
        *,
        table_partition_cols: list[tuple[str, Any]] | None = None,
    ) -> None:
        self.register_calls.append(
            {
                "name": name,
                "path": path,
                "table_partition_cols": table_partition_cols,
            }
        )

    def sql(self, query: str) -> _FakeColumnarDataFrame:
        self.queries.append(query)
        return _FakeColumnarDataFrame(_FakeSessionContext.batches)


class _FakeAmazonS3:
    def __init__(self, *, bucket_name: str, region: str) -> None:
        self.bucket_name = bucket_name
        self.region = region


async def _fake_index_records(**kwargs: Any) -> AsyncIterator[_CdxRecord]:
    del kwargs
    yield _CdxRecord(
        url="https://example.com/a",
        timestamp="20240101000000",
        mime="text/html",
        filename="crawl/a.warc.gz",
        offset=0,
        length=10,
    )
    yield _CdxRecord(
        url="https://example.com/b",
        timestamp="20240101000001",
        mime="text/html",
        filename="crawl/b.warc.gz",
        offset=10,
        length=10,
    )


async def _fake_warc_records(
    *,
    index_record: _CdxRecord,
    **kwargs: Any,
) -> AsyncIterator[tuple[_WarcRecord, bytes]]:
    del kwargs
    yield (
        _WarcRecord(
            url=index_record.url,
            date="2024-01-01T00:00:00Z",
            content_type="text/html; charset=utf-8",
        ),
        b"<html><head><style>.x{}</style></head><body>Hello <b>page</b></body></html>",
    )


async def _fake_duplicate_index_records(**kwargs: Any) -> AsyncIterator[_CdxRecord]:
    del kwargs
    yield _CdxRecord(
        url="https://example.com/robots.txt",
        timestamp="20240101000000",
        mime="text/plain",
        filename="crawl/a.warc.gz",
        offset=0,
        length=10,
    )
    yield _CdxRecord(
        url="https://example.com/robots.txt",
        timestamp="20240102000000",
        mime="text/plain",
        filename="crawl/b.warc.gz",
        offset=10,
        length=10,
    )


async def _fake_duplicate_warc_records(
    *,
    index_record: _CdxRecord,
    **kwargs: Any,
) -> AsyncIterator[tuple[_WarcRecord, bytes]]:
    del kwargs
    yield (
        _WarcRecord(
            url=index_record.url,
            date=f"{index_record.timestamp[:4]}-{index_record.timestamp[4:6]}-"
            f"{index_record.timestamp[6:8]}T00:00:00Z",
            content_type="text/plain; charset=utf-8",
        ),
        f"capture {index_record.timestamp}".encode(),
    )


@pytest.mark.asyncio
async def test_import_domain_uses_default_columns_and_merge(monkeypatch) -> None:
    monkeypatch.setattr(commoncrawl, "_iter_index_records", _fake_index_records)
    monkeypatch.setattr(commoncrawl, "_iter_warc_records", _fake_warc_records)
    room = _FakeRoom(datasets=_FakeDatasets())

    result = await commoncrawl.import_domain_from_commoncrawl(
        room,  # type: ignore[arg-type]
        index="CC-MAIN-2025-08",
        domain="example.com",
        table="pages",
        batch_size=1,
        session=_FakeSession(),  # type: ignore[arg-type]
    )

    assert result.matched_records == 2
    assert result.imported_records == 2
    assert result.skipped_records == 0
    assert room.datasets.create_calls[0]["mode"] == "create_if_not_exists"
    assert room.datasets.merge_calls[0]["on"] == "url"
    assert room.datasets.merge_calls[0]["records"].to_pylist() == [
        {
            "url": "https://example.com/a",
            "date": "2024-01-01T00:00:00Z",
            "content_type": "text/html; charset=utf-8",
            "text": "Hello page",
        }
    ]


@pytest.mark.asyncio
async def test_import_domain_dedupes_primary_keys_before_merge(monkeypatch) -> None:
    monkeypatch.setattr(
        commoncrawl, "_iter_index_records", _fake_duplicate_index_records
    )
    monkeypatch.setattr(commoncrawl, "_iter_warc_records", _fake_duplicate_warc_records)
    room = _FakeRoom(datasets=_FakeDatasets())

    result = await commoncrawl.import_domain_from_commoncrawl(
        room,  # type: ignore[arg-type]
        index="CC-MAIN-2025-08",
        domain="example.com",
        table="pages",
        batch_size=10,
        session=_FakeSession(),  # type: ignore[arg-type]
    )

    assert result.matched_records == 2
    assert result.imported_records == 1
    assert room.datasets.merge_calls[0]["records"].to_pylist() == [
        {
            "url": "https://example.com/robots.txt",
            "date": "2024-01-02T00:00:00Z",
            "content_type": "text/plain; charset=utf-8",
            "text": "capture 20240102000000",
        }
    ]


@pytest.mark.asyncio
async def test_extract_callback_can_filter_records(monkeypatch) -> None:
    monkeypatch.setattr(commoncrawl, "_iter_index_records", _fake_index_records)
    monkeypatch.setattr(commoncrawl, "_iter_warc_records", _fake_warc_records)
    room = _FakeRoom(datasets=_FakeDatasets())

    async def extract(record: _WarcRecord, content: bytes) -> dict[str, str] | None:
        del content
        url = record.rec_headers.get_header("WARC-Target-URI") or ""
        if url.endswith("/b"):
            return None
        return {"url": url, "title": "A"}

    result = await commoncrawl.import_domain_from_commoncrawl(
        room,  # type: ignore[arg-type]
        index="CC-MAIN-2025-08",
        domain="example.com",
        extract=extract,  # type: ignore[arg-type]
        session=_FakeSession(),  # type: ignore[arg-type]
    )

    assert result.matched_records == 2
    assert result.imported_records == 1
    assert result.skipped_records == 1
    assert room.datasets.merge_calls[0]["records"].to_pylist() == [
        {"url": "https://example.com/a", "title": "A"}
    ]


@pytest.mark.asyncio
async def test_import_domain_reports_progress(monkeypatch) -> None:
    monkeypatch.setattr(commoncrawl, "_iter_index_records", _fake_index_records)
    monkeypatch.setattr(commoncrawl, "_iter_warc_records", _fake_warc_records)
    room = _FakeRoom(datasets=_FakeDatasets())
    updates: list[CommonCrawlImportProgress] = []

    async def progress(update: CommonCrawlImportProgress) -> None:
        updates.append(update)

    result = await commoncrawl.import_domain_from_commoncrawl(
        room,  # type: ignore[arg-type]
        index="CC-MAIN-2025-08",
        domain="example.com",
        batch_size=2,
        session=_FakeSession(),  # type: ignore[arg-type]
        progress=progress,
    )

    assert result.imported_records == 2
    assert [update.stage for update in updates] == [
        "started",
        "record_matched",
        "record_matched",
        "record_extracted",
        "record_extracted",
        "batch_merged",
        "completed",
    ]
    assert updates[-1].matched_records == 2
    assert updates[-1].imported_records == 2
    assert updates[-1].pending_records == 0


@pytest.mark.asyncio
async def test_iter_columnar_index_records_uses_generated_datafusion_sql(
    monkeypatch,
) -> None:
    _FakeSessionContext.instances = []
    _FakeSessionContext.batches = [
        pa.RecordBatch.from_pylist(
            [
                {
                    "url": "https://www.example.com/a",
                    "timestamp": datetime(2024, 1, 2, tzinfo=timezone.utc),
                    "mime": "text/html",
                    "filename": "crawl/a.warc.gz",
                    "offset": 10,
                    "length": 20,
                }
            ]
        )
    ]
    monkeypatch.setitem(
        sys.modules,
        "datafusion",
        types.SimpleNamespace(
            SessionConfig=_FakeSessionConfig,
            SessionContext=_FakeSessionContext,
        ),
    )
    updates: list[CommonCrawlImportProgress] = []

    async def progress(update: CommonCrawlImportProgress) -> None:
        updates.append(update)

    rows = [
        row
        async for row in commoncrawl._iter_index_records(
            session=_FakeSession(),  # type: ignore[arg-type]
            index="CC-MAIN-2025-08",
            domain="www.example.com",
            url_filter=r"^https?://www\.example\.com(/.*)?$",
            limit=10,
            index_source="columnar",
            match_type="host",
            columnar_index_path="/tmp/ccindex",
            progress=progress,
        )
    ]

    assert rows == [
        _CdxRecord(
            url="https://www.example.com/a",
            timestamp="20240102000000",
            mime="text/html",
            filename="crawl/a.warc.gz",
            offset=10,
            length=20,
        )
    ]
    context = _FakeSessionContext.instances[0]
    assert context.config is not None
    assert context.config.target_partitions == 64
    assert context.config.repartition_file_scans is True
    assert context.config.parquet_pruning is True
    assert context.register_calls[0]["name"] == "ccindex"
    assert (
        context.register_calls[0]["path"]
        == "/tmp/ccindex/crawl=CC-MAIN-2025-08/subset=warc/"
    )
    query = context.queries[0]
    assert "FROM ccindex" in query
    assert "url_host_name = 'www.example.com'" in query
    assert "regexp_like(url, '^https?://www\\.example\\.com(/.*)?$')" in query
    assert "row_number() OVER" in query
    assert "LIMIT 10" in query
    assert [update.stage for update in updates] == [
        "index_registering",
        "index_listing",
        "index_querying",
        "index_batch_scanned",
    ]
    assert updates[-1].pending_records == 1


@pytest.mark.asyncio
async def test_iter_columnar_index_records_registers_commoncrawl_s3_store(
    monkeypatch,
) -> None:
    _FakeSessionContext.instances = []
    _FakeSessionContext.batches = []
    monkeypatch.delenv("AWS_SKIP_SIGNATURE", raising=False)
    monkeypatch.delenv("AWS_REQUEST_PAYER", raising=False)
    monkeypatch.setitem(
        sys.modules,
        "datafusion",
        types.SimpleNamespace(
            SessionConfig=_FakeSessionConfig,
            SessionContext=_FakeSessionContext,
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "datafusion.object_store",
        types.SimpleNamespace(AmazonS3=_FakeAmazonS3),
    )

    rows = [
        row
        async for row in commoncrawl._iter_index_records(
            session=_FakeSession(),  # type: ignore[arg-type]
            index="CC-MAIN-2025-08",
            domain="example.com",
            url_filter=None,
            limit=1,
            index_source="columnar",
            match_type="domain",
            columnar_index_path="s3://commoncrawl/cc-index/table/cc-main/warc/",
        )
    ]

    assert rows == []
    context = _FakeSessionContext.instances[0]
    assert context.object_store_calls[0]["schema"] == "s3://"
    assert context.object_store_calls[0]["host"] is None
    store = context.object_store_calls[0]["store"]
    assert store.bucket_name == "commoncrawl"
    assert store.region == "us-east-1"
    assert (
        context.register_calls[0]["path"]
        == "s3://commoncrawl/cc-index/table/cc-main/warc/"
        "crawl=CC-MAIN-2025-08/subset=warc/"
    )
    assert os.environ["AWS_SKIP_SIGNATURE"] == "true"
    assert os.environ["AWS_REQUEST_PAYER"] == "true"


@pytest.mark.asyncio
async def test_iter_columnar_index_records_accepts_custom_sql(monkeypatch) -> None:
    _FakeSessionContext.instances = []
    _FakeSessionContext.batches = [
        pa.RecordBatch.from_pylist(
            [
                {
                    "url": "https://example.com/custom",
                    "fetch_time": "2024-01-03 04:05:06",
                    "content_mime_detected": "text/html",
                    "warc_filename": "crawl/custom.warc.gz",
                    "warc_record_offset": 30,
                    "warc_record_length": 40,
                }
            ]
        )
    ]
    monkeypatch.setitem(
        sys.modules,
        "datafusion",
        types.SimpleNamespace(
            SessionConfig=_FakeSessionConfig,
            SessionContext=_FakeSessionContext,
        ),
    )

    rows = [
        row
        async for row in commoncrawl._iter_index_records(
            session=_FakeSession(),  # type: ignore[arg-type]
            index="CC-MAIN-2025-08",
            domain="example.com",
            url_filter=None,
            limit=5,
            index_source="columnar",
            match_type="domain",
            columnar_index_path="/tmp/ccindex",
            columnar_sql="SELECT * FROM ccindex WHERE url LIKE 'https://example.com/%'",
        )
    ]

    assert [row.url for row in rows] == ["https://example.com/custom"]
    assert rows[0].timestamp == "20240103040506"
    query = _FakeSessionContext.instances[0].queries[0]
    assert query.startswith("SELECT * FROM (SELECT * FROM ccindex")
    assert query.endswith("LIMIT 5")


def test_commoncrawl_index_url_helpers() -> None:
    assert commoncrawl._domain_index_query("https://Example.COM/docs") == "example.com"
    assert commoncrawl._url_filters(["a", "b"]) == ["a", "b"]
    assert commoncrawl._index_base_url("CC-MAIN-2025-08").endswith(
        "/CC-MAIN-2025-08-index"
    )
    with pytest.raises(ValueError, match="must use HTTPS"):
        commoncrawl._index_base_url(
            "http://index.commoncrawl.org/CC-MAIN-2025-08-index"
        )


def test_generated_columnar_sql_parses_in_datafusion() -> None:
    pytest.importorskip("datafusion")

    query = commoncrawl._columnar_index_sql(
        index="CC-MAIN-2026-17",
        domain="www.walmart.com",
        url_filter=r"^https?://www\.walmart\.com(/.*)?$",
        limit=1000000,
        match_type="host",
        sql=None,
    )
    wrapped_query = query.replace(
        "FROM ccindex",
        """FROM (
          SELECT
            'https://www.walmart.com/' AS url,
            timestamp '2026-01-01 00:00:00' AS fetch_time,
            'text/html' AS content_mime_detected,
            'crawl/a.warc.gz' AS warc_filename,
            0 AS warc_record_offset,
            10 AS warc_record_length,
            200 AS fetch_status,
            '/' AS url_path,
            'www.walmart.com' AS url_host_name,
            'walmart.com' AS url_host_registered_domain
        ) AS ccindex""",
    )

    from datafusion import SessionContext

    rows = SessionContext().sql(wrapped_query).collect()[0].to_pylist()
    assert rows == [
        {
            "url": "https://www.walmart.com/",
            "timestamp": datetime(2026, 1, 1, 0, 0),
            "mime": "text/html",
            "filename": "crawl/a.warc.gz",
            "offset": 0,
            "length": 10,
        }
    ]


@pytest.mark.asyncio
async def test_index_404_is_treated_as_no_matches() -> None:
    class _Content:
        def __aiter__(self) -> AsyncIterator[bytes]:
            return self._iter()

        async def _iter(self) -> AsyncIterator[bytes]:
            if False:
                yield b""

    class _Response:
        status = 404
        content = _Content()

        async def __aenter__(self) -> _Response:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        def raise_for_status(self) -> None:
            raise AssertionError("404 should not raise")

        async def text(self) -> str:
            raise AssertionError("404 should not be read")

    class _Session:
        def get(self, url: str, **kwargs: Any) -> _Response:
            assert kwargs["headers"]["User-Agent"].startswith("meshagent-commoncrawl/")
            assert "matchType=domain" in url
            assert "url=www.hersheyland.com" in url
            assert "filter=~url%3A%5Ehttps%3F%3A%2F%2Fwww" in url
            return _Response()

    rows = [
        row
        async for row in commoncrawl._iter_index_records(
            session=_Session(),  # type: ignore[arg-type]
            index="CC-MAIN-2025-08",
            domain="www.hersheyland.com",
            url_filter=r"^https?://www\.hersheyland\.com(/.*)?$",
            limit=None,
            index_source="cdx",
            request_delay=0,
        )
    ]

    assert rows == []


@pytest.mark.asyncio
async def test_iter_index_records_reads_paginated_cdx_pages() -> None:
    class _Content:
        def __init__(self, lines: list[bytes]) -> None:
            self._lines = lines

        def __aiter__(self) -> AsyncIterator[bytes]:
            return self._iter()

        async def _iter(self) -> AsyncIterator[bytes]:
            for line in self._lines:
                yield line

    class _Response:
        def __init__(
            self,
            *,
            status: int = 200,
            text: str = "",
            lines: list[bytes] | None = None,
        ) -> None:
            self.status = status
            self._text = text
            self._lines = lines or []
            self.content = _Content(lines or [])

        async def __aenter__(self) -> _Response:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        def raise_for_status(self) -> None:
            if self.status >= 400:
                raise AssertionError(f"unexpected HTTP status {self.status}")

        async def text(self) -> str:
            if self._text != "":
                return self._text
            return b"".join(self._lines).decode()

    def row(url: str) -> bytes:
        return (
            b'{"url":"'
            + url.encode()
            + b'","timestamp":"20240101000000","mime":"text/html",'
            + b'"filename":"crawl/a.warc.gz","offset":"0","length":"10"}\n'
        )

    class _Session:
        def __init__(self) -> None:
            self.urls: list[str] = []

        def get(self, url: str, **kwargs: Any) -> _Response:
            assert kwargs["headers"]["User-Agent"].startswith("meshagent-commoncrawl/")
            self.urls.append(url)
            if "showNumPages=true" in url:
                return _Response(text='{"pages": 4}')
            if "page=0" in url:
                return _Response(lines=[row("https://example.com/a")])
            if "page=1" in url:
                return _Response(lines=[row("https://example.com/b")])
            if "page=2" in url:
                return _Response(status=404)
            if "page=3" in url:
                return _Response(lines=[row("https://example.com/c")])
            raise AssertionError(f"unexpected URL {url}")

    session = _Session()
    rows = [
        row
        async for row in commoncrawl._iter_index_records(
            session=session,  # type: ignore[arg-type]
            index="CC-MAIN-2025-08",
            domain="example.com",
            url_filter=None,
            limit=None,
            index_source="cdx",
            request_delay=0,
        )
    ]

    assert [row.url for row in rows] == [
        "https://example.com/a",
        "https://example.com/b",
        "https://example.com/c",
    ]
    assert len(session.urls) == 5


@pytest.mark.asyncio
async def test_iter_index_records_applies_limit_across_pages() -> None:
    class _Content:
        def __init__(self, lines: list[bytes]) -> None:
            self._lines = lines

        def __aiter__(self) -> AsyncIterator[bytes]:
            return self._iter()

        async def _iter(self) -> AsyncIterator[bytes]:
            for line in self._lines:
                yield line

    class _Response:
        def __init__(self, *, text: str = "", lines: list[bytes] | None = None) -> None:
            self.status = 200
            self._text = text
            self._lines = lines or []
            self.content = _Content(lines or [])

        async def __aenter__(self) -> _Response:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        def raise_for_status(self) -> None:
            return None

        async def text(self) -> str:
            if self._text != "":
                return self._text
            return b"".join(self._lines).decode()

    def row(url: str) -> bytes:
        return (
            b'{"url":"'
            + url.encode()
            + b'","timestamp":"20240101000000","mime":"text/html",'
            + b'"filename":"crawl/a.warc.gz","offset":"0","length":"10"}\n'
        )

    class _Session:
        def __init__(self) -> None:
            self.urls: list[str] = []

        def get(self, url: str, **kwargs: Any) -> _Response:
            assert kwargs["headers"]["User-Agent"].startswith("meshagent-commoncrawl/")
            self.urls.append(url)
            if "showNumPages=true" in url:
                return _Response(text='{"pages": 3}')
            if "page=0" in url:
                assert "limit=2" in url
                return _Response(lines=[row("https://example.com/a")])
            if "page=1" in url:
                assert "limit=1" in url
                return _Response(lines=[row("https://example.com/b")])
            raise AssertionError(f"unexpected URL {url}")

    session = _Session()
    rows = [
        row
        async for row in commoncrawl._iter_index_records(
            session=session,  # type: ignore[arg-type]
            index="CC-MAIN-2025-08",
            domain="example.com",
            url_filter=None,
            limit=2,
            index_source="cdx",
            request_delay=0,
        )
    ]

    assert [row.url for row in rows] == [
        "https://example.com/a",
        "https://example.com/b",
    ]
    assert len(session.urls) == 3


@pytest.mark.asyncio
async def test_iter_index_records_reports_503_rate_limit_guidance() -> None:
    class _Content:
        def __aiter__(self) -> AsyncIterator[bytes]:
            return self._iter()

        async def _iter(self) -> AsyncIterator[bytes]:
            if False:
                yield b""

    class _Response:
        status = 503
        content = _Content()

        async def __aenter__(self) -> _Response:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        def raise_for_status(self) -> None:
            raise AssertionError("503 should produce Common Crawl guidance")

    class _Session:
        def get(self, url: str, **kwargs: Any) -> _Response:
            del url
            assert kwargs["headers"]["User-Agent"].startswith("meshagent-commoncrawl/")
            return _Response()

    with pytest.raises(RuntimeError, match="CDX API returned HTTP 503"):
        _ = [
            row
            async for row in commoncrawl._iter_index_records(
                session=_Session(),  # type: ignore[arg-type]
                index="CC-MAIN-2025-08",
                domain="example.com",
                url_filter=None,
                limit=None,
                index_source="cdx",
                request_delay=0,
                retries=0,
            )
        ]

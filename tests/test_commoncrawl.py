from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
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
        "record_extracted",
        "record_matched",
        "record_extracted",
        "batch_merged",
        "completed",
    ]
    assert updates[-1].matched_records == 2
    assert updates[-1].imported_records == 2
    assert updates[-1].pending_records == 0


def test_commoncrawl_index_url_helpers() -> None:
    assert commoncrawl._domain_index_query("https://Example.COM/docs") == "example.com"
    assert commoncrawl._url_filters(["a", "b"]) == ["a", "b"]
    assert commoncrawl._index_base_url("CC-MAIN-2025-08").endswith(
        "/CC-MAIN-2025-08-index"
    )


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

    class _Session:
        def get(self, url: str) -> _Response:
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
        )
    ]

    assert rows == []

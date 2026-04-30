# Meshagent Common Crawl

Import Common Crawl captures into a Meshagent room dataset.

```python
from meshagent.commoncrawl import import_domain_from_commoncrawl

result = await import_domain_from_commoncrawl(
    room,
    index="CC-MAIN-2025-08",
    domain="example.com",
    table="pages",
    url_filter=r"https?://(www\.)?example\.com/docs/.*",
)
```

To test it through `meshagent room connect`:

```bash
meshagent room connect --room=my-room --identity=commoncrawl -- \
  python meshagent-sdk/meshagent-commoncrawl/examples/crawl.py \
  http://www.meshagent.com --table=sample --namespace=crawls --limit=10
```

The example defaults to `--scope=host`, so `https://www.example.com` imports
only captures from `www.example.com`. Use `--scope=domain` when you explicitly
want sibling subdomains too, for example when a large site stores useful content
outside `www`.

The sample command writes progress to stderr while it imports. TTY output uses a
single updating line; redirected output uses plain log lines. Pass `--silent` to
suppress progress output. Columnar scans emit periodic heartbeat updates while
waiting for DataFusion batches. WARC reads run concurrently by default and report
queued records, downloaded bytes, and request counts; use `--scan-partitions` to
tune DataFusion scan parallelism and `--concurrency`, `--warc-retries`, and
`--warc-retry-delay` to tune object reads.

The importer uses Common Crawl's columnar index by default through DataFusion.
Basic imports generate a SQL query that selects one latest HTML capture per URL
from the requested host or domain, excluding `robots.txt`. Advanced callers can
pass `columnar_sql=` to control the URL selection directly; the query must return
`url` plus WARC pointer columns (`filename`/`offset`/`length` or the Common Crawl
names `warc_filename`/`warc_record_offset`/`warc_record_length`). The example CLI
exposes this as `--sql`.

Common Crawl's CDX API is rate limited and not a good fit for broad filtering.
The SDK still contains the polite CDX reader for compatibility, using
`https://index.commoncrawl.org`, a Meshagent User-Agent, serialized/paced
requests, and clearer HTTP 503 guidance.

By default, records are merged on `url` with the columns `url`, `date`,
`content_type`, and `text`. Pass an async `extract=` callback to derive custom
columns from the WARC record and decoded content bytes. Return `None` from the
callback to skip the record. Pass an async `progress=` callback to observe import
progress from library code.

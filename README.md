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

The sample command writes progress to stderr while it imports. TTY output uses a
single updating line; redirected output uses plain log lines. Pass `--silent` to
suppress progress output.

By default, records are merged on `url` with the columns `url`, `date`,
`content_type`, and `text`. Pass an async `extract=` callback to derive custom
columns from the WARC record and decoded content bytes. Return `None` from the
callback to skip the record. Pass an async `progress=` callback to observe import
progress from library code.

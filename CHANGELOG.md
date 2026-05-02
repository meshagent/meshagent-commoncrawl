## [0.39.7]
- Documentation cleanup: removed stale archived Python example agents/services/webserver routes.
- Documentation cleanup: removed several Python service example entrypoints (browser, document author, presentation author, voice, voice proofreader, voice tools).

## [0.39.6]
- CLI help docs generation was rewritten to recursively render command documentation for lazy-loaded Click/Typer command trees, with more robust hidden/deprecated filtering and deterministic command-block generation.
- CLI help reference generation now normalizes command output to produce stable reference content.
- Skill package validation now permits missing top-level help command references for `webserver`.

## [0.39.5]
- Added Scrapy crawler HTML/content stripping configuration via new `strip` and `strip_order` inputs (including support for stripping `scripts`, `css`, `whitespace`, `clean`, and `image-data-urls`)
- Changed default behavior for `content_format="html"` to strip `scripts` and inline image data URLs while preserving the rest of the HTML (and updated `--clean` CLI usage to map onto the new stripping configuration)
- Broke Scrapy dataset output schema by removing `links`, `link_urls`, `image_urls`, and reducing `images` to `src`/`alt` only; inline image data URLs are excluded from extracted images
- Changed index creation defaults: automatic creation no longer includes inverted/label indexes for removed link/image URL columns; `text` inverted index creation is now opt-in via `index_columns=("text",)`
- Updated generated dataset schema to apply ZSTD compression metadata to large string fields (including `text` and image fields)

## [0.39.4]
- Switched Common Crawl imports to use the columnar Parquet index by default through DataFusion, with generated SQL for basic host/domain imports and an advanced custom SQL option.
- Added periodic columnar scan progress, configurable DataFusion scan partitioning, and concurrent WARC range reads with retry, downloaded-byte, request-count, and queue reporting.
- Fixed Common Crawl imports with multiple captures of the same URL in one batch by deduplicating primary keys before merge.
- Added an explicit `--scope=domain` option to the Common Crawl example so broad subdomain imports are opt-in instead of implied by `www` URLs.
- Updated Common Crawl CDX access to use paginated index reads, HTTPS-only index URLs, a Meshagent User-Agent, serialized/paced requests, and clearer HTTP 503 rate-limit guidance.
- Breaking: Python scheduled-task client and spec models now use a `ScheduledTaskSpec` contract (including queue/container targeting) instead of separate queue/schedule/payload parameters.
- Added Python scheduled-task run listing support with models/pages for runs and their status/attempt/timestamp fields.
- Updated scheduled-task client methods to support `room_id` filtering and the new spec-based request/response shapes.
- Added/updated CLI scheduled-task create/update flows to load the `ScheduledTaskSpec` from a YAML file and included new run-related CLI functionality.
- Removed generated CLI dataset functionality (including the previously available SQL-exec command).
- Added `croniter~=6.0` as a dependency to support cron parsing for scheduled tasks.

## [0.39.3]
- Added `meshagent-commoncrawl` package with Common Crawl import support (progress reporting, dataset record extraction/import utilities, and tests); includes dependencies such as `pyarrow~=21.0.0` and `warcio~=1.7`.
- Added `meshagent-scrapy` package with Scrapy-based dataset import support (scrapy import utilities, examples, and tests); includes dependencies such as `scrapy~=2.13`, `trafilatura~=2.0`, and `pyarrow~=21.0.0`.
- Updated OpenAI Responses adapter error handling to detect out-of-credits/`insufficient_quota` conditions and return a clearer non-retryable 402 response; also improved websocket error payload message extraction.
- Updated `meshagent-cli` default model selections from `gpt-5.4` to `gpt-5.5` across ask/chatbot/codex/task runner/mailbot/worker CLI flows.
- Updated `meshagent-cli` and `meshagent-python` packaging extras to include `meshagent-commoncrawl` and `meshagent-scrapy` (including dedicated `commoncrawl`/`scrapy` extras).
- Added/updated tests for the new OpenAI out-of-credits handling and for commoncrawl/scrapy importer functionality.

## [0.39.2]
- Added `meshagent-commoncrawl` with Common Crawl domain imports into room datasets.

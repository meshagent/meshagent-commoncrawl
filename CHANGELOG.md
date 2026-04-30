## [0.39.4]
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

## [0.46.3]
- Process, task-runner, and worker defaults now use `gpt-5.6-sol`, and process model and thread-storage normalization now raises proper CLI parameter errors instead of generic value errors.
- Process specs now emit stable YAML and use the renamed `--require-document-authoring` room requirement flag.
- Queue send now reads `--file` input as JSON text, and setup and project loading now honor explicit API URL overrides.
- OpenAI pricing and usage accounting now cover GPT-5.6, GPT-5.5 Pro, and GPT-5.4 Pro families, including cache-write tokens, long-context pricing, and the `1,050,000`-token GPT-5.6 context window.

## [0.46.2]
- Python SDK project models now support mapping-style field checks and indexing, making `ProjectInfo` and `ProjectsPage` easier to use with `in` and `[]` access patterns.

## [0.46.1]
- Breaking change: `ServicesClient.list()` now returns the combined services-and-runtime-state result instead of a bare service list, so callers that only need service definitions must read the `services` field.

## [0.46.0]
- Stability

## [0.45.9]
- Breaking change: `SecretVersion.encryption_key_id` was removed from the generated API model and cloud resource records.
- Room service APIs now return typed runtime status, including `list()`, `ServiceRuntimeStatus`, and `ServicePortRuntimeState`, so clients can inspect per-port liveness.
- CLI room helpers now honor the room URL returned by the connection, `MESHAGENT_ROOM_URL` can override it, room-service output includes port liveness, and session list/traces can emit JSON for automation.
- Document runtime and schema loading now preserve property metadata and route sync callbacks through the active runtime instance.
- Playwright automation is more resilient, with stale-container recreation, longer startup/connect attempts, and clearer startup/reconnect progress.

## [0.45.8]
- Stability

## [0.45.7]
- Tightened container-shell input validation and managed-container parsing so malformed `commands`, `container_id`, `env`, and timeout fields fail fast with clearer errors.
- Changed container mount merging to stop carrying project mounts into the merged shell mount spec.
- Improved tool hosting error mapping and remote-tool message validation so invalid payloads surface as invalid-request errors.
- Simplified the image pack/build flow and changed default image tagging so non-BuildKit images use the `-nydus` suffix while BuildKit and Playwright defaults keep the plain version tag.
- Adjusted computer automation to preserve blocked-URL handling correctly and fixed async mouse drag execution in Docker-backed computers.
- Made memory-toolkit and remote graph loading more resilient when using remote storage roots and room-local API endpoints.

## [0.45.6]
- Added strict dataset prompt rendering with escaped-brace support and simple field placeholders, replacing generic `str.format` expansion.
- Tightened OpenAI adapter handling so code-interpreter results must be structured objects with required string fields, and invalid payloads now error out earlier.
- Aligned computer/browser tooling with Python behavior for Browserbase setup, Docker geometry handling, and optional rule initialization.
- Synchronized Python package dependencies and release metadata across the API, agents, CLI, OpenAI, tools, computers, codex, and related companion packages.

## [0.45.5]
- Shell command analysis now handles mixed absolute and dynamic write targets more safely, keeping generated file previews and path grouping accurate.

## [0.45.4]
- Stability

## [0.45.3]
- Added `whoami`, typed `ServiceAccount.email`, and service-account `view` filtering.
- Hardened shared HTTP session creation with certifi-backed TLS, optional host aliases, and an extra CA bundle.
- Exposed service runtime startup errors and event histories through room service-state responses.
- Added `pull_secret` support for service container specs and enforced id-only secret payloads, breaking older named-secret service specs.
- Updated agent chat and thread handling to consume direct payload envelopes, clean outbound metadata, and match the newer completion/thread message shape.
- Expanded OpenAI, Anthropic, CLI, and tool parity so web fetch/grep, HTML-to-Markdown, regex handling, data URLs, Docker subprocesses, and MCP/web tool behavior more closely match Python semantics.
- Removed deprecated compatibility aliases around thread adapters and managed-agent exports.

## [0.45.2]
- Added `whoami`, typed `ServiceAccount.email`, and service-account `view` filtering, and hardened shared HTTP session creation with certifi-backed TLS, optional host aliases, and an extra CA bundle.
- Exposed service runtime startup errors and event histories through room service state responses.
- Added `pull_secret` to service container specs and enforced id-only secret payloads, which is a breaking change for older named-secret service specs.
- Updated agent chat and thread handling to consume direct payload envelopes, clean outbound metadata, and align completions/thread behavior with the newer message shape.
- Expanded OpenAI, Anthropic, CLI, and tool parity so web fetch/grep, HTML-to-Markdown, regex handling, data URLs, Docker subprocesses, and MCP/web tool behavior more closely match Python semantics.
- Removed deprecated compatibility aliases around thread adapters and managed-agent exports, and updated related tests and package wiring accordingly.

## [0.45.1]
- `meshagent.api` now supports `view` on service-account listing, and the shared HTTP helper uses certifi-backed TLS with optional host aliases and an extra CA bundle.
- The CLI image and deploy helpers now preserve digest-pinned published refs, canonicalize image mounts, and use personal-room paging for room-connect flows.
- Web, dataset, script, and computer tooling were tightened to match Python semantics more closely for filename inference, charset decoding, HTML-to-Markdown conversion, regex behavior, environment-variable handling, and Docker subprocess execution.
- OpenAI, Anthropic, and agent abstractions gained parity updates for threaded channels, completions/response streaming, and raw-output handling.

## [0.45.0]
- Added `whoami` support plus typed `ServiceAccount.email` and `Whoami` responses in the API client.
- Exposed service runtime startup errors and lifecycle events through room service state responses.
- Added `pull_secret` to container specs and tightened secret validation to id-only payloads, breaking legacy secret objects.
- Expanded the room-services CLI with a `describe` command and richer list output that includes runtime events, and updated image deploy cleanup to run after deploy completion.
- Removed the `thread_adapter` alias, require `thread_storage`, and switched queue targeting to `path` instead of `thread_id`, which is a breaking change for existing agent integrations.
- Improved dataset tooling and OpenAI code-interpreter handling, including Python-compatible row formatting, binary row support, and correct log/file aggregation.

## [0.44.13]
- Stability

## [0.44.12]
- Added generated project support flows across the SDK Python CLI and API, including visible-room selection, deploy helpers, and broader create-template coverage.
- Expanded generated Python app templates with a new task queue dashboard app, simpler install/dev scripts, and safer contact-form and mailbox delivery behavior.
- Added session log and metrics CLI commands, plus support helpers for `SingleRoomAgent` and toolkit annotation preservation in room listings.
- Fixed OpenAI shell-output restoration and corrected audio transcription pricing and reasoning-token accounting.
- Improved template and deployment robustness with stale deploy-value handling and other create-flow hardening.

## [0.44.11]
- Stability

## [0.44.10]
- Stability

## [0.44.9]
- Stability

## [0.44.8]
- Stability

## [0.44.7]
- Realtime websocket sessions now expand nested namespace toolkits into individual function tools, improving support for live tool advertising in OpenAI realtime flows.

## [0.44.6]
- Breaking: Codex setup now uses a single default-provider flow and removes the older multi-profile conflict/update screens.
- Codex setup now detects all MeshAgent-managed Codex configs instead of only the active project or API host, so stale configs can be updated or removed during setup.

## [0.44.5]
- OpenAI completions now emit structured assistant text and tool-call lifecycle events, including arguments and results, so consumers can reconstruct streamed assistant and tool activity.
- Reasoning-end events are now preserved even when no active reasoning buffer exists, as long as metadata is available, which restores reasoning dataset replay.
- OpenAI response handling now includes all structured output items instead of only message and compaction items, improving replay coverage for additional response types.

## [0.44.4]
- Breaking: `AgentSessionContext` no longer exposes `previous_messages` or `previous_response_id`; restore flows now operate from the current `messages` payload instead of maintaining a separate history buffer.
- OpenAI Responses restore now preserves encrypted reasoning metadata, normalizes legacy reasoning items, and forces stateless requests to use `store=False` while replaying the current context.
- Agent event handling and dataset thread storage now keep reasoning provider/model metadata so empty reasoning items with encrypted content can still be restored without losing the payload.
- Managed agents now share the `llm` backend abstraction, which changes thread creation and resume behavior and lets thread naming consider the selected provider/model plus audio attachments.
- Updated `typer` to `~=0.26.6`.

## [0.44.3]
- Stability

## [0.44.2]
- Base chat clients now expose an async event stream for consuming emitted agent payloads alongside listener callbacks.
- Messaging chat clients now distinguish first connect from reconnect, track participant add/remove events, and reopen open sessions when the agent returns.
- Restored session context now resolves stored room file URLs into inline attachments, including PDF and image handling for OpenAI- and Anthropic-style message content.
- Fresh turns no longer trigger redundant storage restoration when there is no prior thread history.

## [0.44.1]
- Stability

## [0.44.0]
- Python agent processes now support multiple thread storages, thread watch/unwatch flows, and storage-aware list/view routing for thread lifecycle operations.
- Thread startup now preserves better thread naming and metadata, including fallback names derived from message content and attachments when no explicit name is provided.
- Managed-agent server code now creates thread metadata earlier and persists thread naming information consistently through websocket-driven lifecycles.
- Single-room and Codex orchestration now avoid unnecessary toolkit-discovery waits and improve startup latency and initialization behavior.

## [0.43.4]
- Public room toolkit metadata now preserves annotations end-to-end, and the SDK exports tool-search metadata for consumers that need to discover searchable tools.
- Tool listings now round-trip annotations alongside tools and participant IDs, so extra toolkit metadata is no longer lost when clients read or write it.
- Agent and room message handling now keeps `created_at` timestamps through streamed deltas and live thread updates, improving ordering and replay consistency.
- Responses integration now supports tool namespaces and search across the Python agent tooling stack.

## [0.43.3]
- Stability

## [0.43.2]
- Added backend-aware fields across agent messages and chat/session APIs in `meshagent-agents`, enabling multi-backend conversations, model changes, and room/thread opening flows.
- Breaking: `meshagent-codex` was reorganized around a dedicated process, supervisor, and thread-storage stack, so the old internal process/chat wiring moved.
- Removed the mandatory Codex binary wheel dependency and vendored the OpenAI Codex client into `meshagent-codex`.
- Added thread inspection and thread-storage diagnostics for Codex sessions, along with no-room process mode and improved inline attachment handling in the CLI.
- Added IAP websocket support in `meshagent-api`, including nullable tokens, `withIAP()`, and Authorization-header based connections.

## [0.43.1]
- Added IAP room websocket support in the SDK chat and channel stack.
- Reworked the CLI around a unified process backend and Codex integration, replacing the older Codex-specific launch path and changing thread loading semantics.
- Added multi-backend support, the Codex thread-storage repository and diagnostics, and managed thread-storage fixes so threads can be loaded, renamed, and deleted through the new repository flow.
- Added TUI image attachment support with `textual-image[textual]~=0.12.0`.
- Removed the hard dependency on the Codex binary wheel.

## [0.43.0]
- `meshagent-agents` now supports backend-aware multi-backend supervision, with backend metadata in thread/model messages, attachment-aware prompts, and backend-aware thread/model/realtime-audio operations.
- `meshagent-codex` was split into a dedicated process, supervisor, and thread-storage stack and now vendors `openai_codex`, with a new `meshagent-openai==0.42.2` dependency.
- `meshagent-cli` now uses Typer consistently, adds lazy command loading, image/PDF/file paste-and-drop handling for `ask`, thread-sidebar controls, and improved `doctor`, `create`, and deploy-room workflows, including new room-workspace and meeting templates.
- `meshagent-openai` now preserves image-generation call inputs and emits structured image-generation results, and the LLM proxy and agent server websocket auth path now accept the `meshagent-agent.` token prefix.
- Third-party dependency updates include `textual-image[textual]~=0.12.0` for inline image rendering.

## [0.42.2]
- Added `wait_for_exit_status` and richer container/build models, exposing image IDs, runtime stats, published build image digests, and detailed exit status information while keeping the existing integer exit-code helper.
- The deploy flow now resolves completed builds to published digests, rewrites deploy plans to use the resolved image reference, and cleans up replaced built images after successful deploys.
- Room client shutdown is now cancellation-safe, so protocol teardown completes even if exit is cancelled mid-close.
- CLI API URL resolution now prefers `MESHAGENT_API_URL` before the persisted active URL, matching the explicit environment override users expect.

## [0.42.1]
- Deploy liveness checks now treat `401` and `403` responses as live, improving detection for protected endpoints.
- Deploy log streaming now cancels background log and progress tasks cleanly on exit, avoiding hangs during shutdown.
- Deploy TUI now supports copying selected text or the full deploy log buffer to the clipboard.

## [0.42.0]
- Added project lookup by key.
- Service and route specs now support container templates, `host_port`, and `stripPrefix`; route-path serialization omits `stripPrefix` when it is false.
- Room/container responses now expose structured port mappings instead of bare integers, which is a breaking shape change for container listings.
- Room creation and room-service helpers now carry annotations and permissions through the API.
- Container creation and room-client helpers now accept the `template` option.

## [0.41.10]
- Breaking change: several resource lookup commands now use `get` instead of `show`, including API keys, feeds, LLM loggers, mailboxes, registries, routes, services, sessions, storage, and subscriptions.
- Added `get` commands for projects, dataset branches, and webhooks, plus a `get` alias for memory inspection.

## [0.41.9]
- Deployment config models now carry an optional server version, and `meshagent config get version` can surface it.
- `meshagent` now performs a best-effort startup version check, warns when the installed client is older than the server, and `meshagent version` reports both client and server versions instead of the previous raw version string, so scripts that parse the old output need to update.

## [0.41.8]
- Stability

## [0.41.7]
- Deployment config models now carry optional server version metadata, allowing API consumers to read the server version from config responses.
- CLI config lookup now supports returning the deployment version, and the version command now prints both client and server versions.
- The CLI startup path now performs a best-effort server version check and emits a one-time warning when the CLI is behind the server.

## [0.41.6]
- Added deploy-ready project scaffolding and the Python contact-form starter, including deploy/dev/install scripts and generated deployment links.
- Improved CLI ask/deploy flows with room selection, domain entry, service lookup, and template-variable prompts.
- Extended the Python API client and cloud router to resolve services by name in both project and room scopes.
- Added attachment-aware signed download URLs across the Python storage stack so files can be served inline or as forced downloads.

## [0.41.5]
- Stability

## [0.41.4]
- `ChatThreadSession` now exposes thread-start, turn-steer, and interrupt workflows, along with richer pending-input state and active-turn tracking for acceptance, application, and rejection events.
- Container and service models now support a `template` value (`agent` or `none`), and container runs can opt into that template to receive the standard agent runtime environment and mount defaults.

## [0.41.3]
- Stability

## [0.41.2]
- `meshagent create` now uses clearer stable focus IDs and labels, adds an Anthropic chatbot option, and prints grouped next steps plus agent-toolkit deploy guidance for backend-agent templates.
- `meshagent rooms list` now defaults to rooms the current user can access, with `--all` to switch back to listing every room in the project.
- Deploy-room prompting now derives the Pages suffix from the configured API host, pre-fills a room-based subdomain, and validates subdomain-only input before constructing the final public domain.
- The CLI chat and process runtime now centralize turn-toolkit assembly and thread-list tooling through the supervisor, while websocket chat sessions keep web participants aligned with the base participant identity for on-behalf-of access.

## [0.41.1]
- Python feed subscription APIs and CLI commands now support an optional `filename_datetime_format`, and listing shows the stored value.
- The create workflow now prints a `cd` hint for new subfolders and blocks reusing an already occupied nested folder.
- Image deploys now preserve Dockerfile default environment values and clear the newly built image from the room cache after a successful build.

## [0.41.0]
- Managed-agent support now includes thread listing, thread create/update/delete events, attachment names, and sender-name trust for chat input.
- Websocket process support now uses `/messages`, adds `jwt`/`iap`/`none` auth modes, and supports websocket-based `process use` sessions.
- Route handling now uses the spec-based route model and supports room or agent backends.
- The CLI gained new agent/process/route flows, removed the `codex` command, and added `ascii-magic~=2.3`, `pillow~=11.3.0`, and `msgpack~=1.1`.
- Managed-agent storage and shell toolkits were removed from the public managed-agent surface.
- OpenAI, Anthropic, browser, computer, and toolkit helpers were updated to work with the new managed-agent and client-toolkit plumbing.
- Fixed thread storage, chat replay, and process shutdown races.

## [0.40.3]
- Added managed-agent spec and API models covering allowed models, toolkits, secrets, MCP servers, thread isolation, agent/room grants, and agent session listing.
- Route APIs now use `RouteSpec` with room or agent backends and preserve compatibility with legacy route payloads.
- Chat and channel code now supports websocket transport, participant connect/disconnect events, sender-name propagation, and attachment-aware thread start/load flows.
- Added a new `create` scaffolder with Dart, .NET, JavaScript, Python, React, and TypeScript templates, replacing the old `init`/Codex entrypoints.
- Added CLI dependencies on `ascii-magic~=2.3` and `pillow~=11.3.0`.

## [0.40.2]
- Stability

## [0.40.1]
- Stability

## [0.40.0]
- Added realtime model selection, audio modality, and protocol negotiation support across the Python agents, CLI, OpenAI, and Anthropic adapters.
- Reworked ask/process and dataset/thread handling to support new-thread loading, multi-user TUI flows, richer status reporting, and friendlier tool summaries.
- Improved crawler, roompool, and offline-wait behavior for local routing and cached room provisioning.
- Added `sounddevice~=0.5` to the CLI dependency set.
- Removed the restored agent event metadata mirror, so downstream consumers now rely on the canonical event metadata source.

## [0.39.9]
- Added/expanded `meshagent init` and `meshagent doctor` CLI workflows in the Python SDK, including TUI init improvements.
- Expanded `meshagent doctor` to provide richer, toolchain-aware diagnostics (Python/TypeScript/.NET), including stronger deployment/runtime guidance and missing toolchain detection.
- Implemented dataset table rename support and SDK dataset toolkit support for renamed dataset handling.
- Improved dataset path restoration and dataset-backed conversation handling in the SDK.
- Implemented dataset thread storage in the SDK, including dataset thread storage/watch plumbing for dataset-scoped conversation threads.
- Added SDK wiring for error reporting and transaction reconciliation-related CLI behavior.

## [0.39.8]
- Added `rename_table` support to the Python datasets client API (`DatasetsClient.rename_table`) for renaming dataset tables with optional namespace/branch
- Updated image dataset schema to store the image data column as `large_binary` (instead of `binary`) for newly created datasets
- Updated scrapy/dataset schema handling to use `large_string` for large compressed text fields (including image `src`/`alt`)
- CLI: ask-style TUI now supports a configurable assistant label name
- CLI: `meshagent process use` now routes through a room chat-channel session and streams text deltas into the ask-style TUI

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

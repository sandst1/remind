# Changelog

All notable changes to Remind.

## [Unreleased]

## [0.10.0] - 2026-04-08

### Added
- **Native vector indexes** — Retrieval now uses `sqlite-vec` on SQLite and `pgvector` on PostgreSQL when available, with automatic brute-force cosine fallback.
- **Cross-encoder reranking** — Optional reranking stage for recall (`sentence-transformers`) with configurable `recall_initial_candidates`.
- **Hybrid retrieval scoring** — Embedding similarity is fused with keyword overlap via configurable `hybrid_keyword_weight`.
- **Topics as first-class partitions** — `topic` support on episodes/concepts with topic-aware consolidation and retrieval behavior.
- **Topic APIs/tools** — `list_topics` and `topic_overview` available in CLI, MCP, and Python API.
- **Ingest controls** — Optional ingest `instructions` plus topic inference when topic is omitted.
- **Configurable `episode_types`** — Plan/spec/task CLI and MCP surfaces register only when enabled.
- **Project-local config** — `.remind/remind.config.json` supported alongside project database.
- **SQLAlchemy databases** — PostgreSQL and MySQL support through `REMIND_DB_URL` / `db_url`.
- **Parallel consolidation and richer stats** — Faster batch consolidation and episode type breakdowns in stats.
- **Memory metadata additions** — `source_type` on episodes and `supersedes` relation surfaced in recall.

### Changed
- **Auto-ingest** — Removed configurable density-threshold gating; improved chunking and text processing.
- **Consolidation & extraction** — Tuned prompts, token limits, and concurrency defaults for better quality/throughput.
- **Retrieval runtime** — Improved recall performance, including reranker warm-up behavior in CLI workflows.
- **Web UI** — Better handling for custom episode types, topics, task flows, and non-SQLite database URLs/paths.

### Fixed
- Reconsolidation edge cases.
- MCP episode argument parsing.
- Task creation from the web UI.
- Web UI and stats with PostgreSQL and other SQLAlchemy URLs.
- Embedding dimension handling and reranker NaN-score safety.

## [0.8.0] - 2026-03-23

### Added
- **Episode embeddings** — `remember` now embeds episode content by default for direct vector search during recall. Use `--no-embed` to skip (faster, no API call).
- **Direct episode recall** — `recall --episode-k N` (CLI) or `episode_k` parameter (Python/MCP) retrieves episodes by embedding similarity alongside concept-based spreading activation. Default: 5. Set to 0 to disable.
- **`embed-episodes` command** — Backfill embeddings for episodes created before episode embedding was enabled.
- **Contradiction display** — Recall output now shows inbound and outbound `contradicts` relations per concept, with context.
- **Batched contradiction detection** — Consolidation compares new material against existing concepts in configurable batches (`consolidation_concepts_per_pass`, default: 64).

### Changed
- Azure OpenAI provider upgraded to OpenAI v1 API; `api_version` config removed, `/openai/v1` appended to base URL automatically
- Default `episode_k` set to 5 for direct episode recall

### Fixed
- Ingest buffer handling in foreground mode
- Async processing fixes in background worker
- Contradiction retrieval improvements (batched comparison against existing concepts)

## [0.7.0] - 2026-03-19

### Added
- **Auto-ingest pipeline** — `ingest()` and `flush_ingest()` for automatic memory curation. Buffers raw text, scores information density via LLM, and distills memory-worthy episodes automatically. Available via CLI, MCP, and Python API.
- **Fact episodes** — New `fact` episode type for specific factual assertions (config values, names, dates, technical details). Consolidation preserves fact details verbatim rather than generalizing them away.
- **Outcome episodes** — New `outcome` episode type for action-result pairs with structured metadata (`strategy`, `result`, `prediction_error`). Consolidation extracts causal strategy patterns.
- **Entity name matching in retrieval** — Queries now match against entity names directly (fast, no embedding needed), complementing semantic search.
- **Minimum activation floor** — Retrieval drops concepts below a configurable `min_activation` threshold (default: 0.15), reducing low-relevance noise.
- **Entity deduplication** — Entity extraction deduplicates by name across types to prevent duplicates like `family:Capulet` and `character:Capulet`.
- **`status` CLI command** — Shows processing status: running workers, pending episodes, queued ingest chunks.
- **Per-provider ingest model** — Configure a separate (cheaper/faster) model for triage without affecting consolidation quality.
- **Debug file logging** — Enable `logging_enabled` in config to get full LLM prompt/response logs in `remind.log` next to the database.
- **Background ingest worker** — CLI `ingest` command queues work and spawns a background worker by default. Use `--foreground` for synchronous processing.
- **Batch consolidation progress** — `consolidate` and `reconsolidate` commands show per-batch progress for large runs.
- **Hybrid recall episodes** — Retrieval now returns source episodes with type labels and entity context alongside concepts.

### Changed
- Default recall `k` reduced from 5 to 3 for more focused results
- `recall` no longer requires a query when `--entity` is provided
- `end-session` now flushes the ingestion buffer before consolidating
- Consolidation loops through all batches internally instead of requiring external batch loop
- Foreground consolidation acquires a file lock to prevent concurrent runs

## [0.6.0] - 2026-03-09

### Added
- Task management system: task episodes with status tracking (todo, in_progress, done, blocked), dependency chains, plan/spec linking, and priority levels
- Agent workflow skills for the plan-to-implementation lifecycle:
  - `remind` -- base memory operations reference
  - `remind-plan` -- interactive planning with sparring and crystallization
  - `remind-spec` -- spec-driven development with lifecycle management
  - `remind-implement` -- systematic task execution loop
- Active tasks are excluded from consolidation; completed tasks become eligible

### Changed
- Updated web UI

### Fixed
- `run_async` helper function

## [0.5.3] - 2026-03-03

### Fixed
- When updating episodes, reset entity associations so they are rebuilt on next consolidation

## [0.5.2] - 2026-03-02

### Fixed
- Actually include web UI static files in wheel builds

## [0.5.1] - 2026-03-02

### Fixed
- Include built web UI assets in package

## [0.5.0] - 2026-03-02

### Added
- Support for updating and deleting concepts and episodes
- Built-in memories about Remind itself for self-aware assistance

### Changed
- Consolidation is now non-blocking, improving CLI responsiveness

### Fixed
- Explicit consolidation command now works correctly
- Build issues resolved

## [0.4.0] - 2026-02-26

### Added
- Memory decay system: concepts gradually lose retrieval priority based on recall frequency
  - `decay_factor` (0.0--1.0) multiplies retrieval activation score
  - Decay runs every N recalls with configurable rate
  - Rejuvenation: recalled concepts receive activation-proportional boost
  - 60-second grace window protects recently-accessed concepts
- `DecayConfig` in config file under `"decay"` key
- Metadata table in SQLite for persistent key-value storage
- Memory status panel in web UI

## [0.3.1] - 2026-02-25

### Fixed
- Bump numpy requirement to `>=2.0.0` to prevent segfault on macOS in sandboxed environments

## [0.3.0] - 2026-02-25

### Added
- Global config file support (`~/.remind/remind.config.json`)
- `--version` CLI argument
- Collapsible sidebar in web UI
- Agent skills support for Claude Code integration

### Fixed
- Entity relationship extraction
- Consolidation with explicit entities

## [0.2.0] - 2026-01-09

### Added
- Web UI with interactive concept graph visualization (D3-based)
- Docker support
- Entity inspection UI and MCP tools
- LLM-powered query answering with source episodes
- Dark mode support
- Batch consolidation and reconsolidation

## [0.1.0] - 2026-01-04

### Added
- Core memory system with episodes and concepts
- Spreading activation retrieval algorithm
- LLM-powered consolidation
- Entity extraction from episodes
- Provider support: Anthropic, OpenAI, Azure OpenAI, Ollama
- MCP server (SSE mode)
- CLI tool
- SQLite persistence layer
- Background consolidation
- Project-aware database paths

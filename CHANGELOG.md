# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added
- Episode embeddings: `remember` now embeds episode content by default for direct vector search during recall. Use `--no-embed` to skip embedding (faster, no API call).
- Direct episode recall via `recall --episode-k N` (CLI) or `episode_k` parameter (Python/MCP). Retrieves episodes by embedding similarity alongside concept-based spreading activation. Default: 5. Set to 0 to disable.
- `remind embed-episodes` CLI command to backfill embeddings for episodes created before episode embedding was enabled
- Contradiction display in recall output: each concept now shows inbound and outbound `contradicts` relations with context
- Batched contradiction detection during consolidation, controlled by `consolidation_concepts_per_pass` config (default: 64)

### Changed
- Azure OpenAI provider upgraded to OpenAI v1 API; `api_version` config removed, `/openai/v1` appended to base URL automatically
- Default `episode_k` set to 5 for direct episode recall

### Fixed
- Ingest buffer handling in foreground mode
- Async processing fixes in background worker
- Contradiction retrieval improvements (batched comparison against existing concepts)

## [0.7.0] - 2026-03-19

### Added
- Auto-ingest mode: LLM-powered triage pipeline that buffers raw text, scores information density, and extracts memory-worthy episodes automatically
  - `IngestionBuffer` accumulates text until a configurable threshold (~4000 chars)
  - `IngestionTriager` uses an LLM to score density (0.0–1.0) and extract distilled episodes, including outcome detection
  - New `ingest()` and `flush_ingest()` methods on `MemoryInterface`
  - New `remind ingest` and `remind flush-ingest` CLI commands
  - New `ingest` and `flush_ingest` MCP tools
- Non-blocking ingestion: triage and consolidation run in background workers to avoid blocking the caller
- Configurable ingest model: each provider supports a separate `ingest_model` for cheaper/faster triage (e.g., Haiku for triage, Sonnet for consolidation)
- Hybrid recall with entity name matching: retrieval now does fast entity-name lookups alongside embedding search, improving recall for queries that mention known entities
- `ScoredEpisode` dataclass for ranked episode results from hybrid recall
- Batch episode retrieval (`get_episodes_batch`) and entity word search (`search_entities_by_words`, `find_episodes_by_entities`) in the store layer
- `remind status` CLI command showing processing status (workers, queues)
- Configurable file logging (`logging_enabled` in config, `REMIND_LOGGING_ENABLED` env var) with per-database log files
- Episode type weights for retrieval scoring (facts and decisions ranked higher than meta/tasks)
- Minimum activation floor on retrieval to filter out noise

### Changed
- Default recall `k` reduced from 5 to 3 for more focused results
- Consolidation now processes all pending episodes in batches with optional progress callback
- Consolidation prompts improved: fact episodes preserve specific details verbatim; outcome episodes extract strategy-outcome patterns with causal relations
- Extraction phase now deduplicates entity names, merging entities that share the same display name regardless of type prefix
- Entity IDs normalized to lowercase throughout
- Recall query argument is now optional when using `--entity` flag
- Updated documentation site with auto-ingest guide, expanded configuration docs, and new MCP tool references

### Fixed
- `remind status` command crash
- Entity name deduplication during extraction (prevents `family:Capulet` vs `character:Capulet` splits)
- Triage batching: ingestion buffer now processed in proper batches

## [0.6.1] - 2026-03-17

### Added
- Documentation site (VitePress-based) with landing page, guides, concept explainers, real-world examples, and reference pages, deployed to GitHub Pages

### Changed
- Updated README to point to the new docs site
- Tweaked UI icons

### Fixed
- Main page links in website
- Skill installer updated to install latest Remind skills

### Added
- Task editing support in the web UI
- Allow linking existing tasks to plans and specs

## [0.6.0] - 2026-03-09

### Added
- Task management system: task episodes with status tracking (todo, in_progress, done, blocked), dependency chains, plan/spec linking, and priority levels
- Agent workflow skills for the plan-to-implementation lifecycle:
  - `remind` – base memory operations reference
  - `remind-plan` – interactive planning with sparring and crystallization
  - `remind-spec` – spec-driven development with lifecycle management
  - `remind-implement` – systematic task execution loop
- Active tasks are excluded from consolidation; completed tasks become eligible, allowing the system to learn from finished work

### Changed
- Updated web UI

### Fixed
- `run_async` helper function

## [0.5.3] - 2026-03-03

### Fixed
- When updating episodes, reset entity associations so they are rebuilt on next consolidation

## [0.5.2] - 2026-03-02

### Fixed
- Actually include web UI static files in wheel builds (force-include was only configured for sdist, not wheel)

## [0.5.1] - 2026-03-02

### Fixed
- Include built web UI assets in package (was missing from 0.5.0 release)

## [0.5.0] - 2026-03-02

### Added
- Support for updating and deleting concepts and episodes
- Built-in memories about Remind itself for self-aware assistance

### Changed
- Consolidation is now non-blocking, improving CLI responsiveness

### Fixed
- Explicit consolidation command now works correctly
- Build issues resolved
- Changelog skill now works in Claude Code

## [0.4.0] - 2026-02-26

### Added
- Memory decay system: concepts gradually lose retrieval priority based on how rarely they are recalled, mimicking human forgetting
  - `decay_factor` (0.0–1.0) multiplies each concept's retrieval activation score
  - Decay runs every N recalls (`decay_interval`, default 20), reducing `decay_factor` by `decay_rate` (default 0.1) using a single SQL update for O(1) performance
  - Rejuvenation: recalled concepts receive an activation-proportional boost to their `decay_factor`; recently-accessed concepts are protected by a 60-second grace window so they are not penalised immediately after being recalled
  - Recall count is persisted in the database across process restarts, so decay works correctly with the CLI
  - Decay stats visible in `remind stats` (enabled state, recall count, next decay, avg/min decay factor)
- `DecayConfig` in `~/.remind/remind.config.json` under the `"decay"` key with `enabled`, `decay_interval`, and `decay_rate` options
- Metadata table in SQLite for persistent key-value storage (currently used for recall count)
- Memory status panel in web UI and recall count shown in concepts view

## [0.3.1] - 2026-02-25

### Fixed
- Bump numpy requirement to `>=2.0.0` to prevent segfault on macOS in sandboxed environments (e.g. Cursor agent terminal) caused by numpy 1.26.x `_mac_os_check` startup self-test

## [0.3.0] - 2026-02-25

### Added
- Global config file support (`~/.remind/remind.config.json`) for centralized configuration
- `--version` CLI argument to display current version
- Collapsible sidebar in web UI
- Agent skills support for Claude Code integration
- UI can now be run from any directory

### Fixed
- Entity relationship extraction
- Consolidation with explicit entities

## [0.2.0] - 2026-01-09

### Added
- Web UI with interactive concept graph visualization (D3-based)
- Docker support for containerized deployment
- Entity inspection UI and MCP tools
- LLM-powered query answering with source episodes
- Dark mode support
- Batch consolidation and reconsolidation
- Concept and entity filtering in UI
- Entity relationship inference
- Concept titles for better readability
- Episode titles in UI

### Changed
- Improved concept list ordering (alphabetical)
- Enhanced graph visualization

## [0.1.0] - 2026-01-04

### Added
- Core memory system with episodes and concepts
- Spreading activation retrieval algorithm
- LLM-powered consolidation (episode to concept transformation)
- Entity extraction from episodes
- Provider support: Anthropic, OpenAI, Azure OpenAI, Ollama
- MCP server (SSE mode)
- CLI tool (`remind` command)
- SQLite persistence layer
- Background consolidation
- Project-aware database paths

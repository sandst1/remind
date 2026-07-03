# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

## [0.11.3] - 2026-07-03

### Fixed

- **Web UI Topics crash** — Fixed `Object of type Topic is not JSON serializable` error on the dashboard and Topics view.
- **`snapshot query:` crash** — Fixed `AttributeError: 'SQLAlchemyMemoryStore' object has no attribute 'vector_search_concepts'` when using semantic search scope.

## [0.11.2] - 2026-07-03

### Fixed

- **`recall --topic` crash** — Fixed `AttributeError: 'SQLAlchemyMemoryStore' object has no attribute 'get_topic_by_name'` when looking up topics by display name.

## [0.11.1] - 2026-07-03

### Fixed

- **`remind apply` crash** — Fixed `AttributeError: 'MemoryInterface' object has no attribute 'config'` that blocked all batch changesets.
- **CLI hangs in non-interactive mode** — Commands with confirmation prompts (`delete-episode`, `purge-episode`, `delete-concept`, `purge-concept`, `empty-trash`, `re-embed`) now detect non-TTY stdin and exit with a clear error message instead of hanging indefinitely. Use `-y`/`--yes` for automation.

## [0.11.0] - 2026-07-03

### BREAKING CHANGES

This release fundamentally changes how Remind works. **All internal LLM usage has been removed.** The calling agent is now the only intelligence — Remind is a deterministic memory substrate that you curate explicitly.

**Migration required:**
- Remove any `consolidate`, `ingest`, `flush-ingest`, `end-session` commands from scripts
- Remove `--llm` flags from CLI invocations
- Update any code that called `memory.consolidate()`, `memory.ingest()`, etc.
- Run `remind re-embed --all` if switching from OpenAI to local embeddings (dimensions change from 1536 to 384)
- Rewrite any custom automation using the old MCP tools

### Added

- **Local embedding provider (default)** — `LocalEmbedding` using fastembed (ONNX-based, no torch, no API key). Model `all-MiniLM-L6-v2` (384 dims), lazy-loaded. Zero-config default: no embedding provider configuration needed.
- **`remind snapshot`** — Batch read tool returning a single JSON document. Scopes are combinable: `pending` (unprocessed episodes), `conflicts` (open with fact details), `entity:<id>`, `topic:<id>`, `concept:<id>` (with supersession history), `recent:<n>`, `stats`, `query:<text>`. CLI and MCP tool.
- **`remind apply`** — Batch write tool for transactional memory curation. Operations: `remember`, `supersede`, `conflict`, `resolve`, `dismiss`, `concept`, `update`, `link`, `topic`, `set_topic`, `delete`, `restore`, `processed`. Local refs (`$name`) for referencing items within the same changeset. JSON and compact line format (canonical). All-or-nothing transaction semantics. `--dry-run` for validation. CLI and MCP tool.
- **Deterministic fact pipeline** — `remember()` with `type=fact` now creates `Fact` rows synchronously using Jaccard similarity for cluster assignment (no LLM). Collisions are detected and returned in `RememberResult` for agent disposition (commit-then-report pattern).
- **Transaction support** — `store.transaction()` context manager for atomic multi-operation changesets.
- **Episode provenance** — Episodes now carry optional `asserted_by` (who asserted the information) and `source_ref` (permalink to the original artifact). Threaded through `remember()`, CLI (`--asserted-by`, `--source-ref`), and MCP tools. Provenance is shown in recall output, the REST API, and the web episode timeline.
- **First-class temporal facts** — New `Fact` model and `facts` table. Each fact is a row with a validity window (`valid_from`/`valid_to`), structural supersession (`superseded_by`), provenance (`asserted_by`, `source_ref`, `source_episode_id`), and entity references. Existing fact_cluster `specifics` strings are backfilled into fact rows once per database. Stats now include `facts` and `active_facts` counts.
- **Time-travel recall (`as_of`)** — `recall(as_of=...)` (datetime or ISO string), CLI `remind recall --as-of 2026-01-15 "query"`, and MCP `recall(as_of=...)` show the facts that were valid at that point in time for fact_cluster concepts.
- **Conflict lifecycle** — New `Conflict` model and `conflicts` table with status lifecycle (`open` → `resolved`/`dismissed`), severity, resolution metadata. Stats include `open_conflicts`.
- **Conflict resolution workflow** — `resolve_conflict(id, winning_fact_id, note, resolved_by)`: the losing fact is structurally superseded. `dismiss_conflict(id, note)`: both facts stay active. Exposed as REST routes, MCP tools, and CLI (`remind conflicts`).
- **Conflicts inbox in web UI** — new "Conflicts" view with an open-count badge in the sidebar.
- **Rewritten agent skills** — `remind-capture`, `remind-context`, `remind-curate` updated for the snapshot/apply workflow. `remind-curate` now documents the consolidation procedure (what the LLM consolidator used to do) as agent instructions.

### Changed

- **`embedding_provider` default is now `"local"`** — No API key required. OpenAI embedding is available via `pip install "remind-mcp[openai]"`.
- **`remember()` returns `RememberResult`** — Contains `episode_id`, and for facts: `fact_id`, `cluster_id`, `cluster_created`, and `collisions` (list of potentially conflicting facts).
- **`create_memory()` no longer accepts `llm_provider`** — Only embedding providers are supported.
- **Dashboard card renamed** — "Consolidation Status" → "Pending Review" (shows unprocessed episodes awaiting agent curation).
- **Fact-cluster recall shows fact rows** — recall output for fact clusters now renders active fact rows with provenance and validity instead of the raw `specifics` cache.

### Removed

- **All LLM providers and internal LLM usage** — `AnthropicLLM`, `OpenAILLM`, `AzureOpenAILLM`, `OllamaLLM` removed. The `LLMProvider` ABC is gone.
- **Consolidation** — `memory.consolidate()`, CLI `remind consolidate`, `remind reconsolidate`, MCP `consolidate` tool. Consolidation logic is now documented in the `remind-curate` skill for agents to implement.
- **Ingestion** — `memory.ingest()`, `memory.flush_ingest()`, CLI `remind ingest`, `remind flush-ingest`, `remind end-session`, MCP `ingest`/`flush_ingest` tools. The triage LLM is gone; capture directly with `remember` or `apply`.
- **Transcript capture** — `remind ingest-transcript`, `remind hook-install`, the `transcript.py` module.
- **Entity extraction** — `extraction.py` module removed. Entities must be specified explicitly on `remember()`.
- **Chat endpoint** — `POST /api/v1/chat` REST route and `stream_chat()` removed. The web UI no longer has a chat feature.
- **Config options** — `llm_provider`, `consolidation_threshold`, `concepts_per_pass`, `auto_consolidate`, `extraction_batch_size`, `extraction_llm_batch_size`, `consolidation_batch_size`, `llm_concurrency`, `ingest_buffer_size`, `AnthropicConfig`.
- **Evals** — The `evals/` directory is deleted (recoverable from git history).
- **Background workers** — Consolidation and ingest workers removed. Only the recall worker (for reranking warmup) remains.

### Documentation

- AGENTS.md updated to reflect agent-driven architecture
- Skills rewritten for snapshot/apply workflow
- Website documentation updated

## [0.10.5] - 2026-05-05

### Added

- **Dual-track concepts** — Concepts are now classified as either `pattern` (generalizations from observations and decisions) or `fact_cluster` (verbatim fact details that are never abstracted away). Fact clusters include a `summary` generated from their constituent facts.
- **Entity embeddings** — Entities are now embedded alongside episodes for richer retrieval.

### Changed

- **Consolidation prompts** — Improved concept and fact-tracking prompts for better specificity and throughput; fact clustering logic tuned for higher precision.

### Removed

- **Plan / spec / task episode types and CLI** — The `spec`, `plan`, and `task` episode types, related CLI commands (`specs`, `plans`, `tasks`, `task …`), and MCP tools have been removed. Remind is a memory layer, not a task planner. Use standard episode types (`observation`, `decision`, `question`, `fact`, etc.) with entities and metadata to track work. Existing databases with these episode types continue to work; the types are just no longer surfaced by the CLI or MCP.
- **Bundled plan/spec/implement skills** — `remind-plan`, `remind-spec`, and `remind-implement` skills removed from the package. `skill-install` now installs only the base `remind` skill.

### Fixed

- **Entity processing bug** — Fixed a bug where entity extraction could produce incorrect associations during consolidation.
- **UI fixes** — Various web UI reliability improvements.

### Documentation

- README, MCP reference, CLI reference, and concept pages updated to reflect removed types and current CLI (topics subgroup, `types` command, corrected `ingest` topic behavior, expanded MCP tool list).

## [0.10.4] - 2026-04-09

### Added
- CLI `cli_output_mode` / `cliOutputMode` config and `REMIND_CLI_OUTPUT_MODE` env: default `table`, or `json` / `compact-json` for machine-readable output on browse commands; `--json`, `--compact-json`, and `--table` override per invocation (at most one).
- JSON output (`--json` or `cli_output_mode=json`) for `inspect`, `specs`, `plans`, `tasks`, `topics list`/`overview`, `entities`, `search`, `mentions`, `decisions`, `questions`, `types`, `status`, `entity-relations`, `deleted`.
- **`--compact-json`** (and `cli_output_mode=compact-json`): third stdout mode with minimal `id` / `title` / `summary` payloads (plus documented per-command fields such as task `plan_id`/`plan`, search `score`, entities `mention_count`, status metadata wrapper).
- `remind tasks`: shows linked plan in a Plan column; `--by-plan` groups by plan then status; JSON includes enriched `plan` on tasks and a `by_plan` grouping shape when `--by-plan` is set.

### Documentation
- Fixed documentation website links and expanded the SQLite examples page.

## [0.10.3] - 2026-04-08

### Added
- Topic reassignment for existing episodes and concepts: `update_episode` / `update_concept` accept `--topic` and `--clear-topic` on the CLI; REST `PATCH`/`PUT` bodies may include `topic`; MCP tools accept optional `topic` (empty string clears).

## [0.10.2] - 2026-04-08

### Fixed
- Crash on startup when the `sqlite-vec` package was installed but Python's `sqlite3` was built without extension loading (common on macOS / some pyenv builds). Remind now detects this and falls back to brute-force vector similarity instead of calling `enable_load_extension`.

### Documentation
- Documented SQLite vector search (sqlite-vec) requirements, how to verify extension support, and typical pyenv + Homebrew steps to enable native SQLite vector indexes.

## [0.10.1] - 2026-04-08

### Added
- Added a new `re-embed` command to regenerate stored embeddings after changing embedding model or dimensions.

## [0.10.0] - 2026-04-08

### Added
- Native vector search indexes for retrieval: `sqlite-vec` (SQLite) and `pgvector` (PostgreSQL), with automatic fallback to brute-force cosine search
- Optional cross-encoder reranking for recall (`sentence-transformers`), plus configurable `recall_initial_candidates`
- Hybrid retrieval scoring that fuses embeddings with keyword overlap (`hybrid_keyword_weight`)
- Topics as first-class memory partitions across episodes and concepts, with topic-aware consolidation and retrieval
- Topic tools and APIs (`list_topics`, `topic_overview`) plus ingest-time topic inference when no topic is supplied
- Optional ingest `instructions` to steer triage extraction
- Configurable `episode_types`, with conditional registration of plan/spec/task CLI and MCP surfaces
- Project-local Remind config (e.g. `.remind/remind.config.json`) and project-specific `oo` token-saving patterns
- PostgreSQL and MySQL support via SQLAlchemy (`REMIND_DB_URL` / `db_url`)
- Parallel consolidation across batches, and episode type breakdowns in stats
- `source_type` metadata on episodes and `supersedes` concept relation in recall output

### Changed
- Auto-ingest no longer uses configurable density-threshold gating; chunking and text processing improved
- Consolidation and extraction prompts tuned for specificity and throughput, including higher token limits and better concurrency defaults
- Retrieval performance improved, including reranker warm-up behavior for CLI workflows
- Web UI improved for custom episode types, topics, task flows, and non-SQLite database URL/path handling

### Fixed
- Reconsolidation reliability
- MCP episode argument parsing
- Task creation from the web UI
- Web UI and stats when using PostgreSQL or other SQLAlchemy database URLs
- Embedding dimension handling and reranker NaN-score error handling

## [0.8.0] - 2026-03-23

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

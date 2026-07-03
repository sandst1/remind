# Changelog

All notable changes to Remind.

## [0.11.3] - 2026-07-03

### Fixed

- **Web UI Topics crash** — Fixed `Object of type Topic is not JSON serializable` error on the dashboard.
- **`snapshot query:` crash** — Fixed `AttributeError` when using semantic search scope.

## [0.11.2] - 2026-07-03

### Fixed

- **`recall --topic` crash** — Fixed `AttributeError` when looking up topics by display name.

## [0.11.1] - 2026-07-03

### Fixed

- **`remind apply` crash** — Fixed `AttributeError` that blocked all batch changesets.
- **CLI hangs in non-interactive mode** — Commands with confirmation prompts now detect non-TTY stdin and exit with a clear error. Use `-y`/`--yes` for automation.

## [0.11.0] - 2026-07-03

### BREAKING CHANGES

This release fundamentally changes how Remind works. **All internal LLM usage has been removed.** The calling agent is now the only intelligence — Remind is a deterministic memory substrate that you curate explicitly.

**Migration required:**
- Remove any `consolidate`, `ingest`, `flush-ingest`, `end-session` commands from scripts
- Remove `--llm` flags from CLI invocations
- Update any code that called `memory.consolidate()`, `memory.ingest()`, etc.
- Run `remind re-embed --all` if switching from OpenAI to local embeddings (dimensions change from 1536 to 384)

### Added

- **Local embedding provider (default)** — `LocalEmbedding` using fastembed (ONNX-based, no API key). Zero-config default.
- **`remind snapshot`** — Batch read tool returning a single JSON document. Scopes: `pending`, `conflicts`, `entity:<id>`, `topic:<id>`, `concept:<id>`, `recent:<n>`, `stats`, `query:<text>`.
- **`remind apply`** — Batch write tool for transactional memory curation. Operations: `remember`, `supersede`, `conflict`, `resolve`, `dismiss`, `concept`, `update`, `link`, `topic`, `set_topic`, `delete`, `restore`, `processed`. Local refs, JSON and compact line format.
- **Deterministic fact pipeline** — `remember()` with `type=fact` creates `Fact` rows using Jaccard similarity for cluster assignment. Collisions returned in `RememberResult` for agent disposition.
- **Transaction support** — `store.transaction()` context manager for atomic operations.
- **Episode provenance** — `asserted_by` and `source_ref` on episodes. Shown in recall output and web UI.
- **First-class temporal facts** — `Fact` model with validity windows, supersession, provenance.
- **Time-travel recall (`as_of`)** — Show facts valid at a past point in time.
- **Conflict lifecycle** — `Conflict` model with `open` → `resolved`/`dismissed` lifecycle.
- **Conflicts inbox in web UI** — New view with open-count badge.
- **Rewritten agent skills** — `remind-capture`, `remind-context`, `remind-curate` for snapshot/apply workflow.

### Changed

- **`embedding_provider` default is now `"local"`** — No API key required.
- **`remember()` returns `RememberResult`** — Contains `episode_id`, and for facts: collision info.
- **`create_memory()` no longer accepts `llm_provider`** — Only embedding providers supported.
- **Dashboard card renamed** — "Consolidation Status" → "Pending Review".

### Removed

- **All LLM providers** — `AnthropicLLM`, `OpenAILLM`, `AzureOpenAILLM`, `OllamaLLM` removed.
- **Consolidation** — `memory.consolidate()`, CLI `remind consolidate`, MCP `consolidate` tool.
- **Ingestion** — `memory.ingest()`, `memory.flush_ingest()`, CLI commands, MCP tools.
- **Transcript capture** — `remind ingest-transcript`, `remind hook-install`.
- **Entity extraction** — `extraction.py` removed. Entities must be specified explicitly.
- **Chat endpoint** — `POST /api/v1/chat` removed.
- **Background workers** — Consolidation and ingest workers removed.

## [0.10.5] - 2026-05-05

### Added

- **Dual-track concepts** — `pattern` (generalizations) or `fact_cluster` (verbatim facts).
- **Entity embeddings** — Entities embedded alongside episodes for richer retrieval.

### Changed

- **Consolidation prompts** — Improved specificity and throughput.

### Removed

- **Plan / spec / task episode types and CLI** — Removed. Use standard episode types.
- **Bundled plan/spec/implement skills** — Removed.

### Fixed

- **Entity processing bug** — Fixed incorrect associations during consolidation.
- **UI fixes** — Various reliability improvements.

## [0.10.4] - 2026-04-09

### Added
- **`cli_output_mode`** — `table`, `json`, or `compact-json` output modes.
- **JSON output** — For browse commands.
- **`--compact-json`** — Minimal payloads.

## [0.10.3] - 2026-04-08

### Added
- **Topic reassignment** — Move episodes/concepts between topics.

## [0.10.2] - 2026-04-08

### Fixed
- **SQLite startup crash** — Fallback when sqlite-vec can't load.

## [0.10.1] - 2026-04-08

### Added
- **`re-embed` command** — Regenerate embeddings after model change.

## [0.10.0] - 2026-04-08

### Added
- **Native vector indexes** — sqlite-vec and pgvector support.
- **Cross-encoder reranking** — Optional reranking for recall.
- **Hybrid retrieval** — Embedding + keyword scoring.
- **Topics** — First-class memory partitions.
- **PostgreSQL/MySQL support** — Via SQLAlchemy.

### Changed
- Improved consolidation, retrieval, and web UI.

## [0.8.0] - 2026-03-23

### Added
- **Episode embeddings** — Direct vector search during recall.
- **Contradiction display** — Shows `contradicts` relations.

## [0.7.0] - 2026-03-19

### Added
- **Auto-ingest** — LLM-powered triage pipeline.
- **Fact/outcome episodes** — New episode types.
- **Hybrid recall** — Entity name matching.

## [0.6.0] - 2026-03-09

### Added
- **Task management** — Task episodes with status tracking.
- **Agent workflow skills** — Plan/spec/implement lifecycle.

## [0.5.0] - 2026-03-02

### Added
- Support for updating and deleting concepts/episodes.

## [0.4.0] - 2026-02-26

### Added
- **Memory decay** — Concepts lose priority based on recall frequency.

## [0.3.0] - 2026-02-25

### Added
- Global config file support.
- Agent skills for Claude Code.

## [0.2.0] - 2026-01-09

### Added
- Web UI with concept graph visualization.
- Docker support.

## [0.1.0] - 2026-01-04

### Added
- Core memory system.
- Spreading activation retrieval.
- LLM-powered consolidation.
- MCP server and CLI.

# Remind - Development Guide for AI Agents

This guide is for AI agents developing **Remind itself**. For using Remind as a memory layer, see [docs/AGENTS.md](./docs/AGENTS.md).

## Project Overview

Remind is an agent-driven memory layer for LLMs. It provides temporal facts, semantic retrieval, and structured curation — the calling agent is the only intelligence. There are no internal LLM calls.

**Core architecture**: Episodes → Agent curation via `apply` → Concepts with relations

## Architecture

```
src/remind/
├── models.py          # Data models (Concept, Episode, Entity, Relation, Fact, Conflict)
├── store.py           # SQL persistence and disposable query projection
├── file_store.py      # Default JSON store, write journal, recovery, migration
├── serialization.py   # Complete portable snapshots and backups
├── operations.py      # Revision checks and idempotency
├── evals.py           # Operational, semantic, and external-agent evaluations
├── interface.py       # MemoryInterface - main public API
├── config.py          # Configuration loading (config file, env vars, defaults)
├── facts.py           # Deterministic fact processing (clustering, collision detection)
├── apply.py           # Batch write engine (op vocabulary, transaction support)
├── snapshot.py        # Batch read engine (combinable scopes)
├── retrieval.py       # Spreading activation retrieval
├── reranker.py        # Optional cross-encoder reranking (requires [rerank] extra)
├── cli.py             # Command-line interface (project-aware)
├── mcp_server.py      # MCP (Model Context Protocol) server
├── background.py      # Background recall worker spawning
├── background_worker.py # Subprocess entry point for recall worker
├── api/               # REST API for web UI
│   ├── __init__.py    # Exports api_routes
│   └── routes.py      # Starlette route handlers
├── static/            # Web UI assets (compiled)
│   ├── index.html     # Entry point
│   └── assets/        # CSS/JS bundles
├── skills/            # Bundled agent skills (installed via `remind skill-install`)
│   ├── remind-capture/  # When/how to write memories while working
│   ├── remind-context/  # When/how to recall before acting
│   └── remind-curate/   # Consolidation procedure, conflict triage, label upkeep
└── providers/         # Embedding provider implementations
    ├── base.py        # EmbeddingProvider ABC
    ├── local.py       # Local embeddings via fastembed (default)
    ├── openai.py      # OpenAI embeddings
    ├── azure_openai.py # Azure OpenAI embeddings
    └── ollama.py      # Ollama embeddings
```

## Key Abstractions

### Data Models (`models.py`)

| Model | Purpose |
|-------|---------|
| `Episode` | Raw experience/interaction. Marked `consolidated=True` when processed. |
| `Concept` | Generalized knowledge with confidence, relations, conditions. Has `concept_type`: `pattern`, `fact_cluster`, or `legacy`. |
| `Entity` | External referent (file, person, concept, tool). Format: `type:name` |
| `Relation` | Typed edge between concepts (implies, contradicts, specializes, etc.) |
| `Fact` | First-class factual assertion with validity window (`valid_from`/`valid_to`), structural supersession (`superseded_by`), and provenance. Belongs to a fact_cluster concept via `cluster_id`. |
| `Conflict` | Detected contradiction with lifecycle: `open` → `resolved`/`dismissed`. `kind` is `fact` (two fact rows) or `concept` (two concepts). |

**Episode types**: `observation`, `decision`, `question`, `meta`, `preference`, `outcome`, `fact`

**Episode lifecycle**: Created via `remember()` → For facts: deterministic clustering + collision detection → Marked processed via `apply` with `processed` op

**Episode provenance**: Optional `asserted_by` (who asserted the information) and `source_ref` (permalink to the original artifact).

**Entity ID format**: `type:name` (e.g., `file:src/auth.ts`, `person:alice`, `concept:caching`)

**Labels**: Freeform `key -> value(s)` tags on `Episode`/`Concept` (e.g. `{"topic": ["architecture"]}`), backed by a `labels` table designed to be pushed down as a pre-filter into vector search (`recall(labels=...)`), not just applied as a post-filter. Replaced the old hardcoded `Topic` model in 0.13.0 — build any higher-level grouping convention (topics, projects, teams) on top of this primitive rather than in the substrate.

### Providers (`providers/base.py`)

One abstract base class (LLM providers have been removed):

```python
class EmbeddingProvider(ABC):
    async def embed(text) -> list[float]
    async def embed_batch(texts) -> list[list[float]]
    @property dimensions: int
    @property name: str
```

**Default provider**: `LocalEmbedding` using fastembed (`all-MiniLM-L6-v2`, 384 dimensions). No API key required.

### Memory Interface (`interface.py`)

The main entry point. Key design decisions:

1. **`remember()` returns `RememberResult`** - episode_id + fact info for fact types
2. **`recall()` returns `RecallResult` and uses spreading activation** - with hybrid embedding+keyword scoring
3. **No internal LLM calls** - the calling agent provides all judgment

```python
@dataclass
class RememberResult:
    episode_id: str
    fact_id: Optional[str] = None
    cluster_id: Optional[str] = None
    cluster_created: bool = False
    collisions: list[Fact] = field(default_factory=list)
```

### Fact Processing (`facts.py`)

Deterministic fact handling (no LLM):

1. `create_fact_from_episode()` - Main entry point for fact-type episodes
2. `find_matching_cluster()` - Jaccard similarity on entity sets
3. `create_fact_cluster()` - Creates cluster with templated title
4. `detect_collisions()` - Entity overlap + embedding similarity

Collisions are reported to the agent via `RememberResult.collisions` for disposition.

### Apply Engine (`apply.py`)

Batch write operations with transaction support:

**Op vocabulary**: `remember`, `supersede`, `conflict`, `resolve`, `dismiss`, `concept`, `update`, `link`, `label`, `unlabel`, `delete`, `restore`, `processed`

**Two formats** (auto-detected):
- Compact line format (canonical, lower token usage)
- JSON array

**Transaction**: All ops run in a single database transaction via `store.transaction()`.

### Snapshot Engine (`snapshot.py`)

Batch read returning JSON:

**Scopes**: `pending`, `conflicts`, `entity:<id>`, `labels`, `label:<key>=<value>`, `concept:<id>`, `recent:<n>`, `stats`, `query:<text>`, `events[:<since_seq>]`, `bootstrap[:<n>]`

`bootstrap[:<n>]` is the query-free counterpart to `query:<text>`: no embedding call, deterministic across turns for the same memory state (top-n actionable concepts ranked by `(confidence, instance_count)` desc, plus open conflict count and stats) — suitable for a system-prompt injection layer that wants to keep the KV cache warm.

### Change Feed (`events` table)

Append-only outbox so consolidation daemons and sync layers can poll incrementally instead of re-scanning `snapshot pending`. Every successful `apply` op and every `remember`/`remember_batch` call appends a row via `store.emit_event(kind, subject_type, subject_id, payload=None)`, written inside the same `store.transaction()` as the change it describes so it commits atomically. `kind` is one of `remembered`, `superseded`, `conflict_opened`, `conflict_resolved`, `conflict_dismissed`, `concept_created`, `updated`, `labeled`, `unlabeled`, `deleted`, `restored`, `processed`. Read with `store.get_events(since_seq=0, limit=100, kind=None)`, `snapshot(["events:<since_seq>"])`, or `remind events --since <seq>`; each read returns a `next_since_seq` cursor to pass on the next poll.

### Retrieval (`retrieval.py`)

**Hybrid recall** with spreading activation + entity-based episode retrieval:
1. Query is embedded and matched to concepts via cosine similarity
2. A parallel lexical (FTS5/tsvector/FULLTEXT) search ranks the same concepts/episodes by keyword match
3. The two rankings are fused via weighted Reciprocal Rank Fusion (`hybrid_keyword_weight` = lexical arm weight, `rrf_k` = rank-damping constant)
4. Matched concepts activate related concepts through the graph
5. Activation spreads with decay over multiple hops
5. Optional cross-encoder reranking

**Time-travel recall**: `recall(as_of=...)` renders fact_cluster concepts with historical facts.

### Store (`store.py`)

Multi-database persistence via SQLAlchemy Core. Supports SQLite, PostgreSQL, MySQL.

**Transaction support**: `store.transaction()` context manager for atomic operations.

**Vector search backends**:
- **sqlite-vec** (SQLite): `vec0` virtual tables with cosine distance KNN
- **pgvector** (PostgreSQL): `vector(N)` columns with HNSW indexes
- **Fallback**: Python-side numpy cosine similarity

### Configuration (`config.py`)

```python
@dataclass
class RemindConfig:
    embedding_provider: str = "local"
    db_url: Optional[str] = None
    hybrid_keyword_weight: float = 0.3
    lexical_enabled: bool = True
    rrf_k: int = 60
    recall_initial_candidates: int = 10
    recall_max_chars: Optional[int] = None
    recall_min_score: Optional[float] = None
    recall_timeout_ms: Optional[int] = None
    reranking_enabled: bool = False
    fact_cluster_jaccard_threshold: float = 0.5
    logging_enabled: bool = False
    episode_types: list[str] = ...
    local: LocalConfig  # Local embedding config
    openai: OpenAIConfig  # OpenAI embedding config
    # etc.
```

## Code Conventions

### Async/Await
- All embedding operations are async
- `remember()` and `remember_batch()` are async; embeddings happen before the write transaction
- Use `asyncio.run()` in CLI, native async in MCP server

### Type Hints
- Full type hints on all public APIs
- Use `Optional[T]` explicitly
- Dataclasses with `field(default_factory=...)` for mutable defaults

### JSON Serialization
- All models have `to_dict()` and `from_dict()` class methods
- Enums serialize to their string value
- Datetimes serialize to ISO format

## Testing

Tests are in `tests/` using pytest:

```bash
pytest                        # All tests
pytest tests/test_store.py    # Specific file
pytest -v                     # Verbose
```

Tests use temporary databases and mock embedding providers.

## Common Development Tasks

### Adding a New Provider

1. Create `providers/newprovider.py`
2. Implement `EmbeddingProvider`
3. Add to `providers/__init__.py` exports
4. Add to `interface.py` factory map in `create_memory()`
5. Update config in `config.py`
6. Document in README.md

### Adding a New Episode Type

1. Add to `EpisodeType` enum in `models.py`
2. Update skills documentation

### Adding a New Apply Operation

1. Add validation in `ApplyEngine._validate_ops()`
2. Add execution in `ApplyEngine._execute_op()`
3. Create `_op_<name>()` method
4. Update skills documentation

### Adding a New Snapshot Scope

1. Add scope handler in `SnapshotEngine.snapshot()`
2. Create `_scope_<name>()` method
3. Update CLI help and MCP tool description

## Important Files for Context

| Change Type | Files |
|-------------|-------|
| New data structure | `models.py`, `store.py` |
| New provider | `providers/newprovider.py`, `providers/__init__.py`, `interface.py` |
| Fact processing | `facts.py`, `interface.py` |
| Apply operations | `apply.py`, `cli.py`, `mcp_server.py` |
| Snapshot scopes | `snapshot.py`, `cli.py`, `mcp_server.py` |
| Retrieval behavior | `retrieval.py`, `reranker.py` |
| CLI commands | `cli.py` |
| Configuration | `config.py`, `interface.py`, `mcp_server.py`, `cli.py` |
| MCP tools | `mcp_server.py` |
| REST API endpoints | `api/routes.py` |
| Public API | `interface.py`, `__init__.py`, `README.md` |

## Debugging Tips

- **Fact clustering issues**: Check Jaccard threshold, entity overlap
- **Collision detection**: Verify entity IDs match, check embedding similarity
- **Retrieval misses**: Verify concepts have embeddings, check vector index status
- **MCP issues**: Check `db` query parameter, verify server is running
- **Config issues**: Check `~/.remind/remind.config.json` is valid JSON
- **CLI database path**: Without `--db`, uses `<cwd>/.remind/remind.db` (project-aware)

## Database Schema

```sql
CREATE TABLE concepts (
    id TEXT PRIMARY KEY,
    data JSON NOT NULL
);

CREATE TABLE episodes (
    id TEXT PRIMARY KEY,
    data JSON NOT NULL
);

CREATE TABLE entities (
    id TEXT PRIMARY KEY,
    data JSON NOT NULL
);

CREATE TABLE mentions (
    episode_id TEXT,
    entity_id TEXT,
    PRIMARY KEY (episode_id, entity_id)
);

CREATE TABLE labels (
    subject_type TEXT NOT NULL,   -- episode | concept | fact
    subject_id TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    PRIMARY KEY (subject_type, subject_id, key, value)
);

CREATE TABLE facts (
    id TEXT PRIMARY KEY,
    cluster_id TEXT,
    statement TEXT,
    valid_from DATETIME,
    valid_to DATETIME,
    superseded_by TEXT,
    -- ... other columns
);

CREATE TABLE conflicts (
    id TEXT PRIMARY KEY,
    kind TEXT,
    status TEXT,
    fact_a_id TEXT,
    fact_b_id TEXT,
    -- ... other columns
);
```

The store handles JSON serialization/deserialization transparently.

## Durable storage and evaluation development

Default stores use canonical model JSON records under `.remind/memory/`; SQL is a rebuildable query projection. Preserve the journal commit/recovery protocol and never introduce internal LLM calls. New opaque IDs are full UUIDs; old IDs remain valid. All deliberate edits require caller revisions. Capture, apply, events, and retry receipts commit together. Ordinary recall must not mutate knowledge or usage statistics.

Use the fixture dataset in `src/remind/eval_data/dataset.json` for operational, retrieval, and external-agent evals. Run `python -m remind.evals --suite operational`; real MCP/REST transports need loopback ports. Semantic evals use the actual default model. Agent evals require an external command and must report not-run when absent. See `evals/README.md`. Run pytest locally; do not add CI as part of this work.

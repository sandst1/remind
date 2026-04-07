# Remind - Development Guide for AI Agents

This guide is for AI agents developing **Remind itself**. For using Remind as a memory layer, see [docs/AGENTS.md](./docs/AGENTS.md).

## Project Overview

Remind is a generalization-capable memory layer for LLMs. It differs from simple RAG by extracting and maintaining **generalized concepts** from episodic experiences, mimicking how human memory consolidates specific events into abstract knowledge.

**Core insight**: Episodes → Consolidation (LLM-powered "sleep") → Concepts with relations

## Architecture

```
src/remind/
├── models.py          # Data models (Concept, Episode, Entity, Relation, Topic)
├── store.py           # SQLite persistence layer
├── interface.py       # MemoryInterface - main public API
├── config.py          # Configuration loading (config file, env vars, defaults)
├── consolidation.py   # LLM-powered episode → concept transformation
├── extraction.py      # Entity/type extraction from episodes
├── retrieval.py       # Spreading activation retrieval
├── reranker.py        # Optional cross-encoder reranking (requires [rerank] extra)
├── triage.py          # Auto-ingest: buffered intake + density scoring + topic inference
├── cli.py             # Command-line interface (project-aware)
├── mcp_server.py      # MCP (Model Context Protocol) server
├── background.py      # Background consolidation spawning
├── background_worker.py # Subprocess entry point for background consolidation
├── api/               # REST API for web UI
│   ├── __init__.py    # Exports api_routes
│   └── routes.py      # Starlette route handlers
├── static/            # Web UI assets (compiled)
│   ├── index.html     # Entry point
│   └── assets/        # CSS/JS bundles
└── providers/         # LLM and embedding provider implementations
    ├── base.py        # Abstract base classes
    ├── anthropic.py   # Claude
    ├── openai.py      # OpenAI
    ├── azure_openai.py # Azure OpenAI
    └── ollama.py      # Local models via Ollama
```

## Key Abstractions

### Data Models (`models.py`)

| Model | Purpose |
|-------|---------|
| `Episode` | Raw experience/interaction. Temporary, gets consolidated. |
| `Concept` | Generalized knowledge with confidence, relations, conditions. |
| `Entity` | External referent (file, person, concept, tool). Format: `type:name` |
| `Relation` | Typed edge between concepts (implies, contradicts, specializes, etc.) |
| `Topic` | Named knowledge area grouping episodes/concepts. Has id (slug), name, description. |
| `TaskStatus` | Enum for task status: `todo`, `in_progress`, `done`, `blocked` |

**Episode types**: `observation`, `decision`, `question`, `meta`, `preference`, `spec`, `plan`, `task`, `outcome`, `fact`

**Episode lifecycle**: Created via `remember()` or `ingest()` → Entity extraction → Consolidation → Marked consolidated

**Fact episodes**: Specific factual assertions (config values, names, dates, concrete technical details). Consolidation preserves fact details verbatim in concept summaries rather than generalizing them away.

**Outcome episode metadata**: `strategy` (approach used), `result` (success/failure/partial), `prediction_error` (low/medium/high)

**Task lifecycle**: `todo` → `in_progress` → `done` (or `blocked` → `todo`). Active tasks are excluded from consolidation; only completed tasks consolidate.

**Entity ID format**: `type:name` (e.g., `file:src/auth.ts`, `person:alice`, `concept:caching`)

### Providers (`providers/base.py`)

Two abstract base classes:

```python
class LLMProvider(ABC):
    async def complete(prompt, system, temperature, max_tokens) -> str
    async def complete_json(prompt, system, temperature, max_tokens) -> dict
    @property name: str

class EmbeddingProvider(ABC):
    async def embed(text) -> list[float]
    async def embed_batch(texts) -> list[list[float]]
    @property dimensions: int
    @property name: str
```

**Adding a new provider**: Implement these interfaces. See `ollama.py` for a complete example with error handling.

### Memory Interface (`interface.py`)

The main entry point. Key design decisions:

1. **`remember()` is synchronous and fast** - no LLM calls, just stores episode
2. **`ingest()` is async with LLM triage** - buffers, extracts episodes with topic inference, immediately consolidates
3. **`consolidate()` does all LLM work** - extraction + generalization
4. **Two consolidation modes**: Automatic (threshold-based) or manual (hook-based)

```python
# Consolidation happens in two phases:
# 1. Extract entities/types from unextracted episodes
# 2. Generalize episodes into concepts (the "sleep" process)
```

### Consolidation (`consolidation.py`)

The "brain" of the system. Uses LLM to:
- Classify episode types (observation, decision, question, meta, preference, outcome)
- Extract entity mentions from natural language
- Identify patterns across episodes
- Create generalized concepts with relations
- Detect contradictions
- Identify causal patterns in outcome episodes (strategy-outcome relations)

### Auto-Ingest Triage (`triage.py`)

The "input selection" subsystem. Two classes:
- `IngestionBuffer` — character-threshold accumulator. Buffers raw text until threshold (~4000 chars).
- `IngestionTriager` — LLM-based episode extraction with topic inference. The LLM decides directly what's worth remembering, extracts distilled episodes, detects action-result pairs as outcome episodes, and assigns each episode to a topic. A density score (0.0-1.0) is produced for diagnostics but doesn't gate extraction.

**Topic handling**: When `ingest()` is called with an explicit `topic`, all episodes are stamped with that topic (no LLM inference). When `topic` is omitted, the triage LLM receives existing topics as context and assigns each episode to an existing topic or suggests a new one (auto-created). Sub-chunks are triaged concurrently, bounded by `llm_concurrency`.

**Instructions**: The `instructions` parameter (optional) lets callers steer what the triage LLM extracts. When provided, instructions are appended to the triage system prompt as a prioritized directive. This enables focused ingestion (e.g. "extract only architectural decisions", "capture all config values"). Threaded through the full pipeline: `ingest()`/`flush_ingest()` → `_process_ingest_chunk()` → `_triage_sub_chunk()` → `IngestionTriager.triage()`. Also serialized in the background queue JSON payload for CLI background workers.

Pipeline: `ingest()` → buffer → triage + extract + topic inference (LLM) → `remember()` → `consolidate(force=True)`

### Retrieval (`retrieval.py`)

**Hybrid recall** with spreading activation + entity-based episode retrieval:
1. Query is embedded and matched to concepts via cosine similarity (native vector index when available)
2. Embedding scores are optionally fused with keyword overlap scores (`hybrid_keyword_weight` config, default 0.3)
3. Matched concepts activate related concepts through the graph
4. Activation spreads with decay over multiple hops
5. Optional cross-encoder reranking blends activation scores with query-document relevance (`reranking_enabled` config, requires `[rerank]` extra)
6. Highest-activation concepts are returned with source episodes (including type labels and entity context)

Key class: `MemoryRetriever` with `ActivatedConcept` results.

Helper function: `_keyword_score(query, text)` — normalized token overlap for hybrid scoring.

**Reranking** (`reranker.py`): Optional cross-encoder post-processing. When `reranking_enabled=True`, a `Reranker` wrapping sentence-transformers `CrossEncoder` rescores candidates after spreading activation. Blending: `0.4 × activation + 0.6 × rerank_score`. Model is lazy-loaded on first recall. Requires `pip install "remind-mcp[rerank]"`.

### Store (`store.py`)

Multi-database persistence via SQLAlchemy Core. Supports SQLite (default), PostgreSQL, and MySQL. Tables:
- `concepts` - Stores concepts with JSON-serialized relations
- `episodes` - Raw episodes with consolidation status
- `entities` - Entity registry
- `mentions` - Episode-entity junction table
- `relations` - Concept-to-concept graph edges
- `entity_relations` - Entity-to-entity relationships
- `metadata` - Persistent key-value store

**Vector search backends** (auto-detected at startup):
- **sqlite-vec** (SQLite): `vec0` virtual tables (`vec_concepts`, `vec_episodes`) with cosine distance KNN. Extension is loaded via `sqlite_vec.load()` on connection creation.
- **pgvector** (PostgreSQL): `vector(N)` columns (`embedding_vec`) with HNSW indexes and `<=>` cosine distance operator.
- **Brute-force fallback**: If neither extension is available, falls back to Python-side numpy cosine similarity (O(n) per query).

Embedding dimensions are recorded in the `metadata` table on first write. Vector tables/columns are created lazily when the first embedding is stored.

The `MemoryStore` ABC defines the interface. `SQLAlchemyMemoryStore` is the concrete implementation (aliased as `SQLiteMemoryStore` for backward compatibility).

### Configuration (`config.py`)

Centralized configuration management with provider-specific settings:

```python
REMIND_DIR = Path.home() / ".remind"
CONFIG_FILE = REMIND_DIR / "remind.config.json"

@dataclass
class AnthropicConfig:
    api_key: Optional[str] = None
    model: str = "claude-sonnet-4-20250514"
    ingest_model: Optional[str] = None

@dataclass
class OpenAIConfig:
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: str = "gpt-4.1"
    embedding_model: str = "text-embedding-3-small"
    ingest_model: Optional[str] = None

@dataclass
class AzureOpenAIConfig:
    api_key: Optional[str] = None
    base_url: Optional[str] = None  # e.g. https://myresource.openai.azure.com (/openai/v1 appended automatically)
    deployment_name: Optional[str] = None
    embedding_deployment_name: Optional[str] = None
    embedding_size: int = 1536
    ingest_deployment_name: Optional[str] = None

@dataclass
class OllamaConfig:
    url: str = "http://localhost:11434"
    llm_model: str = "llama3.2"
    embedding_model: str = "nomic-embed-text"
    ingest_model: Optional[str] = None

@dataclass
class RemindConfig:
 llm_provider: str = "anthropic"
 embedding_provider: str = "openai"
 consolidation_threshold: int = 5
 concepts_per_pass: int = 64
 auto_consolidate: bool = True
 extraction_batch_size: int = 50
 extraction_llm_batch_size: int = 10
 consolidation_batch_size: int = 25
 llm_concurrency: int = 3
 # Database URL (SQLAlchemy format; None = SQLite default)
 db_url: Optional[str] = None
 # Auto-ingest settings
 ingest_buffer_size: int = 4000
 # Retrieval tuning
 hybrid_keyword_weight: float = 0.3
 recall_initial_candidates: int = 10
 # Reranking (requires `pip install "remind-mcp[rerank]"`)
 reranking_enabled: bool = False
 reranking_model: str = "cross-encoder/ms-marco-MiniLM-L-2-v2"
 # Logging
 logging_enabled: bool = False
 # Episode types (controls which types are valid + gates CLI/MCP features)
 episode_types: list[str] = field(default_factory=lambda: list(DEFAULT_EPISODE_TYPES))
 # Nested provider configs
 anthropic: AnthropicConfig
 openai: OpenAIConfig
 azure_openai: AzureOpenAIConfig
 ollama: OllamaConfig

def load_config() -> RemindConfig:
    """Priority: env vars > config file > defaults"""

def resolve_db_url(db_name: Optional[str], project_aware: bool = False) -> str:
    """Resolve a database name/path/URL to a SQLAlchemy database URL.
    - Full URL (postgresql://..., mysql://...): returned as-is
    - db_name provided: sqlite:///~/.remind/{name}.db
    - db_name=None + project_aware=True: sqlite:///<cwd>/.remind/remind.db
    - db_name=None + project_aware=False: sqlite:///~/.remind/memory.db
    """

def resolve_db_path(db_name: Optional[str], project_aware: bool = False) -> str:
    """Legacy function - resolves to a file path (SQLite only)."""
```

**Database URL** (`db_url`): Supports any SQLAlchemy-compatible database URL. Env var: `REMIND_DB_URL`. Examples:
- SQLite (default): `sqlite:///~/.remind/memory.db`
- PostgreSQL: `postgresql+psycopg://user:pass@localhost:5432/remind`
- MySQL: `mysql+pymysql://user:pass@localhost:3306/remind`

**Config file format** (`~/.remind/remind.config.json`):
```json
{
 "llm_provider": "anthropic",
 "embedding_provider": "openai",
 "consolidation_threshold": 5,
 "auto_consolidate": true,
 "hybrid_keyword_weight": 0.3,
 "logging_enabled": false,
 "db_url": null,
 "anthropic": { "api_key": "sk-ant-..." },
 "openai": { "api_key": "sk-..." },
 "azure_openai": { "api_key": "...", "base_url": "..." },
 "ollama": { "url": "http://localhost:11434" }
}
```

### Background Consolidation (`background.py`, `background_worker.py`)

Non-blocking consolidation for CLI:

- `spawn_background_consolidation()` - Spawns a subprocess to consolidate
- Uses `filelock` for cross-platform file locking to prevent concurrent runs
- Lock files stored at `~/.remind/.consolidate-{hash}.lock`
- Logs to `~/.remind/logs/consolidation.log`

The CLI automatically triggers background consolidation after `remember` when the episode threshold is reached.

## Code Conventions

### Async/Await
- All LLM operations are async
- `remember()` is deliberately sync (fast path)
- Use `asyncio.run()` in CLI, native async in MCP server

### Type Hints
- Full type hints on all public APIs
- Use `Optional[T]` explicitly, not `T | None` for consistency
- Dataclasses with `field(default_factory=...)` for mutable defaults

### Error Handling
- Providers handle their own retries and rate limiting
- Store operations raise on critical errors, return None for "not found"
- Consolidation is fault-tolerant (individual episode failures don't abort)

### Logging
- Use `logging.getLogger(__name__)` pattern
- Debug for operation traces, Info for consolidation events, Warning for recoverable issues

### JSON Serialization
- All models have `to_dict()` and `from_dict()` class methods
- Enums serialize to their string value
- Datetimes serialize to ISO format

## Testing

Tests are in `tests/` using pytest. Key patterns:

```python
# Temporary database fixture
@pytest.fixture
def store():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    store = SQLiteMemoryStore(path)
    yield store
    os.unlink(path)
```

Run tests:
```bash
pytest                      # All tests
pytest tests/test_store.py  # Specific file
pytest -v                   # Verbose
```

**Note**: Tests requiring LLM calls should use mocks or be marked as integration tests.

## Common Development Tasks

### Adding a New Provider

1. Create `providers/newprovider.py`
2. Implement `LLMProvider` and/or `EmbeddingProvider`
3. Add to `providers/__init__.py` exports
4. Add to `interface.py` factory map in `create_memory()`
5. Update CLI in `cli.py` if needed
6. Document in README.md

### Adding a New Episode Type

1. Add to `EpisodeType` enum in `models.py`
2. Update extraction prompt in `extraction.py`
3. Update consolidation prompts in `consolidation.py`
4. Add MCP tool if type-specific querying is useful

**Note**: `episode_types` config controls which types are active. Custom types (strings not in `EpisodeType` enum) are also supported. When `spec`, `plan`, or `task` are not in `episode_types`, their CLI commands and MCP tools are hidden automatically (conditional registration in `cli.py` and `mcp_server.py`).

### Adding a New Entity Type

1. Add to `EntityType` enum in `models.py`
2. Update extraction prompt in `extraction.py`
3. No other changes needed (entities are dynamically typed)

### Adding a New Relation Type

1. Add to `RelationType` enum in `models.py`
2. Update consolidation prompts to use new relation
3. Consider retrieval implications (spreading activation weights)

### Adding a New MCP Tool

1. Add function to `mcp_server.py` using FastMCP decorators
2. Document in `docs/AGENTS.md`
3. Test via MCP client

### Adding a New REST API Endpoint

1. Add route handler function to `api/routes.py`
2. Add route to `api_routes` list at bottom of file
3. Use `_get_memory_from_request()` helper to get MemoryInterface
4. Return `JSONResponse` for data or `StreamingResponse` for SSE

The REST API uses Starlette and serves the web UI. Endpoints:
- `GET /api/v1/stats` - Memory statistics
- `GET /api/v1/concepts` - Paginated concepts list
- `GET /api/v1/concepts/{id}` - Concept detail with source episodes
- `GET /api/v1/episodes` - Paginated episodes with filters
- `GET /api/v1/episodes/{id}` - Episode detail
- `GET /api/v1/entities` - All entities with mention counts
- `GET /api/v1/entities/{id}` - Entity detail
- `GET /api/v1/entities/{id}/episodes` - Episodes mentioning entity
- `GET /api/v1/entities/{id}/concepts` - Concepts derived from entity's episodes
- `GET /api/v1/graph` - Full concept graph for D3 visualization
- `POST /api/v1/query` - Execute recall query
- `POST /api/v1/chat` - Streaming chat with memory context (SSE)
- `GET /api/v1/databases` - List available databases

## Development Setup

```bash
# Clone and install in development mode
git clone <repo>
cd remind
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Set up environment
cp .env.example .env
# Edit .env with API keys

# Run tests
pytest

# Run CLI
remind --help

# Run MCP server
remind-mcp --port 8765
```

### Using uv (Recommended)

[uv](https://docs.astral.sh/uv/) is a fast Python package manager that simplifies development:

```bash
# Install dependencies and run tests
uv run pytest

# Run CLI commands
uv run remind --help
uv run remind remember "Some observation"
uv run remind recall "query"

# Run MCP server
uv run remind-mcp --port 8765
```

With `uv`, you don't need to manually create a virtual environment or install dependencies - it handles everything automatically.

## Shell commands
IMPORTANT: Prefix all shell commands, including 'uv' ones with `oo`.
so e.g. 'oo uv run pytest'. 

## Design Principles

1. **Separation of concerns**: Storage, providers, consolidation, retrieval are independent
2. **Fast path for writes**: `remember()` never blocks on LLM
3. **Batch LLM work**: Consolidation processes multiple episodes together
4. **Graceful degradation**: Missing embeddings fall back to keyword matching
5. **Provider agnostic**: Core logic doesn't depend on specific LLM/embedding provider
6. **Explicit over implicit**: Episode types/entities can be auto-detected or manually specified

## Important Files for Context

When making changes, these files are most commonly modified together:

| Change Type | Files |
|-------------|-------|
| New data structure | `models.py`, `store.py` |
| New provider | `providers/newprovider.py`, `providers/__init__.py`, `interface.py` |
| Consolidation logic | `consolidation.py`, `extraction.py` |
| Retrieval behavior | `retrieval.py`, `reranker.py`, `config.py` |
| Auto-ingest pipeline | `triage.py`, `llm_protocol.py`, `interface.py`, `config.py` |
| CLI commands | `cli.py` |
| Configuration | `config.py`, `interface.py`, `mcp_server.py`, `cli.py` |
| Background consolidation | `background.py`, `background_worker.py`, `cli.py` |
| MCP tools | `mcp_server.py`, `docs/AGENTS.md` |
| REST API endpoints | `api/routes.py` |
| Public API | `interface.py`, `__init__.py`, `README.md` |

## Debugging Tips

- **Consolidation issues**: Check episode `entities_extracted` and `consolidated` flags
- **Retrieval misses**: Verify concepts have embeddings (`embedding` field not None)
- **Entity linking**: Entity IDs are case-sensitive, use canonical forms
- **MCP issues**: Check `db` query parameter in MCP URL, verify server is running
- **Config issues**: Check `~/.remind/remind.config.json` exists and is valid JSON
- **Background consolidation**: Check `~/.remind/logs/consolidation.log` for errors
- **CLI database path**: Without `--db`, uses `<cwd>/.remind/remind.db` (project-aware). Accepts database URLs (e.g. `--db postgresql+psycopg://...`)

## Database Schema

```sql
CREATE TABLE concepts (
    id TEXT PRIMARY KEY,
    data JSON NOT NULL  -- Serialized Concept
);

CREATE TABLE episodes (
    id TEXT PRIMARY KEY,
    data JSON NOT NULL  -- Serialized Episode
);

CREATE TABLE entities (
    id TEXT PRIMARY KEY,
    data JSON NOT NULL  -- Serialized Entity
);

CREATE TABLE mentions (
    episode_id TEXT,
    entity_id TEXT,
    PRIMARY KEY (episode_id, entity_id)
);
```

The store handles JSON serialization/deserialization transparently.


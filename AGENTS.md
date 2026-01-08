# Remind - Development Guide for AI Agents

This guide is for AI agents developing **Remind itself**. For using Remind as a memory layer, see [docs/AGENTS.md](./docs/AGENTS.md).

## Project Overview

Remind is a generalization-capable memory layer for LLMs. It differs from simple RAG by extracting and maintaining **generalized concepts** from episodic experiences, mimicking how human memory consolidates specific events into abstract knowledge.

**Core insight**: Episodes → Consolidation (LLM-powered "sleep") → Concepts with relations

## Architecture

```
src/remind/
├── models.py          # Data models (Concept, Episode, Entity, Relation)
├── store.py           # SQLite persistence layer
├── interface.py       # MemoryInterface - main public API
├── consolidation.py   # LLM-powered episode → concept transformation
├── extraction.py      # Entity/type extraction from episodes
├── retrieval.py       # Spreading activation retrieval
├── cli.py             # Command-line interface
├── mcp_server.py      # MCP (Model Context Protocol) server
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

**Episode lifecycle**: Created via `remember()` → Entity extraction → Consolidation → Marked consolidated

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
2. **`consolidate()` does all LLM work** - extraction + generalization
3. **Two consolidation modes**: Automatic (threshold-based) or manual (hook-based)

```python
# Consolidation happens in two phases:
# 1. Extract entities/types from unextracted episodes
# 2. Generalize episodes into concepts (the "sleep" process)
```

### Consolidation (`consolidation.py`)

The "brain" of the system. Uses LLM to:
- Classify episode types (observation, decision, question, meta, preference)
- Extract entity mentions from natural language
- Identify patterns across episodes
- Create generalized concepts with relations
- Detect contradictions

### Retrieval (`retrieval.py`)

**Spreading activation** algorithm:
1. Query is embedded and matched to concepts via cosine similarity
2. Matched concepts activate related concepts through the graph
3. Activation spreads with decay over multiple hops
4. Highest-activation concepts are returned

Key class: `MemoryRetriever` with `ActivatedConcept` results.

### Store (`store.py`)

SQLite-based persistence. Tables:
- `concepts` - Stores concepts with JSON-serialized relations
- `episodes` - Raw episodes with consolidation status
- `entities` - Entity registry
- `mentions` - Episode-entity junction table

The `MemoryStore` protocol defines the interface for alternative storage backends.

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
| Retrieval behavior | `retrieval.py` |
| CLI commands | `cli.py` |
| MCP tools | `mcp_server.py`, `docs/AGENTS.md` |
| REST API endpoints | `api/routes.py` |
| Public API | `interface.py`, `__init__.py`, `README.md` |

## Debugging Tips

- **Consolidation issues**: Check episode `entities_extracted` and `consolidated` flags
- **Retrieval misses**: Verify concepts have embeddings (`embedding` field not None)
- **Entity linking**: Entity IDs are case-sensitive, use canonical forms
- **MCP issues**: Check `db` query parameter in MCP URL, verify server is running

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


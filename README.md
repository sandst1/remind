# Remind

[![PyPI version](https://img.shields.io/pypi/v/remind-mcp.svg)](https://pypi.org/project/remind-mcp/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)

Agent-driven memory layer for LLMs. Remind is a deterministic memory substrate with temporal facts, semantic retrieval, and structured curation — the calling agent is the only intelligence.

**[Documentation](https://sandst1.github.io/remind/)** · **[Examples](https://sandst1.github.io/remind/examples/)** · **[Changelog](https://sandst1.github.io/remind/reference/changelog)**

## Quick start

```bash
pip install remind-mcp
```

**No configuration required** — Remind uses local embeddings by default (fastembed, no API key).

```bash
remind remember "This project uses React with TypeScript"
remind remember "Chose PostgreSQL for the database" -t decision
remind remember "Cache TTL is 600 seconds" -t fact -e concept:caching
remind recall "What tech stack are we using?"
```

## How it works

Remind stores **episodes** (raw experiences) and **concepts** (generalized knowledge). You capture and curate memories explicitly using CLI commands or MCP tools.

For **facts** (`-t fact`), Remind automatically:
1. Creates a `Fact` row with validity tracking
2. Assigns it to a cluster based on entity overlap (Jaccard similarity)
3. Detects potential collisions with existing facts (returned for your review)

For **patterns and concepts**, you use `remind apply` to create them from episodes:

```bash
remind apply << 'EOF'
concept from=ep:11,ep:12 title="Retry-with-backoff for resilience" "Exponential backoff resolves flaky deploys and API timeouts."
processed ids=ep:11,ep:12
EOF
```

## Two batch tools

### `remind snapshot` — Read state

```bash
remind snapshot stats pending conflicts              # Memory overview
remind snapshot entity:concept:caching               # Everything about an entity
remind snapshot concept:abc123                       # Concept detail with history
```

Returns JSON. Combinable scopes: `pending`, `conflicts`, `entity:<id>`, `topic:<id>`, `concept:<id>`, `recent:<n>`, `stats`, `query:<text>`.

### `remind apply` — Write changes

```bash
remind apply << 'EOF'
remember as=f1 t=fact e=concept:cache "Cache TTL is 600 seconds"
supersede old=fact:old123 new=$f1
concept from=ep:1,ep:2 title="Pattern name" "Summary"
resolve id=conflict:7 winner=fact:abc "confirmed by alice"
processed ids=ep:1,ep:2
EOF
```

Operations: `remember`, `supersede`, `conflict`, `resolve`, `dismiss`, `concept`, `update`, `link`, `topic`, `set_topic`, `delete`, `restore`, `processed`.

All operations run in a single transaction. `--dry-run` validates without executing.

## Agent skills

Install skills to teach AI agents how to use Remind:

```bash
remind skill-install
```

Three skills:
- **remind-capture** — When and how to write memories
- **remind-context** — When and how to recall before acting
- **remind-curate** — How to process pending episodes into concepts, resolve conflicts, maintain quality

## MCP Server

For IDE agents (Cursor, Claude Desktop, etc.):

```bash
remind-mcp --port 8765
```

```json
{
  "mcpServers": {
    "remind": {
      "url": "http://127.0.0.1:8765/sse?db=my-project"
    }
  }
}
```

Tools: `remember`, `recall`, `snapshot`, `apply`, plus topic/conflict/entity management.

Web UI at `http://127.0.0.1:8765/ui/`, REST API at `/api/v1/`.

## Key features

- **Zero-config embeddings** — Local fastembed by default (no API key required)
- **Temporal facts** — Validity windows, structural supersession, time-travel queries (`--as-of`)
- **Conflict detection** — Collisions reported on write for your disposition
- **Transactional writes** — `apply` runs all operations atomically
- **Spreading activation retrieval** — Queries activate related concepts through the knowledge graph
- **Native vector indexes** — sqlite-vec (SQLite), pgvector (PostgreSQL)
- **Entity graph** — Files, functions, people, tools linked to episodes and concepts
- **Memory decay** — Rarely-recalled concepts fade
- **Soft delete / restore** — With permanent purge as a separate step
- **Web UI** — Dashboard, concept graph, entity explorer, conflicts inbox

## Embedding providers

Local embedding is the default (384-dim `all-MiniLM-L6-v2`). For cloud embeddings:

```bash
pip install "remind-mcp[openai]"   # OpenAI embeddings
pip install "remind-mcp[rerank]"   # Cross-encoder reranking
```

```json
{
  "embedding_provider": "openai",
  "openai": { "api_key": "sk-..." }
}
```

## Database backends

SQLite is the default. For PostgreSQL or MySQL:

```bash
pip install "remind-mcp[postgres]"   # PostgreSQL (psycopg v3 + pgvector)
pip install "remind-mcp[mysql]"      # MySQL (PyMySQL)
```

```bash
export REMIND_DB_URL="postgresql+psycopg://user:pass@localhost:5432/mydb"
```

## CLI reference

```
Core
  remember     Add an episode (-t type, -e entity, --asserted-by, --source-ref)
  recall       Semantic or entity-based retrieval (-k, --episode-k, --as-of)
  snapshot     Read memory state as JSON (combinable scopes)
  apply        Apply a batch changeset transactionally

Inspection
  inspect      List or detail concepts; use --episodes for episodes
  stats        Memory statistics
  entities     List entities or show details
  
Episode types
  decisions    Show decision episodes
  questions    Show open question episodes

Topics
  topics list/create/update/delete/overview

Conflicts
  conflicts list/resolve/dismiss

Editing
  update-episode/update-concept
  delete-episode/restore-episode/purge-episode
  delete-concept/restore-concept/purge-concept

Embeddings
  embed-episodes  Backfill embeddings
  re-embed        Recompute embeddings (--episodes/--concepts/--entities/--all)

Import / Export
  export/import

Skills
  skill-install  Install Remind skills

UI
  ui           Launch the web UI
```

## Documentation

Full documentation at **[sandst1.github.io/remind](https://sandst1.github.io/remind/)**:

- [What is Remind?](https://sandst1.github.io/remind/guide/what-is-remind) — How it works
- [Skills + CLI](https://sandst1.github.io/remind/guide/skills) — Agent integration
- [Configuration](https://sandst1.github.io/remind/guide/configuration) — Providers, config
- [CLI Reference](https://sandst1.github.io/remind/reference/cli-commands) — All commands
- [MCP Tools](https://sandst1.github.io/remind/reference/mcp-tools) — MCP reference

## License

Apache 2.0 ([LICENSE](./LICENSE))

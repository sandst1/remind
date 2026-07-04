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
3. Detects potential collisions with existing facts — same-cluster collisions and cross-cluster related facts are returned with ready-to-paste `apply` commands

For any `remember` call, the output also surfaces the **top-5 nearest episodes and concepts** semantically, so you can catch contradictions before they go unnoticed.

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
remind snapshot stats pending conflicts health        # Full overview
remind snapshot entity:concept:caching                # Everything about an entity
remind snapshot concept:abc123                        # Concept detail with history

# Browse scopes (for exploring memory)
remind snapshot concepts                              # All concepts
remind snapshot episodes:20                           # Recent 20 episodes
remind snapshot entities:person                       # Entities filtered by type
remind snapshot topics                                # All topics with stats
remind snapshot decisions questions                   # Episodes by type
```

Returns JSON. Combinable scopes:

| Scope | Description |
|-------|-------------|
| `pending` | Unprocessed episodes with their entities |
| `conflicts[:<status>]` | Open conflicts (or `resolved`/`dismissed`/`all`) |
| `health` | Actionable issues: pending episodes, open conflicts, orphan concepts |
| `stats` | Memory statistics |
| `concepts[:<n>]` | All concepts (default 50) |
| `episodes[:<n>]` | Recent episodes (default 20) |
| `entities[:<type>]` | All entities with mention counts, filterable by type |
| `topics` | All topics with episode and concept counts |
| `decisions[:<n>]` | Recent decision episodes |
| `questions[:<n>]` | Recent question episodes |
| `entity:<id>` | Episodes and concepts for a specific entity |
| `topic:<id>` | All episodes and concepts for a topic |
| `concept:<id>` | Concept detail with facts and supersession history |
| `recent:<n>` | N most recent episodes |
| `query:<text>` | Semantic search results |

### `remind apply` — Write changes

```bash
remind apply << 'EOF'
remember as=f1 t=fact e=concept:cache "Cache TTL is 600 seconds"
supersede old=fact:old123 new=$f1
concept as=c1 from=ep:1,ep:2 title="Pattern name" "Summary"
evidence concept=$c1 episode=ep:3 type=supports strength=0.8 "confirms pattern"
resolve id=conflict:7 winner=fact:abc "confirmed by alice"
processed ids=ep:1,ep:2
EOF
```

All operations run in a single transaction. `--dry-run` validates without executing.

**Operations:**

| Op | Description |
|----|-------------|
| `remember` | Store episode (same params as CLI `remember`) |
| `supersede old=<fact> new=<fact>` | Replace old fact — auto-records resolved conflict |
| `conflict fact_a=<id> fact_b=<id>` | Flag contradiction for triage |
| `resolve id=<conflict> winner=<fact>` | Resolve conflict; losing fact is superseded |
| `dismiss id=<conflict>` | Dismiss conflict (both facts stay active) |
| `concept from=<eps> title="..." "summary"` | Create concept from episodes |
| `link from=<concept> to=<concept> type=<relation>` | Add concept relation |
| `evidence concept=<id> episode=<id> type=<supports\|contradicts\|qualifies>` | Link episode evidence to concept |
| `unlink concept=<id> episode=<id>` | Remove evidence link |
| `entity_relation source=<id> target=<id> relation=<type>` | Create entity graph edge |
| `reshape id=<concept> type=<new_type>` | Change concept type |
| `merge from=<id1>,<id2> into=<new_id>` | Combine overlapping concepts |
| `split id=<concept> into=<id1>,<id2>` | Separate distinct concerns |
| `update id=<id> [field=value...]` | Update episode or concept fields |
| `topic name="Name"` | Create topic |
| `set_topic id=<id> topic=<topic_id>` | Assign episode/concept to topic |
| `delete id=<id>` / `restore id=<id>` | Soft delete / restore |
| `processed ids=<ep1>,<ep2>` | Mark episodes as reviewed |

## Agent skills

Install skills to teach AI agents how to use Remind:

```bash
remind skill-install
```

Three skills:
- **remind-capture** — When and how to write memories (includes decision tree and entity type guide)
- **remind-context** — When and how to recall before acting (includes output interpretation guide)
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
- **Collision detection** — Same-cluster and cross-cluster collisions reported on write with ready-to-paste `apply` commands
- **Nearby surfacing** — Every `remember` call returns the top-k semantically nearest episodes and concepts for immediate conflict triage
- **Evidence-weighted retrieval** — Episodes link to concepts with typed relationships (`supports`, `contradicts`, `qualifies`); more evidence = higher recall rank
- **Freeform concept types** — Concepts can have any type string: `pattern`, `rule`, `procedure`, `hypothesis`, or any domain-specific label
- **Concept evolution** — `reshape` (change type), `merge` (combine overlapping), `split` (separate concerns), all with lineage tracking
- **Transactional writes** — `apply` runs all operations atomically
- **Spreading activation retrieval** — Queries activate related concepts through the knowledge graph
- **Native vector indexes** — sqlite-vec (SQLite), pgvector (PostgreSQL)
- **Entity graph** — Files, functions, people, tools linked to episodes and concepts via `entity_relation`
- **Memory decay** — Rarely-recalled concepts fade
- **Soft delete / restore** — With permanent purge as a separate step
- **Web UI** — Dashboard, concept graph, entity explorer

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

**Entity types**: `file`, `function`, `class`, `module`, `subject`, `person`, `project`, `tool` — format is `type:name` (e.g., `file:src/auth.ts`, `person:alice`, `tool:redis`, `concept:caching`)

## Documentation

Full documentation at **[sandst1.github.io/remind](https://sandst1.github.io/remind/)**:

- [What is Remind?](https://sandst1.github.io/remind/guide/what-is-remind) — How it works
- [Skills + CLI](https://sandst1.github.io/remind/guide/skills) — Agent integration
- [Configuration](https://sandst1.github.io/remind/guide/configuration) — Providers, config
- [CLI Reference](https://sandst1.github.io/remind/reference/cli-commands) — All commands
- [MCP Tools](https://sandst1.github.io/remind/reference/mcp-tools) — MCP reference

## License

Apache 2.0 ([LICENSE](./LICENSE))

# MCP Server

Remind can run as an [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) server, allowing AI agents in IDEs like Cursor to use it as their memory system over HTTP.

## When to use MCP

MCP is a good fit when:

- Your IDE/agent supports MCP natively (Cursor, Claude Desktop, etc.)
- You want **centralized** memory across projects (named stores at `~/.remind/<name>.memory`)
- You want the agent to use Remind tools directly without shell access

For **project-scoped** memory with composable workflows, see [Skills + CLI](/guide/skills) instead.

## Starting the server

```bash
# After pip install
remind-mcp --port 8765

# Or with uv (no install needed)
uvx remind-mcp --port 8765

# Or with Docker
docker compose up -d
```

## Connecting from Cursor

Add to your project's `.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "remind": {
      "url": "http://127.0.0.1:8765/sse?db=my-project"
    }
  }
}
```

The `db` parameter is a simple name that resolves to the Git-friendly file store `~/.remind/{name}.memory`. Each project can have its own store. Explicit SQL URLs, including `sqlite:////absolute/path/to/remind.db`, continue to select SQL storage.

## Available tools

Full parameter lists and examples: **[MCP tools reference](/reference/mcp-tools)**.

Summary:

| Tool | Purpose |
|------|---------|
| `remember` | Store an episode (returns collision info for facts) |
| `remember_batch` | Atomically capture multiple separate assertions |
| `recall` | Spreading activation (+ optional `entity`, `labels`, `as_of`) |
| `snapshot` | Batch read (pending episodes, conflicts, entities, labels, concepts) |
| `apply` | Batch write (create concepts, supersede facts, resolve conflicts, label/unlabel) |
| `poll_events` | Poll durable changes with a generation-qualified cursor |
| `events` | Legacy numeric-sequence change feed for one projection |
| `doctor` | Diagnose integrity, embedding compatibility, and source freshness |
| `stats` | Memory statistics |
| `list_conflicts` / `resolve_conflict` / `dismiss_conflict` | Manage detected conflicts |
| `inspect` | Concept detail with facts and supersession history |
| `entities` / `inspect_entity` | List and inspect entities |
| `update_episode` / `delete_episode` / `restore_episode` | Manage episodes |
| `update_concept` / `delete_concept` / `restore_concept` | Manage concepts |
| `list_deleted` | Review soft-deleted episodes/concepts |

See [MCP Tools reference](/reference/mcp-tools) for the full parameter list of every tool.

## Agent instructions

Copy [docs/AGENTS.md](https://github.com/sandst1/remind/blob/main/docs/AGENTS.md) into your project to instruct AI agents how to use Remind's MCP tools. This covers:

- **Capture** — When and how to use `remember` (including fact collisions)
- **Recall** — Semantic, entity, and label-scoped queries with time-travel
- **Curation** — Using `snapshot` and `apply` for batch memory management

## Docker

Run Remind as a persistent background service:

```bash
docker compose up -d
```

The container:
- Mounts `~/.remind` from your host for database persistence
- Exposes port 8765 for MCP SSE, Web UI, and REST API
- Uses local embeddings by default (no API keys needed)
- Restarts automatically on crash/reboot

Access endpoints:
- **MCP SSE**: `http://localhost:8765/sse?db=my-project`
- **Web UI**: `http://localhost:8765/ui/?db=my-project`
- **REST API**: `http://localhost:8765/api/v1/...`

## Optional: Remote embeddings

To use OpenAI embeddings instead of local:

```bash
cp .env.example .env   # Edit with OPENAI_API_KEY
docker compose up -d
```

Or set environment variables when running the server directly.

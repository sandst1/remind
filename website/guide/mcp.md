# MCP Server

Remind can run as an [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) server, allowing AI agents in IDEs like Cursor to use it as their memory system over HTTP.

## When to use MCP

MCP is a good fit when:

- Your IDE/agent supports MCP natively (Cursor, Claude Desktop, etc.)
- You want **centralized** memory across projects (databases at `~/.remind/`)
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

The `db` parameter is a simple name that resolves to `~/.remind/{name}.db`. Each project can have its own database.

## Available tools

| Tool | Purpose |
|------|---------|
| `remember` | Store experiences (observation, decision, question, preference, meta, spec, plan, task, outcome, fact) |
| `recall` | Retrieve relevant memories via spreading activation or entity lookup |
| `ingest` | Stream raw text for automatic density scoring and episode extraction |
| `flush_ingest` | Force-flush the ingestion buffer |
| `consolidate` | Process episodes into concepts |
| `inspect` | View concepts or episodes |
| `entities` | List entities with mention counts |
| `inspect_entity` | View entity details and relationships |
| `stats` | Memory statistics |
| `update_episode` | Correct or modify an episode |
| `delete_episode` | Soft delete an episode |
| `restore_episode` | Restore a deleted episode |
| `update_concept` | Refine a concept |
| `delete_concept` | Soft delete a concept |
| `restore_concept` | Restore a deleted concept |
| `list_deleted` | List soft-deleted items |
| `task_add` | Create a task with priority, plan, and dependency links |
| `task_update_status` | Transition task status |
| `list_tasks` | List tasks with filters |
| `list_specs` | List spec episodes |
| `list_plans` | List plan episodes |

## Agent instructions

Copy [docs/AGENTS.md](https://github.com/sandst1/remind/blob/main/docs/AGENTS.md) into your project to instruct AI agents how to use Remind's MCP tools. This covers the workflow (recall at session start, remember during work, consolidate at end) and best practices.

## Docker

Run Remind as a persistent background service:

```bash
cp .env.example .env   # Edit with your API keys
docker compose up -d
```

The container:
- Mounts `~/.remind` from your host for database persistence
- Reads API keys from `.env`
- Exposes port 8765 for MCP SSE, Web UI, and REST API
- Restarts automatically on crash/reboot

Access endpoints:
- **MCP SSE**: `http://localhost:8765/sse?db=my-project`
- **Web UI**: `http://localhost:8765/ui/?db=my-project`
- **REST API**: `http://localhost:8765/api/v1/...`

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

Full parameter lists and examples: **[MCP tools reference](/reference/mcp-tools)**.

Summary:

| Tool | Purpose |
|------|---------|
| `remember` | Store an episode (optional `episode_type`, `entities`, `topic`, `source_type`, `metadata`) |
| `recall` | Spreading activation (+ optional `entity`, `episode_k`, `topic`) |
| `ingest` | Buffer raw text; **triage LLM** extracts episodes. Optional density score is **diagnostic only**, not a gate |
| `flush_ingest` | Flush buffer (optional `topic`, `instructions`) |
| `list_topics` | List topics with counts |
| `create_topic` / `update_topic` / `delete_topic` | Manage topics |
| `topic_overview` | Top concepts for a topic (`topic_id`) |
| `consolidate` | Run consolidation (`force`) |
| `inspect` | Concepts or episodes (`show_episodes`, date filters, `limit`) |
| `stats` | Memory statistics |
| `episode_types` | Show configured episode types |
| `entities` / `inspect_entity` | Entity graph |
| `update_episode` / `delete_episode` / `restore_episode` | Episode maintenance (`topic` clears with `""`) |
| `update_concept` / `delete_concept` / `restore_concept` | Concept maintenance |
| `list_deleted` | Soft-deleted items (`item_type`: `episodes`, `concepts`, `all`) |

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

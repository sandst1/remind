# Remind

[![PyPI version](https://img.shields.io/pypi/v/remind-mcp.svg)](https://pypi.org/project/remind-mcp/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)

Generalization-capable memory layer for LLMs. Unlike simple RAG systems that store verbatim text, Remind extracts and maintains *generalized concepts* from experiences — mimicking how human memory consolidates specific events into abstract knowledge.

**[Documentation](https://sandst1.github.io/remind/)** · **[Examples](https://sandst1.github.io/remind/examples/)** · **[Changelog](https://sandst1.github.io/remind/reference/changelog)**

## Quick start

```bash
pip install remind-mcp
```

Configure a provider (`~/.remind/remind.config.json`):

```json
{
  "llm_provider": "anthropic",
  "embedding_provider": "openai",
  "anthropic": { "api_key": "sk-ant-..." },
  "openai": { "api_key": "sk-..." }
}
```

Use it:

```bash
remind remember "This project uses React with TypeScript"
remind remember "Chose PostgreSQL for the database" -t decision
remind consolidate
remind recall "What tech stack are we using?"
```

Episodes go in, consolidation runs, generalized concepts come out.

## Two ways to use Remind

### Skills + CLI (recommended)

Project-local memory via composable skills. The database lives in your repo at `.remind/remind.db`.

```bash
remind skill-install                    # Install all skills
remind skill-install remind remind-plan # Install specific skills
remind remember "..."                   # Store experiences
remind recall "..."                     # Retrieve memories
remind end-session                      # Consolidate at end of session
```

Available skills: `remind` (core memory), `remind-plan` (interactive planning), `remind-spec` (spec-driven development), `remind-implement` (task execution). Write your own skills for any workflow.

Skills are Markdown files read by AI agents (Claude Code, Cursor, etc.) — they teach the agent how to use Remind as a memory layer for your project.

### MCP Server

Centralized memory for IDE agents (Cursor, Claude Desktop, etc.):

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

The MCP server also serves a web UI at `http://127.0.0.1:8765/ui/` and a REST API at `/api/v1/`.

You can also launch the UI directly from the CLI against the current project's database:

```bash
remind ui
```

## Key features

- **Generalization** — Episodes are consolidated into concepts with confidence, conditions, and exceptions
- **Auto-ingest** — Stream raw conversation text; Remind scores information density and distills memory-worthy episodes automatically
- **Spreading activation retrieval** — Queries activate related concepts through the knowledge graph
- **Entity graph** — Files, functions, people, tools and other entities are extracted and linked to episodes and concepts
- **Outcome tracking** — Record action-result pairs; consolidation extracts causal strategy patterns
- **Task management** — Track work items (todo → in\_progress → done / blocked) with priorities and dependencies
- **Specs and plans** — First-class episode types for requirements and implementation plans
- **Soft delete / restore** — Episodes and concepts can be deleted and restored; permanent purge is a separate step
- **Memory decay** — Rarely-recalled concepts fade; frequently-used ones stay sharp
- **Composable via Skills** — Build any workflow on top of the `remind` CLI
- **Multi-provider** — Anthropic, OpenAI, Azure OpenAI, Ollama (fully local)
- **Web UI** — Dashboard, concept graph, entity explorer, task board

## CLI reference

```
Core
  remember     Add an episode (-t type, -e entity, -m metadata)
  recall       Semantic or entity-based memory retrieval
  ingest       Auto-ingest raw text with density scoring
  flush-ingest Force-flush the ingestion buffer
  consolidate  Run consolidation manually (--background, --force)
  reconsolidate  Reset derived data and re-consolidate from scratch
  end-session  Flush ingest buffer, then consolidate in background

Inspection
  inspect      List or detail concepts; use --episodes for episodes
  stats        Memory statistics and decay info
  search       Keyword/tag search across concepts
  entities     List entities or show a specific entity
  mentions     All episodes mentioning an entity
  entity-relations  Relationships between entities

Episode types
  decisions    Show decision episodes
  questions    Show open question episodes
  specs        Show spec episodes (requirements)
  plans        Show plan episodes

Task management
  tasks               List tasks grouped by status
  task add            Create a task (--priority, --plan, --spec, --depends-on)
  task update         Update a task's linkage, priority, or description (--plan, --spec, --depends-on, --priority)
  task start          Mark task in_progress
  task done           Mark task done
  task block          Block a task with an optional reason
  task unblock        Return a blocked task to todo

Editing
  update-episode      Update content, type, entities, or metadata (--plan, --spec, --depends-on, --priority)
  update-concept      Update title, summary, confidence, tags, or relations
  extract-relations   Backfill entity relationships from existing episodes

Soft delete / restore
  delete-episode   Soft delete an episode
  restore-episode  Restore a soft-deleted episode
  purge-episode    Permanently delete an episode

  delete-concept   Soft delete a concept
  restore-concept  Restore a soft-deleted concept
  purge-concept    Permanently delete a concept

  deleted          List all soft-deleted items
  purge-all        Permanently delete all soft-deleted items

Import / Export
  export       Export memory to JSON
  import       Import memory from JSON

Skills
  skill-install  Install Remind skills into .claude/skills/

UI
  ui           Launch the web UI (auto-opens browser)
```

## Documentation

Full documentation at **[sandst1.github.io/remind](https://sandst1.github.io/remind/)**:

- [What is Remind?](https://sandst1.github.io/remind/guide/what-is-remind) — How it works, how it differs from RAG
- [Skills + CLI](https://sandst1.github.io/remind/guide/skills) — The recommended integration path
- [Configuration](https://sandst1.github.io/remind/guide/configuration) — Providers, config file, env vars
- [Core Concepts](https://sandst1.github.io/remind/concepts/episodes) — Episodes, consolidation, concepts, entities, relations
- [Examples](https://sandst1.github.io/remind/examples/) — Project memory, sparring partner, research ingestion
- [CLI Reference](https://sandst1.github.io/remind/reference/cli-commands) — All commands
- [MCP Tools](https://sandst1.github.io/remind/reference/mcp-tools) — MCP tool reference

## License

Apache 2.0 ([LICENSE](./LICENSE))

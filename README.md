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
remind end-session                      # Consolidate
```

Available skills: `remind` (core memory), `remind-plan` (interactive planning), `remind-spec` (spec-driven development), `remind-implement` (task execution). Write your own skills for any workflow.

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

## Key features

- **Generalization** — Episodes are consolidated into concepts with confidence, conditions, and exceptions
- **Spreading activation retrieval** — Queries activate related concepts through the knowledge graph
- **Composable via Skills** — Build any workflow on top of the `remind` CLI
- **Task management** — Track work items with status lifecycle and dependency chains
- **Multi-provider** — Anthropic, OpenAI, Azure OpenAI, Ollama (fully local)
- **Web UI** — Dashboard, concept graph, entity explorer, task board
- **Memory decay** — Rarely-recalled concepts fade; frequently-used ones stay sharp

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

# Getting Started

## Installation

::: code-group

```bash [pip]
pip install remind-mcp
```

```bash [pipx]
pipx install remind-mcp
```

```bash [uv]
# No install needed — run directly
uvx --from remind-mcp remind --help
```

```bash [Docker]
git clone https://github.com/sandst1/remind.git
cd remind
cp .env.example .env   # Edit with your API keys
docker compose up -d
```

:::

## Configure a provider

Remind needs an LLM provider (for consolidation) and an embedding provider (for retrieval). The simplest setup:

Create `~/.remind/remind.config.json`:

```json
{
  "llm_provider": "anthropic",
  "embedding_provider": "openai",
  "anthropic": {
    "api_key": "sk-ant-..."
  },
  "openai": {
    "api_key": "sk-..."
  }
}
```

Or use environment variables:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export OPENAI_API_KEY=sk-...
```

See [Configuration](/guide/configuration) for all provider options including Azure OpenAI and Ollama (fully local).

## Your first memory

```bash
# Store some experiences
remind remember "This project uses React with TypeScript"
remind remember "We chose PostgreSQL for the database" -t decision
remind remember "All API routes need authentication" -t spec

# Consolidate into concepts
remind consolidate

# Retrieve
remind recall "What tech stack are we using?"
```

That's it. Episodes go in, consolidation runs, generalized concepts come out.

## Next steps

- **[Skills + CLI](/guide/skills)** — The recommended integration path. Use Remind as a memory primitive inside agent skills.
- **[MCP Server](/guide/mcp)** — Run Remind as a centralized tool server for IDE agents.
- **[Core Concepts](/concepts/episodes)** — Understand episodes, consolidation, and the concept graph.
- **[Examples](/examples/)** — See Remind used for project memory, sparring, and research ingestion.

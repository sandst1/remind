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
docker compose up -d
```

:::

## Zero-config start

Remind works out of the box with **local embeddings** (no API keys needed):

```bash
# Store some experiences
remind remember "This project uses React with TypeScript"
remind remember "We chose PostgreSQL for the database" -t decision
remind remember "Cache TTL is 300s for auth tokens" -t fact -e tool:redis

# Retrieve
remind recall "What tech stack are we using?"
```

That's it. Episodes are stored and embedded locally using `all-MiniLM-L6-v2`.

## Fact handling

When you store a fact that might conflict with existing facts, Remind reports collisions:

```bash
# First fact
remind remember "Cache TTL is 300s" -t fact -e tool:redis

# Later, a new value
remind remember "Cache TTL is 600s" -t fact -e tool:redis
# Output: collision detected with fact:abc123 ("Cache TTL is 300s")
```

The agent decides what to do: supersede the old fact, open a conflict, or ignore.

## Batch operations

Use `snapshot` and `apply` for batch memory curation:

```bash
# See what needs review
remind snapshot pending,conflicts

# Apply a changeset
remind apply << 'EOF'
supersede old=fact:abc123 new=fact:def456
concept from=ep:11,ep:12 title="Redis caching" "TTL-based cache for auth tokens"
processed ids=ep:11,ep:12
EOF
```

## Optional: Remote embeddings

For higher-quality embeddings, configure a remote provider:

Create `~/.remind/remind.config.json`:

```json
{
  "embedding_provider": "openai",
  "openai": {
    "api_key": "sk-..."
  }
}
```

Or use environment variables:

```bash
export OPENAI_API_KEY=sk-...
export REMIND_EMBEDDING_PROVIDER=openai
```

See [Configuration](/guide/configuration) for all provider options including Azure OpenAI and Ollama.

## Next steps

- **[Skills + CLI](/guide/skills)** — The recommended integration path. Use Remind as a memory primitive inside agent skills.
- **[MCP Server](/guide/mcp)** — Run Remind as a centralized tool server for IDE agents.
- **[Core Concepts](/concepts/episodes)** — Understand episodes, facts, and the concept graph.
- **[Examples](/examples/)** — See Remind used for project memory, sparring, and research.

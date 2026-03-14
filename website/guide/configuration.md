# Configuration

Remind is configured via a config file, environment variables, or CLI arguments. Settings resolve with this priority (highest first):

1. CLI arguments (`--llm`, `--embedding`)
2. Environment variables (`ANTHROPIC_API_KEY`, etc.)
3. Config file (`~/.remind/remind.config.json`)
4. Defaults

## Config file

Create `~/.remind/remind.config.json`:

```json
{
  "llm_provider": "anthropic",
  "embedding_provider": "openai",
  "consolidation_threshold": 5,
  "auto_consolidate": true,

  "anthropic": {
    "api_key": "sk-ant-...",
    "model": "claude-sonnet-4-20250514"
  },

  "openai": {
    "api_key": "sk-...",
    "base_url": null,
    "model": "gpt-4.1",
    "embedding_model": "text-embedding-3-small"
  },

  "azure_openai": {
    "api_key": "...",
    "base_url": "https://your-resource.openai.azure.com",
    "api_version": "2024-02-15-preview",
    "deployment_name": "gpt-4",
    "embedding_deployment_name": "text-embedding-3-small",
    "embedding_size": 1536
  },

  "ollama": {
    "url": "http://localhost:11434",
    "llm_model": "llama3.2",
    "embedding_model": "nomic-embed-text"
  },

  "decay": {
    "enabled": true,
    "decay_interval": 20,
    "decay_rate": 0.1
  }
}
```

You only need to include settings you want to change from defaults. A minimal config:

```json
{
  "llm_provider": "anthropic",
  "embedding_provider": "openai",
  "anthropic": { "api_key": "sk-ant-..." },
  "openai": { "api_key": "sk-..." }
}
```

## Environment variables

### Anthropic (Claude)

```bash
ANTHROPIC_API_KEY=sk-ant-...
LLM_PROVIDER=anthropic
EMBEDDING_PROVIDER=openai   # Anthropic has no embeddings
```

### OpenAI

```bash
OPENAI_API_KEY=sk-...
LLM_PROVIDER=openai
EMBEDDING_PROVIDER=openai
```

### Azure OpenAI

```bash
AZURE_OPENAI_API_KEY=...
AZURE_OPENAI_API_BASE_URL=https://your-resource.openai.azure.com
AZURE_OPENAI_API_VERSION=2024-02-15-preview
AZURE_OPENAI_DEPLOYMENT_NAME=gpt-4
AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME=text-embedding-3-small
LLM_PROVIDER=azure_openai
EMBEDDING_PROVIDER=azure_openai
```

### Ollama (local)

No API keys needed. Install [Ollama](https://ollama.ai/) and pull models:

```bash
ollama pull llama3.2           # LLM
ollama pull nomic-embed-text   # Embeddings

# Optional overrides
OLLAMA_URL=http://localhost:11434
OLLAMA_LLM_MODEL=llama3.2
OLLAMA_EMBEDDING_MODEL=nomic-embed-text
LLM_PROVIDER=ollama
EMBEDDING_PROVIDER=ollama
```

## Database location

| Context | Default path |
|---------|-------------|
| CLI (no `--db` flag) | `<cwd>/.remind/remind.db` (project-local) |
| CLI with `--db name` | `~/.remind/name.db` |
| MCP Server / Python API | `~/.remind/{name}.db` |

## Memory decay

Concepts that are rarely recalled gradually lose retrieval priority, mimicking how human memory fades.

| Option | Default | Description |
|--------|---------|-------------|
| `decay.enabled` | `true` | Set `false` to disable |
| `decay.decay_interval` | `20` | Recalls between decay passes |
| `decay.decay_rate` | `0.1` | How much `decay_factor` drops per interval (0.0–1.0) |

When a concept is recalled, it gets **rejuvenated** — its decay factor gets a boost proportional to match strength. Recently recalled concepts are protected by a 60-second grace window.

View decay stats with `remind stats`.

## Consolidation

| Option | Default | Description |
|--------|---------|-------------|
| `consolidation_threshold` | `5` | Episodes before auto-consolidation triggers |
| `auto_consolidate` | `true` | Whether to auto-consolidate after `remember` |

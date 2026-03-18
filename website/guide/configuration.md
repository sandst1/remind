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
    "model": "claude-sonnet-4-20250514",
    "ingest_model": "claude-haiku-4-20250414"
  },

  "openai": {
    "api_key": "sk-...",
    "base_url": null,
    "model": "gpt-4.1",
    "embedding_model": "text-embedding-3-small",
    "ingest_model": "gpt-4.1-mini"
  },

  "azure_openai": {
    "api_key": "...",
    "base_url": "https://your-resource.openai.azure.com",
    "api_version": "2024-02-15-preview",
    "deployment_name": "gpt-4",
    "embedding_deployment_name": "text-embedding-3-small",
    "embedding_size": 1536,
    "ingest_deployment_name": "gpt-4-mini"
  },

  "ollama": {
    "url": "http://localhost:11434",
    "llm_model": "llama3.2",
    "embedding_model": "nomic-embed-text",
    "ingest_model": "llama3.2:1b"
  },

  "decay": {
    "enabled": true,
    "decay_interval": 20,
    "decay_rate": 0.1
  },

  "ingest_buffer_size": 4000,
  "ingest_min_density": 0.4,

  "logging_enabled": false
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

## Auto-ingest

Settings for the `ingest()` pipeline, which buffers raw text, scores information density, and extracts memory-worthy episodes automatically.

| Option | Default | Description |
|--------|---------|-------------|
| `ingest_buffer_size` | `4000` | Character threshold before buffer flushes and triggers triage |
| `ingest_min_density` | `0.4` | Minimum information density score (0.0-1.0) to extract episodes |

Each provider config has an optional `ingest_model` field (or `ingest_deployment_name` for Azure) to use a cheaper/faster model for triage without affecting consolidation quality. When unset, triage uses the same model as consolidation.

| Provider | Config field | Env var | Example |
|----------|-------------|---------|---------|
| Anthropic | `anthropic.ingest_model` | `ANTHROPIC_INGEST_MODEL` | `claude-haiku-4-20250414` |
| OpenAI | `openai.ingest_model` | `OPENAI_INGEST_MODEL` | `gpt-4.1-mini` |
| Azure OpenAI | `azure_openai.ingest_deployment_name` | `AZURE_OPENAI_INGEST_DEPLOYMENT_NAME` | `gpt-4-mini` |
| Ollama | `ollama.ingest_model` | `OLLAMA_INGEST_MODEL` | `llama3.2:1b` |

Environment variable overrides:

```bash
INGEST_BUFFER_SIZE=4000
INGEST_MIN_DENSITY=0.4
ANTHROPIC_INGEST_MODEL=claude-haiku-4-20250414
```

## Logging

When enabled, Remind writes detailed debug logs to `remind.log` in the same directory as the database. This includes full LLM prompts and responses for triage, extraction, and consolidation — useful for debugging why episodes were scored a certain way or how concepts were derived.

| Option | Default | Description |
|--------|---------|-------------|
| `logging_enabled` | `false` | Write debug logs to `remind.log` next to the database |

The log file location follows the database:

| Database path | Log path |
|--------------|----------|
| `~/.remind/myproject.db` | `~/.remind/remind.log` |
| `<project>/.remind/remind.db` | `<project>/.remind/remind.log` |

Enable via config file:

```json
{
  "logging_enabled": true
}
```

Or environment variable:

```bash
REMIND_LOGGING_ENABLED=true
```

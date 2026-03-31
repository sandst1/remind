# Configuration

Remind is configured via config files, environment variables, or CLI arguments. Settings resolve with this priority (highest first):

1. CLI arguments (`--llm`, `--embedding`)
2. Environment variables
3. Project-local config file (`<project>/.remind/remind.config.json`)
4. Global config file (`~/.remind/remind.config.json`)
5. Defaults

## Config files

### Global config

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

  "db_url": null,

  "logging_enabled": false,

  "episode_types": ["observation", "decision", "question", "meta", "preference",
                     "spec", "plan", "task", "outcome", "fact"]
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

### Project-local config

You can place a `remind.config.json` inside a project's `.remind/` directory to override global settings for that project:

```
myproject/
├── .remind/
│   ├── remind.config.json   ← project-local config
│   └── remind.db            ← project-local database
└── ...
```

Project-local config uses the same format as the global config. Settings in the project-local file override the global file, but are themselves overridden by environment variables and CLI arguments.

A typical use case is selecting a different provider or model for a specific project:

```json
{
  "llm_provider": "ollama",
  "ollama": { "llm_model": "deepseek-coder-v2" }
}
```

The CLI automatically reads `<cwd>/.remind/remind.config.json`. When using the Python API, pass `project_dir` to `create_memory()` to enable project-local config loading.

::: warning Do not commit secrets
If your project-local config contains API keys or other secrets, make sure `.remind/` is in your `.gitignore`. Better yet, keep secrets in the global config (`~/.remind/remind.config.json`) or in environment variables, and use the project-local file only for non-sensitive settings like provider choice and model selection.
:::

## Environment variables

Every config-file setting has a corresponding environment variable. Environment variables take precedence over both config files.

### Complete reference

#### General

| Env variable | Config field | Type | Default |
|---|---|---|---|
| `LLM_PROVIDER` | `llm_provider` | string | `anthropic` |
| `EMBEDDING_PROVIDER` | `embedding_provider` | string | `openai` |
| `CONSOLIDATION_THRESHOLD` | `consolidation_threshold` | int | `5` |
| `CONCEPTS_PER_PASS` | `concepts_per_pass` | int | `64` |
| `AUTO_CONSOLIDATE` | `auto_consolidate` | bool | `true` |
| `EXTRACTION_BATCH_SIZE` | `extraction_batch_size` | int | `50` |
| `EXTRACTION_LLM_BATCH_SIZE` | `extraction_llm_batch_size` | int | `10` |
| `CONSOLIDATION_BATCH_SIZE` | `consolidation_batch_size` | int | `25` |
| `LLM_CONCURRENCY` | `llm_concurrency` | int | `3` |
| `INGEST_BUFFER_SIZE` | `ingest_buffer_size` | int | `4000` |
| `INGEST_MIN_DENSITY` | `ingest_min_density` | float | `0.4` |
| `REMIND_DB_URL` | `db_url` | string | `null` (SQLite default) |
| `REMIND_LOGGING_ENABLED` | `logging_enabled` | bool | `false` |
| `REMIND_EPISODE_TYPES` | `episode_types` | comma-separated list | all built-in types |

#### Anthropic (Claude)

| Env variable | Config field | Type | Default |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | `anthropic.api_key` | string | — |
| `ANTHROPIC_MODEL` | `anthropic.model` | string | `claude-sonnet-4-20250514` |
| `ANTHROPIC_INGEST_MODEL` | `anthropic.ingest_model` | string | — |

#### OpenAI

| Env variable | Config field | Type | Default |
|---|---|---|---|
| `OPENAI_API_KEY` | `openai.api_key` | string | — |
| `OPENAI_BASE_URL` | `openai.base_url` | string | — |
| `OPENAI_MODEL` | `openai.model` | string | `gpt-4.1` |
| `OPENAI_EMBEDDING_MODEL` | `openai.embedding_model` | string | `text-embedding-3-small` |
| `OPENAI_INGEST_MODEL` | `openai.ingest_model` | string | — |

#### Azure OpenAI

| Env variable | Config field | Type | Default |
|---|---|---|---|
| `AZURE_OPENAI_API_KEY` | `azure_openai.api_key` | string | — |
| `AZURE_OPENAI_API_BASE_URL` | `azure_openai.base_url` | string | — |
| `AZURE_OPENAI_DEPLOYMENT_NAME` | `azure_openai.deployment_name` | string | — |
| `AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME` | `azure_openai.embedding_deployment_name` | string | — |
| `AZURE_OPENAI_EMBEDDING_SIZE` | `azure_openai.embedding_size` | int | `1536` |
| `AZURE_OPENAI_INGEST_DEPLOYMENT_NAME` | `azure_openai.ingest_deployment_name` | string | — |

#### Ollama (local)

| Env variable | Config field | Type | Default |
|---|---|---|---|
| `OLLAMA_URL` | `ollama.url` | string | `http://localhost:11434` |
| `OLLAMA_LLM_MODEL` | `ollama.llm_model` | string | `llama3.2` |
| `OLLAMA_EMBEDDING_MODEL` | `ollama.embedding_model` | string | `nomic-embed-text` |
| `OLLAMA_INGEST_MODEL` | `ollama.ingest_model` | string | — |

No API keys needed. Install [Ollama](https://ollama.ai/) and pull models:

```bash
ollama pull llama3.2           # LLM
ollama pull nomic-embed-text   # Embeddings
```

#### Memory decay

| Env variable | Config field | Type | Default |
|---|---|---|---|
| `REMIND_DECAY_ENABLED` | `decay.enabled` | bool | `true` |
| `REMIND_DECAY_INTERVAL` | `decay.decay_interval` | int | `20` |
| `REMIND_DECAY_RATE` | `decay.decay_rate` | float | `0.1` |

Boolean env vars accept `true`, `1`, `yes` (case-insensitive) as truthy values; anything else is falsy.

### Quick-start examples

**Anthropic + OpenAI embeddings (most common):**

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export OPENAI_API_KEY=sk-...
```

**OpenAI for everything:**

```bash
export OPENAI_API_KEY=sk-...
export LLM_PROVIDER=openai
export EMBEDDING_PROVIDER=openai
```

**Azure OpenAI:**

```bash
export AZURE_OPENAI_API_KEY=...
export AZURE_OPENAI_API_BASE_URL=https://your-resource.openai.azure.com
export AZURE_OPENAI_DEPLOYMENT_NAME=gpt-4
export AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME=text-embedding-3-small
export LLM_PROVIDER=azure_openai
export EMBEDDING_PROVIDER=azure_openai
```

**Ollama (fully local):**

```bash
export LLM_PROVIDER=ollama
export EMBEDDING_PROVIDER=ollama
```

## Database

Remind uses SQLite by default but supports any database backend via SQLAlchemy (PostgreSQL, MySQL, etc.).

### Database location (SQLite)

| Context | Default path |
|---------|-------------|
| CLI (no `--db` flag) | `<cwd>/.remind/remind.db` (project-local) |
| CLI with `--db name` | `~/.remind/name.db` |
| MCP Server / Python API | `~/.remind/{name}.db` |

### Using PostgreSQL or MySQL

Set `db_url` in config, the `REMIND_DB_URL` environment variable, or use the `--db` CLI flag with a full URL:

```bash
# Via environment variable
export REMIND_DB_URL="postgresql+psycopg://user:pass@localhost:5432/remind"

# Via CLI flag
remind --db "postgresql+psycopg://user:pass@localhost:5432/remind" remember "hello"

# Via config file
{
  "db_url": "postgresql+psycopg://user:pass@localhost:5432/remind"
}
```

Install the appropriate driver extra:

```bash
pip install "remind-mcp[postgres]"   # PostgreSQL (psycopg)
pip install "remind-mcp[mysql]"      # MySQL (PyMySQL)
```

## Memory decay

Concepts that are rarely recalled gradually lose retrieval priority, mimicking how human memory fades.

| Option | Default | Description |
|--------|---------|-------------|
| `decay.enabled` | `true` | Set `false` to disable |
| `decay.decay_interval` | `20` | Recalls between decay passes |
| `decay.decay_rate` | `0.1` | How much `decay_factor` drops per interval (0.0-1.0) |

When a concept is recalled, it gets **rejuvenated** — its decay factor gets a boost proportional to match strength. Recently recalled concepts are protected by a 60-second grace window.

View decay stats with `remind stats`.

## Consolidation

| Option | Default | Description |
|--------|---------|-------------|
| `consolidation_threshold` | `5` | Episodes before auto-consolidation triggers |
| `concepts_per_pass` | `64` | Max concepts included per consolidation LLM pass |
| `auto_consolidate` | `true` | Whether to auto-consolidate after `remember` |
| `extraction_batch_size` | `50` | Episodes fetched per extraction loop pass (independent of consolidation batch size) |
| `extraction_llm_batch_size` | `10` | Episodes grouped into each extraction LLM call |
| `consolidation_batch_size` | `25` | Episodes fetched and generalized per consolidation loop pass |
| `llm_concurrency` | `3` | Max concurrent LLM calls across extraction + consolidation; also bounds topic-group parallelism |

Legacy aliases remain supported: `consolidation_concepts_per_pass`, `entity_extraction_batch_size`, and `consolidation_llm_concurrency`.

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

## Episode types

Control which episode types are available. This affects which CLI commands and MCP tools are registered.

| Option | Default | Description |
|--------|---------|-------------|
| `episode_types` | all built-in types | List of enabled episode types |

Built-in types: `observation`, `decision`, `question`, `meta`, `preference`, `spec`, `plan`, `task`, `outcome`, `fact`.

By default all types are enabled. To restrict to a subset:

```json
{
  "episode_types": ["observation", "decision", "question", "outcome", "fact"]
}
```

Or via environment variable (comma-separated):

```bash
REMIND_EPISODE_TYPES=observation,decision,question,outcome,fact
```

Custom type names are also accepted — they will be used in LLM prompts for triage and extraction with generic descriptions.

### Feature gating

When `spec`, `plan`, or `task` types are excluded from `episode_types`:

- **CLI**: The corresponding commands (`specs`, `plans`, `tasks`, `task add/start/done/block/unblock`) are hidden from `remind --help` and unavailable
- **MCP**: The corresponding tools (`list_specs`, `list_plans`, `task_add`, `task_update_status`, `list_tasks`) are not registered and won't appear in the tool list

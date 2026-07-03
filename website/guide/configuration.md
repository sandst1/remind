# Configuration

Remind is configured via config files, environment variables, or CLI arguments. Settings resolve with this priority (highest first):

1. CLI arguments (`--embedding`)
2. Environment variables
3. Project-local config file (`<project>/.remind/remind.config.json`)
4. Global config file (`~/.remind/remind.config.json`)
5. Defaults

## Config files

### Global config

Create `~/.remind/remind.config.json`:

```json
{
  "embedding_provider": "local",

  "openai": {
    "api_key": "sk-...",
    "embedding_model": "text-embedding-3-small"
  },

  "azure_openai": {
    "api_key": "...",
    "base_url": "https://your-resource.openai.azure.com",
    "embedding_deployment_name": "text-embedding-3-small",
    "embedding_size": 1536
  },

  "ollama": {
    "url": "http://localhost:11434",
    "embedding_model": "nomic-embed-text"
  },

  "local": {
    "embedding_model": "sentence-transformers/all-MiniLM-L6-v2"
  },

  "decay": {
    "enabled": true,
    "decay_interval": 20,
    "decay_rate": 0.1
  },

  "hybrid_keyword_weight": 0.3,

  "fact_cluster_jaccard_threshold": 0.5,

  "db_url": null,

  "logging_enabled": false,

  "cli_output_mode": "table",

  "episode_types": ["observation", "decision", "question", "meta", "preference",
                     "outcome", "fact"]
}
```

You only need to include settings you want to change from defaults. A minimal config uses local embeddings (no API keys):

```json
{}
```

Or for OpenAI embeddings:

```json
{
  "embedding_provider": "openai",
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

A typical use case is selecting a different embedding provider for a specific project:

```json
{
  "embedding_provider": "ollama",
  "ollama": { "embedding_model": "mxbai-embed-large" }
}
```

The CLI automatically reads `<cwd>/.remind/remind.config.json`. When using the Python API, pass `project_dir` to `create_memory()` to enable project-local config loading.

::: warning Do not commit secrets
If your project-local config contains API keys or other secrets, make sure `.remind/` is in your `.gitignore`. Better yet, keep secrets in the global config (`~/.remind/remind.config.json`) or in environment variables, and use the project-local file only for non-sensitive settings like provider choice and model selection.
:::

### CLI output mode

`cli_output_mode` sets the default for browse/list commands (`status`, `topics`, etc.): `table` (human-readable, default), `json` (full structured stdout), or `compact-json` (minimal objects).

- Per command: `--json`, `--compact-json`, or `--table`
- Environment: `REMIND_CLI_OUTPUT_MODE=table`, `json`, or `compact-json`

## Environment variables

Every config-file setting has a corresponding environment variable. Environment variables take precedence over both config files.

### Complete reference

#### General

| Env variable | Config field | Type | Default |
|---|---|---|---|
| `EMBEDDING_PROVIDER` | `embedding_provider` | string | `local` |
| `REMIND_HYBRID_KEYWORD_WEIGHT` | `hybrid_keyword_weight` | float | `0.3` |
| `REMIND_RECALL_INITIAL_CANDIDATES` | `recall_initial_candidates` | int | `10` |
| `REMIND_RERANKING_ENABLED` | `reranking_enabled` | bool | `false` |
| `REMIND_RERANKING_MODEL` | `reranking_model` | string | `cross-encoder/ms-marco-MiniLM-L-6-v2` |
| `REMIND_FACT_CLUSTER_JACCARD_THRESHOLD` | `fact_cluster_jaccard_threshold` | float | `0.5` |
| `REMIND_DB_URL` | `db_url` | string | `null` (SQLite default) |
| `REMIND_LOGGING_ENABLED` | `logging_enabled` | bool | `false` |
| `REMIND_CLI_OUTPUT_MODE` | `cli_output_mode` | string | `table` |
| `REMIND_EPISODE_TYPES` | `episode_types` | comma-separated list | all built-in types |

#### Local embeddings (default)

| Env variable | Config field | Type | Default |
|---|---|---|---|
| `LOCAL_EMBEDDING_MODEL` | `local.embedding_model` | string | `sentence-transformers/all-MiniLM-L6-v2` |

No API keys needed. Uses fastembed with ONNX for fast local inference.

#### OpenAI

| Env variable | Config field | Type | Default |
|---|---|---|---|
| `OPENAI_API_KEY` | `openai.api_key` | string | — |
| `OPENAI_BASE_URL` | `openai.base_url` | string | — |
| `OPENAI_EMBEDDING_MODEL` | `openai.embedding_model` | string | `text-embedding-3-small` |

#### Azure OpenAI

| Env variable | Config field | Type | Default |
|---|---|---|---|
| `AZURE_OPENAI_API_KEY` | `azure_openai.api_key` | string | — |
| `AZURE_OPENAI_API_BASE_URL` | `azure_openai.base_url` | string | — |
| `AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME` | `azure_openai.embedding_deployment_name` | string | — |
| `AZURE_OPENAI_EMBEDDING_SIZE` | `azure_openai.embedding_size` | int | `1536` |

#### Ollama (local)

| Env variable | Config field | Type | Default |
|---|---|---|---|
| `OLLAMA_URL` | `ollama.url` | string | `http://localhost:11434` |
| `OLLAMA_EMBEDDING_MODEL` | `ollama.embedding_model` | string | `nomic-embed-text` |

No API keys needed. Install [Ollama](https://ollama.ai/) and pull an embedding model:

```bash
ollama pull nomic-embed-text
```

#### Memory decay

| Env variable | Config field | Type | Default |
|---|---|---|---|
| `REMIND_DECAY_ENABLED` | `decay.enabled` | bool | `true` |
| `REMIND_DECAY_INTERVAL` | `decay.decay_interval` | int | `20` |
| `REMIND_DECAY_RATE` | `decay.decay_rate` | float | `0.1` |

Boolean env vars accept `true`, `1`, `yes` (case-insensitive) as truthy values; anything else is falsy.

### Quick-start examples

**Local embeddings (default, no API keys):**

```bash
# Nothing needed — works out of the box
remind remember "Hello world"
```

**OpenAI embeddings:**

```bash
export OPENAI_API_KEY=sk-...
export EMBEDDING_PROVIDER=openai
```

**Azure OpenAI:**

```bash
export AZURE_OPENAI_API_KEY=...
export AZURE_OPENAI_API_BASE_URL=https://your-resource.openai.azure.com
export AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME=text-embedding-3-small
export EMBEDDING_PROVIDER=azure_openai
```

**Ollama (fully local):**

```bash
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
pip install "remind-mcp[postgres]"   # PostgreSQL (psycopg + pgvector)
pip install "remind-mcp[mysql]"      # MySQL (PyMySQL)
```

### Vector search

Remind uses native vector indexes for embedding search when available:

- **SQLite**: [sqlite-vec](https://github.com/asg017/sqlite-vec) is pulled in as a dependency.
- **PostgreSQL**: The Python driver is included with `remind-mcp[postgres]`.
- **Fallback**: If native indexes are unavailable, Remind uses brute-force NumPy cosine similarity.

Vector tables are created lazily when the first embedding is written.

#### SQLite: when sqlite-vec is not used

sqlite-vec is a **loadable extension**. Some Python builds (especially on macOS) don't support extension loading. Remind falls back to brute-force search in that case.

**Check your interpreter:**

```bash
python -c "import sqlite3; c=sqlite3.connect(':memory:'); print('load_extension:', hasattr(c, 'enable_load_extension'))"
```

See [Retrieval — Vector indexes](/concepts/retrieval#vector-indexes) for details.

## Memory decay

Concepts that are rarely recalled gradually lose retrieval priority.

| Option | Default | Description |
|--------|---------|-------------|
| `decay.enabled` | `true` | Set `false` to disable |
| `decay.decay_interval` | `20` | Recalls between decay passes |
| `decay.decay_rate` | `0.1` | How much `decay_factor` drops per interval (0.0-1.0) |

When a concept is recalled, it gets **rejuvenated** — its decay factor gets a boost proportional to match strength.

View decay stats with `remind stats`.

## Fact clustering

| Option | Default | Description |
|--------|---------|-------------|
| `fact_cluster_jaccard_threshold` | `0.5` | Min Jaccard similarity between entity sets to cluster facts together |

Lower values create larger clusters (more facts grouped together). Higher values create more focused clusters (facts need more entity overlap).

## Retrieval tuning

| Option | Default | Description |
|--------|---------|-------------|
| `hybrid_keyword_weight` | `0.3` | Blend between embedding similarity and keyword overlap. `0.0` = pure embedding, `1.0` = pure keyword. |
| `recall_initial_candidates` | `10` | How many initial embedding candidates to fetch before spreading activation and reranking. |

The default `0.3` keyword weight means 70% embedding similarity + 30% keyword overlap. See [Retrieval](/concepts/retrieval) for details.

## Reranking

Cross-encoder reranking rescores retrieval candidates. Disabled by default — requires the `rerank` extra.

```bash
pip install "remind-mcp[rerank]"
```

| Option | Default | Description |
|--------|---------|-------------|
| `reranking_enabled` | `false` | Enable cross-encoder reranking |
| `reranking_model` | `cross-encoder/ms-marco-MiniLM-L-6-v2` | Which model to use |

Enable via config:

```json
{
  "reranking_enabled": true,
  "recall_initial_candidates": 15
}
```

## Logging

When enabled, Remind writes debug logs to `remind.log` in the same directory as the database.

| Option | Default | Description |
|--------|---------|-------------|
| `logging_enabled` | `false` | Write debug logs |

## Episode types

Control which episode types are valid.

| Option | Default | Description |
|--------|---------|-------------|
| `episode_types` | all built-in types | List of enabled episode types |

Built-in types: `observation`, `decision`, `question`, `meta`, `preference`, `outcome`, `fact`.

To restrict to a subset:

```json
{
  "episode_types": ["observation", "decision", "fact"]
}
```

Or via environment variable (comma-separated):

```bash
REMIND_EPISODE_TYPES=observation,decision,fact
```

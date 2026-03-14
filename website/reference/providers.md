# Providers

Remind supports multiple LLM and embedding providers. You need one of each — an LLM for consolidation and an embedding provider for retrieval.

## Provider matrix

| Provider | LLM | Embeddings | API key required |
|----------|-----|------------|-----------------|
| Anthropic | Yes | No | Yes |
| OpenAI | Yes | Yes | Yes |
| Azure OpenAI | Yes | Yes | Yes |
| Ollama | Yes | Yes | No (local) |

## Anthropic

LLM only. Pair with OpenAI or Ollama for embeddings.

::: code-group

```json [Config file]
{
  "llm_provider": "anthropic",
  "embedding_provider": "openai",
  "anthropic": {
    "api_key": "sk-ant-...",
    "model": "claude-sonnet-4-20250514"
  }
}
```

```bash [Environment]
ANTHROPIC_API_KEY=sk-ant-...
LLM_PROVIDER=anthropic
EMBEDDING_PROVIDER=openai
```

:::

| Setting | Default |
|---------|---------|
| `api_key` | — |
| `model` | `claude-sonnet-4-20250514` |

## OpenAI

LLM and embeddings.

::: code-group

```json [Config file]
{
  "llm_provider": "openai",
  "embedding_provider": "openai",
  "openai": {
    "api_key": "sk-...",
    "model": "gpt-4.1",
    "embedding_model": "text-embedding-3-small"
  }
}
```

```bash [Environment]
OPENAI_API_KEY=sk-...
LLM_PROVIDER=openai
EMBEDDING_PROVIDER=openai
```

:::

| Setting | Default |
|---------|---------|
| `api_key` | — |
| `base_url` | `null` (OpenAI default) |
| `model` | `gpt-4.1` |
| `embedding_model` | `text-embedding-3-small` |

## Azure OpenAI

LLM and embeddings via Azure.

::: code-group

```json [Config file]
{
  "llm_provider": "azure_openai",
  "embedding_provider": "azure_openai",
  "azure_openai": {
    "api_key": "...",
    "base_url": "https://your-resource.openai.azure.com",
    "api_version": "2024-02-15-preview",
    "deployment_name": "gpt-4",
    "embedding_deployment_name": "text-embedding-3-small",
    "embedding_size": 1536
  }
}
```

```bash [Environment]
AZURE_OPENAI_API_KEY=...
AZURE_OPENAI_API_BASE_URL=https://your-resource.openai.azure.com
AZURE_OPENAI_API_VERSION=2024-02-15-preview
AZURE_OPENAI_DEPLOYMENT_NAME=gpt-4
AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME=text-embedding-3-small
LLM_PROVIDER=azure_openai
EMBEDDING_PROVIDER=azure_openai
```

:::

| Setting | Default |
|---------|---------|
| `api_key` | — |
| `base_url` | — |
| `api_version` | — |
| `deployment_name` | — |
| `embedding_deployment_name` | — |
| `embedding_size` | `1536` |

## Ollama (local)

Fully local, no API keys. Install [Ollama](https://ollama.ai/) first:

```bash
ollama pull llama3.2           # LLM
ollama pull nomic-embed-text   # Embeddings
```

::: code-group

```json [Config file]
{
  "llm_provider": "ollama",
  "embedding_provider": "ollama",
  "ollama": {
    "url": "http://localhost:11434",
    "llm_model": "llama3.2",
    "embedding_model": "nomic-embed-text"
  }
}
```

```bash [Environment]
OLLAMA_URL=http://localhost:11434
OLLAMA_LLM_MODEL=llama3.2
OLLAMA_EMBEDDING_MODEL=nomic-embed-text
LLM_PROVIDER=ollama
EMBEDDING_PROVIDER=ollama
```

:::

| Setting | Default |
|---------|---------|
| `url` | `http://localhost:11434` |
| `llm_model` | `llama3.2` |
| `embedding_model` | `nomic-embed-text` |

## Mixing providers

You can use different providers for LLM and embeddings:

```json
{
  "llm_provider": "anthropic",
  "embedding_provider": "openai"
}
```

Common combos:
- **Anthropic LLM + OpenAI embeddings** — Best consolidation quality + fast embeddings
- **OpenAI for both** — Simplest setup, single API key
- **Ollama for both** — Fully local, no API keys, no data leaves your machine
- **Anthropic LLM + Ollama embeddings** — Quality consolidation, local embeddings

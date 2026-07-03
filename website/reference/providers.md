# Providers

Remind uses embedding providers for semantic retrieval. By default, it uses **local embeddings** — no API keys needed.

## Provider matrix

| Provider | Embeddings | API key required |
|----------|------------|------------------|
| Local | Yes (default) | No |
| OpenAI | Yes | Yes |
| Azure OpenAI | Yes | Yes |
| Ollama | Yes | No (local server) |

## Local (default)

Uses [fastembed](https://github.com/qdrant/fastembed) with ONNX for fast local inference. No API keys or external calls.

::: code-group

```json [Config file]
{
  "embedding_provider": "local",
  "local": {
    "embedding_model": "sentence-transformers/all-MiniLM-L6-v2"
  }
}
```

```bash [Environment]
EMBEDDING_PROVIDER=local
LOCAL_EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
```

:::

| Setting | Default |
|---------|---------|
| `embedding_model` | `sentence-transformers/all-MiniLM-L6-v2` |

This is the default — no configuration needed to use it.

## OpenAI

Higher-quality embeddings via OpenAI API.

::: code-group

```json [Config file]
{
  "embedding_provider": "openai",
  "openai": {
    "api_key": "sk-...",
    "embedding_model": "text-embedding-3-small"
  }
}
```

```bash [Environment]
OPENAI_API_KEY=sk-...
EMBEDDING_PROVIDER=openai
```

:::

| Setting | Default |
|---------|---------|
| `api_key` | — |
| `base_url` | `null` (OpenAI default) |
| `embedding_model` | `text-embedding-3-small` |

## Azure OpenAI

Embeddings via Azure.

::: code-group

```json [Config file]
{
  "embedding_provider": "azure_openai",
  "azure_openai": {
    "api_key": "...",
    "base_url": "https://your-resource.openai.azure.com",
    "embedding_deployment_name": "text-embedding-3-small",
    "embedding_size": 1536
  }
}
```

```bash [Environment]
AZURE_OPENAI_API_KEY=...
AZURE_OPENAI_API_BASE_URL=https://your-resource.openai.azure.com
AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME=text-embedding-3-small
EMBEDDING_PROVIDER=azure_openai
```

:::

| Setting | Default |
|---------|---------|
| `api_key` | — |
| `base_url` | — (`/openai/v1` appended automatically) |
| `embedding_deployment_name` | — |
| `embedding_size` | `1536` |

## Ollama (local server)

Local embeddings via [Ollama](https://ollama.ai/). Requires Ollama running:

```bash
ollama pull nomic-embed-text
```

::: code-group

```json [Config file]
{
  "embedding_provider": "ollama",
  "ollama": {
    "url": "http://localhost:11434",
    "embedding_model": "nomic-embed-text"
  }
}
```

```bash [Environment]
OLLAMA_URL=http://localhost:11434
OLLAMA_EMBEDDING_MODEL=nomic-embed-text
EMBEDDING_PROVIDER=ollama
```

:::

| Setting | Default |
|---------|---------|
| `url` | `http://localhost:11434` |
| `embedding_model` | `nomic-embed-text` |

## Choosing a provider

| Use case | Recommended |
|----------|-------------|
| Getting started | Local (default) |
| Higher quality retrieval | OpenAI |
| Enterprise / compliance | Azure OpenAI |
| Air-gapped / privacy | Local or Ollama |

The local provider works well for most use cases. Switch to OpenAI or another remote provider if you need higher-quality embeddings for large knowledge bases.

## Switching providers

When switching embedding providers, you'll need to re-embed existing content:

```bash
remind clear-embeddings
remind re-embed --all
```

This is because different providers produce different embedding dimensions and vector spaces.

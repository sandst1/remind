"""Azure OpenAI embedding provider implementation using the v1 API."""

import os
from typing import Optional

from remind.providers.base import EmbeddingProvider


def _normalize_azure_base_url(url: str) -> str:
    """Ensure the base URL ends with /openai/v1."""
    url = url.rstrip("/")
    if not url.endswith("/openai/v1"):
        url = url + "/openai/v1"
    return url


class AzureOpenAIEmbedding(EmbeddingProvider):
    """
    Azure OpenAI embedding provider.

    Uses Azure's OpenAI-compatible v1 API via the standard OpenAI client.
    The base URL should point to your Azure resource, e.g.
    ``https://myresource.openai.azure.com`` (``/openai/v1`` is appended
    automatically if missing).

    Environment variables:
    - AZURE_OPENAI_API_KEY
    - AZURE_OPENAI_API_BASE_URL
    - AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME
    - AZURE_OPENAI_EMBEDDING_SIZE (optional, default 1536)
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        deployment_name: Optional[str] = None,
        dimensions: Optional[int] = None,
    ):
        self._api_key = api_key or os.environ.get("AZURE_OPENAI_API_KEY")
        self._base_url = base_url or os.environ.get("AZURE_OPENAI_API_BASE_URL")
        self.deployment_name = deployment_name or os.environ.get("AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME")

        if not self.deployment_name:
            raise ValueError("AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME environment variable is required")

        dim_env = os.environ.get("AZURE_OPENAI_EMBEDDING_SIZE")
        self._dimensions = dimensions or (int(dim_env) if dim_env else 1536)
        self._client = None

    def _get_client(self):
        """Lazy initialization of the OpenAI client configured for Azure."""
        if self._client is None:
            try:
                from openai import AsyncOpenAI
                self._client = AsyncOpenAI(
                    api_key=self._api_key,
                    base_url=_normalize_azure_base_url(self._base_url),
                    default_headers={"api-key": self._api_key},
                )
            except ImportError:
                raise ImportError(
                    "openai package is required. Install with: pip install openai"
                )
        return self._client

    async def embed(self, text: str) -> list[float]:
        """Generate an embedding for a single text."""
        client = self._get_client()

        kwargs: dict = {"model": self.deployment_name, "input": text}
        if self._dimensions:
            kwargs["dimensions"] = self._dimensions

        response = await client.embeddings.create(**kwargs)

        return response.data[0].embedding

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts."""
        if not texts:
            return []

        client = self._get_client()

        kwargs: dict = {"model": self.deployment_name, "input": texts}
        if self._dimensions:
            kwargs["dimensions"] = self._dimensions

        response = await client.embeddings.create(**kwargs)

        sorted_embeddings = sorted(response.data, key=lambda x: x.index)
        return [e.embedding for e in sorted_embeddings]

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None

    @property
    def dimensions(self) -> int:
        return self._dimensions

    @property
    def name(self) -> str:
        return f"azure-openai/{self.deployment_name}"

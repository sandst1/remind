"""OpenAI embedding provider implementation."""

import os
from typing import Optional

from remind.providers.base import EmbeddingProvider


class OpenAIEmbedding(EmbeddingProvider):
    """
    OpenAI embedding provider.

    Uses text-embedding-3-small by default with 1536 dimensions.
    For text-embedding-3-large, dimensions defaults to 1536 (truncated from
    the native 3072) for pgvector HNSW compatibility and storage efficiency
    with minimal quality loss.

    Set OPENAI_API_KEY environment variable for authentication.
    """

    DEFAULT_DIMENSIONS = 1536

    def __init__(
        self,
        model: str = "text-embedding-3-small",
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        dimensions: Optional[int] = None,
    ):
        self.model = model
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self._base_url = base_url
        self._client = None
        self._dimensions = dimensions or self.DEFAULT_DIMENSIONS

    def _get_client(self):
        """Lazy initialization of the OpenAI client."""
        if self._client is None:
            try:
                import openai
                kwargs = {"api_key": self._api_key}
                if self._base_url:
                    kwargs["base_url"] = self._base_url
                self._client = openai.AsyncOpenAI(**kwargs)
            except ImportError:
                raise ImportError(
                    "openai package is required. Install with: pip install openai"
                )
        return self._client

    async def embed(self, text: str) -> list[float]:
        """Generate an embedding for a single text."""
        client = self._get_client()

        response = await client.embeddings.create(
            model=self.model,
            input=text,
            dimensions=self._dimensions,
        )

        return response.data[0].embedding

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts."""
        if not texts:
            return []

        client = self._get_client()

        response = await client.embeddings.create(
            model=self.model,
            input=texts,
            dimensions=self._dimensions,
        )

        # Sort by index to maintain order
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
        return f"openai/{self.model}"


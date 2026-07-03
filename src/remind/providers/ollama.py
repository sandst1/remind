"""Ollama embedding provider implementation for local models."""

import os
from typing import Optional

from remind.providers.base import EmbeddingProvider


class OllamaEmbedding(EmbeddingProvider):
    """
    Ollama embedding provider for local embedding models.
    
    Requires Ollama to be running with an embedding-capable model.
    Common choices: nomic-embed-text, mxbai-embed-large
    """
    
    # Approximate dimensions for common models
    MODEL_DIMENSIONS = {
        "nomic-embed-text": 768,
        "mxbai-embed-large": 1024,
        "all-minilm": 384,
        "snowflake-arctic-embed": 1024,
    }
    
    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
        timeout: float = 60.0,
    ):
        self.model = model or os.environ.get("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text")
        self.base_url = (base_url or os.environ.get("OLLAMA_URL", "http://localhost:11434")).rstrip("/")
        self.timeout = timeout
        self._dimensions = self.MODEL_DIMENSIONS.get(self.model, 768)
        self._actual_dimensions: Optional[int] = None
    
    async def embed(self, text: str) -> list[float]:
        """Generate an embedding for a single text."""
        try:
            import httpx
        except ImportError:
            raise ImportError(
                'httpx package is required for Ollama. Install with: pip install "remind-mcp[ollama]"'
            )
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/api/embeddings",
                json={
                    "model": self.model,
                    "prompt": text,
                },
            )
            response.raise_for_status()
            
            embedding = response.json()["embedding"]
            
            # Update actual dimensions if different
            if self._actual_dimensions is None:
                self._actual_dimensions = len(embedding)
            
            return embedding
    
    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts."""
        if not texts:
            return []
        
        try:
            import httpx
        except ImportError:
            raise ImportError(
                'httpx package is required for Ollama. Install with: pip install "remind-mcp[ollama]"'
            )
        
        # Ollama doesn't have native batch embedding, so we do it sequentially
        # Could be parallelized with asyncio.gather for better performance
        embeddings = []
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for text in texts:
                response = await client.post(
                    f"{self.base_url}/api/embeddings",
                    json={
                        "model": self.model,
                        "prompt": text,
                    },
                )
                response.raise_for_status()
                embeddings.append(response.json()["embedding"])
        
        return embeddings
    
    @property
    def dimensions(self) -> int:
        """Return embedding dimensions (actual if known, else estimate)."""
        return self._actual_dimensions or self._dimensions
    
    @property
    def name(self) -> str:
        return f"ollama/{self.model}"


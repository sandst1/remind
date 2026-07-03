"""Abstract base class for embedding providers."""

from abc import ABC, abstractmethod


class EmbeddingProvider(ABC):
    """
    Abstract base class for embedding providers.
    
    Implementations should handle batching, rate limiting,
    and normalization specific to their backend.
    """
    
    async def aclose(self) -> None:
        """Close underlying HTTP clients. Override in subclasses that hold persistent connections."""
        pass

    @abstractmethod
    async def embed(self, text: str) -> list[float]:
        """
        Generate an embedding for a single text.
        
        Args:
            text: The text to embed
            
        Returns:
            The embedding vector as a list of floats
        """
        ...
    
    @abstractmethod
    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """
        Generate embeddings for multiple texts.
        
        Args:
            texts: List of texts to embed
            
        Returns:
            List of embedding vectors
        """
        ...
    
    @property
    @abstractmethod
    def dimensions(self) -> int:
        """Return the embedding dimensions."""
        ...
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Return the provider name."""
        ...


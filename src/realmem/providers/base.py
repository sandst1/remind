"""Abstract base classes for LLM and Embedding providers."""

from abc import ABC, abstractmethod
from typing import Optional


class LLMProvider(ABC):
    """
    Abstract base class for LLM providers.
    
    Implementations should handle authentication, rate limiting,
    and error handling specific to their backend.
    """
    
    @abstractmethod
    async def complete(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> str:
        """
        Generate a completion for the given prompt.
        
        Args:
            prompt: The user prompt/message
            system: Optional system message for context
            temperature: Sampling temperature (0.0 = deterministic, 1.0 = creative)
            max_tokens: Maximum tokens in response
            
        Returns:
            The generated text response
        """
        ...
    
    @abstractmethod
    async def complete_json(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> dict:
        """
        Generate a completion expecting JSON output.
        
        Args:
            prompt: The user prompt/message (should request JSON)
            system: Optional system message for context
            temperature: Sampling temperature (lower is better for structured output)
            max_tokens: Maximum tokens in response
            
        Returns:
            Parsed JSON as a dictionary
        """
        ...
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Return the provider name."""
        ...


class EmbeddingProvider(ABC):
    """
    Abstract base class for embedding providers.
    
    Implementations should handle batching, rate limiting,
    and normalization specific to their backend.
    """
    
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


"""Ollama provider implementation for local LLMs."""

import json
import os
import re
from typing import Optional

import httpx

from remind.providers.base import LLMProvider, EmbeddingProvider


class OllamaLLM(LLMProvider):
    """
    Ollama LLM provider for local models.
    
    Requires Ollama to be running locally (default: http://localhost:11434).
    """
    
    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
        timeout: float = 120.0,
    ):
        self.model = model or os.environ.get("OLLAMA_LLM_MODEL", "llama3.2")
        self.base_url = (base_url or os.environ.get("OLLAMA_URL", "http://localhost:11434")).rstrip("/")
        self.timeout = timeout
    
    async def complete(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> str:
        """Generate a completion using Ollama."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            payload = {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": temperature,
                    "num_predict": max_tokens,
                },
            }
            
            if system:
                payload["system"] = system
            
            response = await client.post(
                f"{self.base_url}/api/generate",
                json=payload,
            )
            response.raise_for_status()
            
            return response.json()["response"]
    
    async def complete_json(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> dict:
        """Generate a JSON completion using Ollama."""
        # Add JSON instruction to system prompt
        json_system = (system or "") + "\n\nYou must respond with valid JSON only. No markdown, no explanation, just the JSON object."
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            payload = {
                "model": self.model,
                "prompt": prompt,
                "system": json_system.strip(),
                "stream": False,
                "format": "json",  # Ollama's JSON mode
                "options": {
                    "temperature": temperature,
                    "num_predict": max_tokens,
                },
            }
            
            response = await client.post(
                f"{self.base_url}/api/generate",
                json=payload,
            )
            response.raise_for_status()
            
            text = response.json()["response"].strip()
            
            # Remove markdown code blocks if present
            if text.startswith("```"):
                text = re.sub(r'^```(?:json)?\s*', '', text)
                text = re.sub(r'\s*```$', '', text)
            
            return json.loads(text)
    
    @property
    def name(self) -> str:
        return f"ollama/{self.model}"


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


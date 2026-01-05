"""OpenAI provider implementation."""

import os
import json
import re
from typing import Optional, AsyncIterator

from remind.providers.base import LLMProvider, EmbeddingProvider, ChatMessage


class OpenAILLM(LLMProvider):
    """
    OpenAI GPT LLM provider.
    
    Uses the OpenAI Python SDK for completions.
    Set OPENAI_API_KEY environment variable for authentication.
    """
    
    def __init__(
        self,
        model: str = "gpt-4.1",
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        self.model = model
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self._base_url = base_url
        self._client = None
    
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
    
    async def complete(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> str:
        """Generate a completion using GPT."""
        client = self._get_client()
        
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        
        response = await client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_completion_tokens=max_tokens,
        )
        
        return response.choices[0].message.content
    
    async def complete_json(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> dict:
        """Generate a JSON completion using GPT."""
        client = self._get_client()
        
        # Add JSON instruction to system prompt
        json_system = (system or "") + "\n\nYou must respond with valid JSON only."
        
        messages = [
            {"role": "system", "content": json_system.strip()},
            {"role": "user", "content": prompt},
        ]
        
        response = await client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_completion_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        
        text = response.choices[0].message.content.strip()
        
        # Remove markdown code blocks if present (shouldn't happen with json_object mode)
        if text.startswith("```"):
            text = re.sub(r'^```(?:json)?\s*', '', text)
            text = re.sub(r'\s*```$', '', text)
        
        return json.loads(text)
    
    @property
    def name(self) -> str:
        return f"openai/{self.model}"

    async def complete_stream(
        self,
        messages: list[ChatMessage],
        system: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]:
        """Generate a streaming completion using GPT."""
        client = self._get_client()

        # Build messages list
        openai_messages = []
        if system:
            openai_messages.append({"role": "system", "content": system})

        for msg in messages:
            openai_messages.append({"role": msg["role"], "content": msg["content"]})

        stream = await client.chat.completions.create(
            model=self.model,
            messages=openai_messages,
            temperature=temperature,
            max_completion_tokens=max_tokens,
            stream=True,
        )

        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content


class OpenAIEmbedding(EmbeddingProvider):
    """
    OpenAI embedding provider.
    
    Uses text-embedding-3-small by default (1536 dimensions).
    Set OPENAI_API_KEY environment variable for authentication.
    """
    
    # Dimension sizes for different models
    MODEL_DIMENSIONS = {
        "text-embedding-3-small": 1536,
        "text-embedding-3-large": 3072,
        "text-embedding-ada-002": 1536,
    }
    
    def __init__(
        self,
        model: str = "text-embedding-3-large",
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        self.model = model
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self._base_url = base_url
        self._client = None
        self._dimensions = self.MODEL_DIMENSIONS.get(model, 1536)
    
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
        )
        
        # Sort by index to maintain order
        sorted_embeddings = sorted(response.data, key=lambda x: x.index)
        return [e.embedding for e in sorted_embeddings]
    
    @property
    def dimensions(self) -> int:
        return self._dimensions
    
    @property
    def name(self) -> str:
        return f"openai/{self.model}"


"""Anthropic (Claude) provider implementation."""

import os
import json
import re
from typing import Optional, AsyncIterator

from remind.providers.base import LLMProvider, EmbeddingProvider, ChatMessage


class AnthropicLLM(LLMProvider):
    """
    Anthropic Claude LLM provider.
    
    Uses the Anthropic Python SDK for completions.
    Set ANTHROPIC_API_KEY environment variable for authentication.
    """
    
    def __init__(
        self,
        model: str = "claude-sonnet-4-20250514",
        api_key: Optional[str] = None,
    ):
        self.model = model
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self._client = None
    
    def _get_client(self):
        """Lazy initialization of the Anthropic client."""
        if self._client is None:
            try:
                import anthropic
                self._client = anthropic.AsyncAnthropic(api_key=self._api_key)
            except ImportError:
                raise ImportError(
                    "anthropic package is required. Install with: pip install anthropic"
                )
        return self._client
    
    async def complete(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> str:
        """Generate a completion using Claude."""
        client = self._get_client()
        
        kwargs = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
        }
        
        if system:
            kwargs["system"] = system
        
        response = await client.messages.create(**kwargs)
        return response.content[0].text
    
    async def complete_json(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> dict:
        """Generate a JSON completion using Claude."""
        # Add JSON instruction to system prompt
        json_system = (system or "") + "\n\nYou must respond with valid JSON only. No markdown, no explanation, just the JSON object."
        
        response = await self.complete(
            prompt=prompt,
            system=json_system.strip(),
            temperature=temperature,
            max_tokens=max_tokens,
        )
        
        # Try to parse, handling potential markdown code blocks
        text = response.strip()
        
        # Remove markdown code blocks if present
        if text.startswith("```"):
            # Remove opening ```json or ```
            text = re.sub(r'^```(?:json)?\s*', '', text)
            # Remove closing ```
            text = re.sub(r'\s*```$', '', text)
        
        return json.loads(text)
    
    @property
    def name(self) -> str:
        return f"anthropic/{self.model}"

    async def complete_stream(
        self,
        messages: list[ChatMessage],
        system: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]:
        """Generate a streaming completion using Claude."""
        client = self._get_client()

        # Convert messages to Anthropic format
        anthropic_messages = [
            {"role": msg["role"], "content": msg["content"]}
            for msg in messages
        ]

        kwargs = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": anthropic_messages,
        }

        if system:
            kwargs["system"] = system

        async with client.messages.stream(**kwargs) as stream:
            async for text in stream.text_stream:
                yield text


class AnthropicEmbedding(EmbeddingProvider):
    """
    Anthropic doesn't provide embedding models directly.
    This is a placeholder that raises an error directing users to use
    a different embedding provider.
    """
    
    def __init__(self):
        raise NotImplementedError(
            "Anthropic doesn't provide embedding models. "
            "Use OpenAIEmbedding or OllamaEmbedding instead."
        )
    
    async def embed(self, text: str) -> list[float]:
        raise NotImplementedError()
    
    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError()
    
    @property
    def dimensions(self) -> int:
        raise NotImplementedError()
    
    @property
    def name(self) -> str:
        return "anthropic/none"


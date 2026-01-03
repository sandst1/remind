"""Azure OpenAI provider implementation."""

import os
import json
import re
from typing import Optional

from remind.providers.base import LLMProvider, EmbeddingProvider


class AzureOpenAILLM(LLMProvider):
    """
    Azure OpenAI LLM provider.
    
    Uses the Azure OpenAI service via the OpenAI Python SDK.
    Requires the following environment variables:
    - AZURE_OPENAI_API_KEY
    - AZURE_OPENAI_API_BASE_URL
    - AZURE_OPENAI_API_VERSION
    - AZURE_OPENAI_DEPLOYMENT_NAME
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        api_version: Optional[str] = None,
        deployment_name: Optional[str] = None,
    ):
        self._api_key = api_key or os.environ.get("AZURE_OPENAI_API_KEY")
        self._base_url = base_url or os.environ.get("AZURE_OPENAI_API_BASE_URL")
        self._api_version = api_version or os.environ.get("AZURE_OPENAI_API_VERSION")
        self.deployment_name = deployment_name or os.environ.get("AZURE_OPENAI_DEPLOYMENT_NAME")
        
        if not self.deployment_name:
            raise ValueError("AZURE_OPENAI_DEPLOYMENT_NAME environment variable is required")
            
        self._client = None
    
    def _get_client(self):
        """Lazy initialization of the Azure OpenAI client."""
        if self._client is None:
            try:
                from openai import AsyncAzureOpenAI
                self._client = AsyncAzureOpenAI(
                    api_key=self._api_key,
                    azure_endpoint=self._base_url,
                    api_version=self._api_version,
                )
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
        """Generate a completion using Azure OpenAI."""
        client = self._get_client()
        
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        
        response = await client.chat.completions.create(
            model=self.deployment_name,
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
        """Generate a JSON completion using Azure OpenAI."""
        client = self._get_client()
        
        # Add JSON instruction to system prompt
        json_system = (system or "") + "\n\nYou must respond with valid JSON only."
        
        messages = [
            {"role": "system", "content": json_system.strip()},
            {"role": "user", "content": prompt},
        ]
        
        response = await client.chat.completions.create(
            model=self.deployment_name,
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
        return f"azure-openai/{self.deployment_name}"


class AzureOpenAIEmbedding(EmbeddingProvider):
    """
    Azure OpenAI embedding provider.
    
    Requires the following environment variables:
    - AZURE_OPENAI_API_KEY
    - AZURE_OPENAI_API_BASE_URL
    - AZURE_OPENAI_API_VERSION
    - AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME
    - AZURE_OPENAI_EMBEDDING_SIZE (optional, default 1536)
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        api_version: Optional[str] = None,
        deployment_name: Optional[str] = None,
        dimensions: Optional[int] = None,
    ):
        self._api_key = api_key or os.environ.get("AZURE_OPENAI_API_KEY")
        self._base_url = base_url or os.environ.get("AZURE_OPENAI_API_BASE_URL")
        self._api_version = api_version or os.environ.get("AZURE_OPENAI_API_VERSION")
        self.deployment_name = deployment_name or os.environ.get("AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME")
        
        if not self.deployment_name:
            raise ValueError("AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME environment variable is required")
            
        dim_env = os.environ.get("AZURE_OPENAI_EMBEDDING_SIZE")
        self._dimensions = dimensions or (int(dim_env) if dim_env else 1536)
        self._client = None
    
    def _get_client(self):
        """Lazy initialization of the Azure OpenAI client."""
        if self._client is None:
            try:
                from openai import AsyncAzureOpenAI
                self._client = AsyncAzureOpenAI(
                    api_key=self._api_key,
                    azure_endpoint=self._base_url,
                    api_version=self._api_version,
                )
            except ImportError:
                raise ImportError(
                    "openai package is required. Install with: pip install openai"
                )
        return self._client
    
    async def embed(self, text: str) -> list[float]:
        """Generate an embedding for a single text."""
        client = self._get_client()
        
        response = await client.embeddings.create(
            model=self.deployment_name,
            input=text,
        )
        
        return response.data[0].embedding
    
    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts."""
        if not texts:
            return []
        
        client = self._get_client()
        
        response = await client.embeddings.create(
            model=self.deployment_name,
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
        return f"azure-openai/{self.deployment_name}"


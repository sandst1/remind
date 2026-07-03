"""Embedding providers."""

from remind.providers.base import EmbeddingProvider
from remind.providers.local import LocalEmbedding
from remind.providers.openai import OpenAIEmbedding
from remind.providers.ollama import OllamaEmbedding
from remind.providers.azure_openai import AzureOpenAIEmbedding

__all__ = [
    "EmbeddingProvider",
    "LocalEmbedding",
    "OpenAIEmbedding",
    "OllamaEmbedding",
    "AzureOpenAIEmbedding",
]

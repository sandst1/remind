"""Fixed token-hash vectors for offline operational tests, not semantic search."""

import hashlib
import math
import re

from remind.providers.base import EmbeddingProvider


class DeterministicEmbedding(EmbeddingProvider):
    dimensions = 128
    name = "deterministic:token-hash-v1"

    async def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for token in re.findall(r"\w+", text.lower()):
            index = int.from_bytes(hashlib.sha256(token.encode()).digest()[:4], "big") % self.dimensions
            vector[index] += 1.0
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / norm for v in vector]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [await self.embed(text) for text in texts]

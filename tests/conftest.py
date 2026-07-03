"""Shared test fixtures for the Remind test suite."""

import pytest
import tempfile
import os
import hashlib
from typing import Optional

from remind.providers.base import EmbeddingProvider
from remind.store import SQLiteMemoryStore
from remind.models import (
    Episode, Concept, Entity, EntityType, EpisodeType,
    Relation, RelationType,
)


# =============================================================================
# Mock Provider Implementations
# =============================================================================

class MockEmbeddingProvider(EmbeddingProvider):
    """
    Mock embedding provider for testing.

    Generates deterministic embeddings based on text hash.
    """

    def __init__(self, dimensions: int = 128):
        self._dimensions = dimensions
        self._embed_map: dict[str, list[float]] = {}
        self._call_history: list[dict] = []

    def set_embedding(self, text: str, embedding: list[float]) -> None:
        """Set a specific embedding for a text."""
        self._embed_map[text] = embedding

    def get_call_history(self) -> list[dict]:
        """Get history of all calls made to this mock."""
        return self._call_history

    def clear_history(self) -> None:
        """Clear call history."""
        self._call_history = []

    def _generate_deterministic_embedding(self, text: str) -> list[float]:
        """Generate a deterministic embedding from text hash."""
        hash_bytes = hashlib.sha256(text.encode()).digest()
        # Use hash bytes to seed embedding values
        embedding = []
        for i in range(self._dimensions):
            byte_idx = i % len(hash_bytes)
            val = (hash_bytes[byte_idx] - 128) / 128.0  # Normalize to [-1, 1]
            embedding.append(val)
        return embedding

    async def embed(self, text: str) -> list[float]:
        self._call_history.append({
            "method": "embed",
            "text": text,
        })
        if text in self._embed_map:
            return self._embed_map[text]
        return self._generate_deterministic_embedding(text)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        self._call_history.append({
            "method": "embed_batch",
            "texts": texts,
        })
        return [await self.embed(t) for t in texts]

    @property
    def dimensions(self) -> int:
        return self._dimensions

    @property
    def name(self) -> str:
        return "mock/embedding"


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_embedding():
    """Create a mock embedding provider."""
    return MockEmbeddingProvider(dimensions=128)


@pytest.fixture
def temp_db_path():
    """Create a temporary database file path."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.unlink(path)


@pytest.fixture
def memory_store(temp_db_path):
    """Create a temporary SQLite memory store."""
    return SQLiteMemoryStore(temp_db_path)


@pytest.fixture
def sample_episode():
    """Create a sample episode for testing."""
    return Episode(
        content="User prefers Python for backend development",
        metadata={"source": "conversation"},
        confidence=1.0,
    )


@pytest.fixture
def sample_episodes():
    """Create multiple sample episodes for testing."""
    return [
        Episode(
            content="User prefers Python for backend development",
            episode_type=EpisodeType.PREFERENCE,
        ),
        Episode(
            content="User mentioned they work on distributed systems",
            episode_type=EpisodeType.OBSERVATION,
        ),
        Episode(
            content="Decided to use async patterns for the API",
            episode_type=EpisodeType.DECISION,
        ),
        Episode(
            content="What testing framework should be used?",
            episode_type=EpisodeType.QUESTION,
        ),
        Episode(
            content="User values clean, readable code over clever optimizations",
            episode_type=EpisodeType.PREFERENCE,
        ),
    ]


@pytest.fixture
def sample_concept():
    """Create a sample concept for testing."""
    return Concept(
        summary="User prefers Python for backend work and values clean code",
        confidence=0.8,
        tags=["programming", "preferences"],
        embedding=[0.1] * 128,
    )


@pytest.fixture
def sample_concepts_with_relations():
    """Create concepts with relationships for testing spreading activation."""
    c1 = Concept(
        id="concept1",
        summary="User prefers Python for backend development",
        confidence=0.9,
        tags=["programming", "python"],
        embedding=[1.0, 0.0, 0.0] + [0.0] * 125,
    )
    c2 = Concept(
        id="concept2",
        summary="User values type hints and static analysis",
        confidence=0.8,
        tags=["programming", "code-quality"],
        embedding=[0.8, 0.2, 0.0] + [0.0] * 125,
    )
    c3 = Concept(
        id="concept3",
        summary="FastAPI is the preferred web framework",
        confidence=0.7,
        tags=["programming", "web"],
        embedding=[0.6, 0.3, 0.1] + [0.0] * 125,
    )

    # Add relations: c1 implies c2, c2 implies c3
    c1.relations.append(Relation(
        type=RelationType.IMPLIES,
        target_id="concept2",
        strength=0.8,
    ))
    c2.relations.append(Relation(
        type=RelationType.IMPLIES,
        target_id="concept3",
        strength=0.7,
    ))

    return [c1, c2, c3]


@pytest.fixture
def sample_entity():
    """Create a sample entity for testing."""
    return Entity(
        id="file:src/auth.ts",
        type=EntityType.FILE,
        display_name="auth.ts",
    )

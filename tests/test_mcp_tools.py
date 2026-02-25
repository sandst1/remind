"""MCP tool tests for decay management functionality."""

import pytest
import tempfile
import os
from datetime import datetime, timedelta

from remind.providers.base import LLMProvider, EmbeddingProvider
from remind.store import SQLiteMemoryStore
from remind.models import Concept, EpisodeType
from remind.mcp_server import (
    tool_get_decay_stats,
    tool_reset_decay,
    tool_get_recent_accesses,
    get_memory_for_db,
)


# =============================================================================
# Mock Providers
# =============================================================================

class MockLLMProvider(LLMProvider):
    """Mock LLM provider for testing."""

    def __init__(self):
        self._call_history = []

    async def complete(
        self,
        prompt: str,
        system: str = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> str:
        self._call_history.append({
            "method": "complete",
            "prompt": prompt,
        })
        return "Mock response"

    async def complete_json(
        self,
        prompt: str,
        system: str = None,
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> dict:
        self._call_history.append({
            "method": "complete_json",
            "prompt": prompt,
        })
        return {"analysis": "Mock", "updates": [], "new_concepts": [], "new_relations": [], "contradictions": []}

    @property
    def name(self) -> str:
        return "mock/llm"


class MockEmbeddingProvider(EmbeddingProvider):
    """Mock embedding provider for testing."""

    def __init__(self, dimensions: int = 128):
        self._dimensions = dimensions
        self._call_history = []

    async def embed(self, text: str) -> list[float]:
        self._call_history.append({"method": "embed", "text": text})
        return [0.1] * self._dimensions

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        self._call_history.append({"method": "embed_batch", "texts": texts})
        return [[0.1] * self._dimensions for _ in texts]

    @property
    def dimensions(self) -> int:
        return self._dimensions

    @property
    def name(self) -> str:
        return "mock/embedding"


# =============================================================================
# Test Fixtures
# =============================================================================

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
    store = SQLiteMemoryStore(temp_db_path)
    # Add a sample concept for testing
    concept = Concept(
        id="test-concept-1",
        summary="This is a test concept for decay management",
        confidence=0.85,
        access_count=15,
        last_accessed=datetime.now() - timedelta(days=5),
        embedding=[0.1] * 128,
    )
    store.add_concept(concept)
    # Record an access
    store.record_concept_access("test-concept-1", 0.75, "test-query")
    return store


@pytest.fixture
def mock_llm():
    """Create a mock LLM provider."""
    return MockLLMProvider()


@pytest.fixture
def mock_embedding():
    """Create a mock embedding provider."""
    return MockEmbeddingProvider()


# =============================================================================
# MCP Tool Tests
# =============================================================================

class TestGetDecayStats:
    """Tests for get_decay_stats MCP tool."""

    @pytest.mark.asyncio
    async def test_get_decay_stats_success(self, memory_store):
        """Test successful retrieval of decay stats."""
        # Set the db context
        import remind.mcp_server as mcp_server
        mcp_server._current_db.set(memory_store.db_path)
        
        result = await tool_get_decay_stats("test-concept-1")
        
        # Verify result structure
        assert result["success"] is True
        assert result["concept_id"] == "test-concept-1"
        assert "decay_score" in result
        assert "access_count" in result
        assert "last_accessed" in result
        assert "recency_factor" in result
        assert "frequency_factor" in result
        assert "confidence" in result
        
        # Verify values make sense
        assert 0.0 <= result["decay_score"] <= 1.0
        assert result["access_count"] == 15
        assert result["confidence"] == 0.85

    @pytest.mark.asyncio
    async def test_get_decay_stats_not_found(self, memory_store, mock_llm, mock_embedding):
        """Test decay stats for non-existent concept."""
        import remind.mcp_server as mcp_server
        mcp_server._current_db.set(memory_store.db_path)
        
        result = await tool_get_decay_stats("non-existent-id")
        
        assert result["success"] is False
        assert "not found" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_get_decay_stats_no_last_accessed(self, memory_store):
        """Test decay stats when concept has no last_accessed."""
        # Add concept without last_accessed
        concept = Concept(
            id="test-concept-2",
            summary="Concept without recent access",
            confidence=0.7,
            access_count=0,
            embedding=[0.1] * 128,
        )
        memory_store.add_concept(concept)
        
        import remind.mcp_server as mcp_server
        mcp_server._current_db.set(memory_store.db_path)
        
        result = await tool_get_decay_stats("test-concept-2")
        
        assert result["success"] is True
        assert result["access_count"] == 0
        assert result["days_since_access"] is None


class TestResetDecay:
    """Tests for reset_decay MCP tool."""

    @pytest.mark.asyncio
    async def test_reset_decay_success(self, memory_store, mock_llm, mock_embedding):
        """Test successful reset of decay."""
        import remind.mcp_server as mcp_server
        mcp_server._current_db.set(memory_store.db_path)
        
        # Get initial stats
        initial_result = await tool_get_decay_stats("test-concept-1")
        initial_count = initial_result["access_count"]
        
        # Reset decay
        result = await tool_reset_decay("test-concept-1")
        
        # Verify result
        assert result["success"] is True
        assert result["concept_id"] == "test-concept-1"
        assert result["access_count"] == 0
        assert "new_decay_score" in result
        assert result["message"] == "Decay reset successfully"
        
        # Verify in database
        updated_concept = memory_store.get_concept("test-concept-1")
        assert updated_concept.access_count == 0

    @pytest.mark.asyncio
    async def test_reset_decay_not_found(self, memory_store):
        """Test reset decay for non-existent concept."""
        import remind.mcp_server as mcp_server
        mcp_server._current_db.set(memory_store.db_path)
        
        result = await tool_reset_decay("non-existent-id")
        
        assert result["success"] is False
        assert "not found" in result["error"].lower()


class TestGetRecentAccesses:
    """Tests for get_recent_accesses MCP tool."""

    @pytest.mark.asyncio
    async def test_get_recent_accesses_success(self, memory_store, mock_llm, mock_embedding):
        """Test retrieval of recent accesses."""
        import remind.mcp_server as mcp_server
        mcp_server._current_db.set(memory_store.db_path)
        
        result = await tool_get_recent_accesses(limit=10)
        
        # Verify result is a list
        assert isinstance(result, list)
        
        # Verify each entry has required fields
        for entry in result:
            assert "concept_id" in entry
            assert "accessed_at" in entry
            assert "activation_level" in entry

    @pytest.mark.asyncio
    async def test_get_recent_accesses_limit(self, memory_store):
        """Test that limit parameter is respected."""
        import remind.mcp_server as mcp_server
        mcp_server._current_db.set(memory_store.db_path)
        
        result = await tool_get_recent_accesses(limit=5)
        
        assert len(result) <= 5

    @pytest.mark.asyncio
    async def test_get_recent_accesses_empty(self, memory_store):
        """Test when no accesses exist."""
        # Create new store with no accesses
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        store = SQLiteMemoryStore(path)
        
        import remind.mcp_server as mcp_server
        mcp_server._current_db.set(path)
        
        try:
            result = await tool_get_recent_accesses(limit=10)
            assert result == []
        finally:
            if os.path.exists(path):
                os.unlink(path)
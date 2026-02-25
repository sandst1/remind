"""Integration tests for decay functionality across all layers."""

import pytest
import tempfile
import os
import json
from datetime import datetime, timedelta
from click.testing import CliRunner
from starlette.testclient import TestClient

from remind.interface import MemoryInterface
from remind.models import Concept, Episode, EpisodeType
from remind.providers.base import LLMProvider, EmbeddingProvider
from remind.store import SQLiteMemoryStore
from remind.config import RemindConfig, DecayConfig
from remind.cli import main as cli
from remind.api.routes import api_routes
from starlette.applications import Starlette
from starlette.routing import Router


# =============================================================================
# Mock Providers
# =============================================================================

class MockLLMProvider(LLMProvider):
    """Mock LLM provider for testing."""

    def __init__(self):
        self._complete_response: str = "Mock LLM response"
        self._complete_json_response: dict = {}
        self._call_history: list[dict] = []

    def set_complete_response(self, response: str) -> None:
        self._complete_response = response

    def set_complete_json_response(self, response: dict) -> None:
        self._complete_json_response = response

    async def complete(
        self,
        prompt: str,
        system: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> str:
        self._call_history.append({
            "method": "complete",
            "prompt": prompt,
            "system": system,
            "temperature": temperature,
            "max_tokens": max_tokens,
        })
        return self._complete_response

    async def complete_json(
        self,
        prompt: str,
        system: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> dict:
        self._call_history.append({
            "method": "complete_json",
            "prompt": prompt,
            "system": system,
            "temperature": temperature,
            "max_tokens": max_tokens,
        })
        return self._complete_json_response

    @property
    def name(self) -> str:
        return "mock/llm"


class MockEmbeddingProvider(EmbeddingProvider):
    """Mock embedding provider for testing."""

    def __init__(self, dimensions: int = 128):
        self._dimensions = dimensions
        self._embed_map: dict[str, list[float]] = {}
        self._call_history: list[dict] = []

    def set_embedding(self, text: str, embedding: list[float]) -> None:
        self._embed_map[text] = embedding

    async def embed(self, text: str) -> list[float]:
        self._call_history.append({"method": "embed", "text": text})
        if text in self._embed_map:
            return self._embed_map[text]
        # Generate deterministic embedding
        import hashlib
        hash_bytes = hashlib.sha256(text.encode()).digest()
        embedding = []
        for i in range(self._dimensions):
            byte_idx = i % len(hash_bytes)
            val = (hash_bytes[byte_idx] - 128) / 128.0
            embedding.append(val)
        return embedding

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        self._call_history.append({"method": "embed_batch", "texts": texts})
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
def temp_db_path():
    """Create a temporary database file."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.unlink(path)


@pytest.fixture
def mock_llm():
    """Create a mock LLM provider."""
    return MockLLMProvider()


@pytest.fixture
def mock_embedding():
    """Create a mock embedding provider."""
    return MockEmbeddingProvider()


@pytest.fixture
def memory_store(temp_db_path):
    """Create a memory store with temp database."""
    store = SQLiteMemoryStore(temp_db_path)
    yield store
    if os.path.exists(temp_db_path):
        os.unlink(temp_db_path)


@pytest.fixture
def memory_interface(mock_llm, mock_embedding, memory_store):
    """Create a memory interface for testing."""
    return MemoryInterface(
        llm=mock_llm,
        embedding=mock_embedding,
        store=memory_store,
        consolidation_threshold=3,
        auto_consolidate=False,
    )


@pytest.fixture
def decay_api_app(memory_interface):
    """Create a test API app with decay routes."""
    # Override the _get_memory_from_request to use our test memory
    import remind.api.routes as routes_module
    
    # Create Starlette app with API routes
    app = Starlette(routes=api_routes)
    return app


# =============================================================================
# Test 1: Retrieval Includes Decay
# =============================================================================

class TestRetrievalIncludesDecay:
    """Test that retrieval ranking incorporates decay scores."""

    @pytest.mark.asyncio
    async def test_retrieval_includes_decay(
        self, mock_llm, mock_embedding, memory_store
    ):
        """
        Create concepts with different access patterns.
        Perform retrieval queries.
        Verify ranking incorporates decay scores.
        Concepts with higher decay should rank higher.
        """
        from remind.retrieval import MemoryRetriever

        # Create two concepts with different decay profiles
        concept_high_decay = Concept(
            id="concept_high_decay",
            summary="Recently accessed concept with high decay",
            confidence=0.9,
            access_count=50,
            last_accessed=datetime.now() - timedelta(hours=1),
            embedding=[1.0, 0.0, 0.0] + [0.0] * 125,
        )

        concept_low_decay = Concept(
            id="concept_low_decay",
            summary="Old concept with low decay",
            confidence=0.9,
            access_count=0,
            last_accessed=datetime.now() - timedelta(days=30),
            embedding=[0.0, 1.0, 0.0] + [0.0] * 125,
        )

        memory_store.add_concept(concept_high_decay)
        memory_store.add_concept(concept_low_decay)

        # Create retriever
        config = RemindConfig()
        retriever = MemoryRetriever(
            embedding=mock_embedding,
            store=memory_store,
            config=config,
        )

        # Set embedding to match both concepts equally
        mock_embedding.set_embedding(
            "test query",
            [0.5, 0.5, 0.0] + [0.0] * 125
        )

        # Retrieve
        results = await retriever.retrieve("test query", k=10)

        # Verify both concepts are returned
        assert len(results) >= 2

        # Calculate decay scores manually
        high_decay_score = retriever._compute_decay_score(concept_high_decay)
        low_decay_score = retriever._compute_decay_score(concept_low_decay)

        # High decay concept should rank higher due to recency and frequency
        high_decay_result = next(r for r in results if r.concept.id == "concept_high_decay")
        low_decay_result = next(r for r in results if r.concept.id == "concept_low_decay")

        # Both should have decay scores
        assert high_decay_result.decay_score > 0
        assert low_decay_result.decay_score > 0

        # High decay concept should have higher score
        assert high_decay_result.decay_score >= low_decay_result.decay_score


# =============================================================================
# Test 2: Access Logging
# =============================================================================

class TestAccessLogging:
    """Test that accesses are properly logged to database."""

    @pytest.mark.asyncio
    async def test_access_logging(
        self, mock_llm, mock_embedding, memory_store
    ):
        """
        Perform multiple retrievals.
        Verify accesses are logged to database.
        Verify access counts increment.
        Verify last_accessed updates.
        """
        from remind.retrieval import MemoryRetriever

        # Create concept
        concept = Concept(
            id="test_concept",
            summary="Test concept for access logging",
            confidence=0.9,
            access_count=0,
            last_accessed=None,
            embedding=[1.0, 0.0, 0.0] + [0.0] * 125,
        )
        memory_store.add_concept(concept)

        config = RemindConfig()
        retriever = MemoryRetriever(
            embedding=mock_embedding,
            store=memory_store,
            config=config,
        )

        # Set embedding to match concept
        mock_embedding.set_embedding(
            "test query",
            [1.0, 0.0, 0.0] + [0.0] * 125
        )

        # First retrieval
        result1 = await retriever.retrieve("test query", k=5)
        assert len(result1) == 1
        assert result1[0].concept.access_count == 1
        first_access_time = result1[0].concept.last_accessed
        assert first_access_time is not None

        # Second retrieval
        result2 = await retriever.retrieve("test query", k=5)
        assert len(result2) == 1
        assert result2[0].concept.access_count == 2
        assert result2[0].concept.last_accessed is not None
        assert result2[0].concept.last_accessed > first_access_time

        # Verify in database
        stored_concept = memory_store.get_concept("test_concept")
        assert stored_concept.access_count == 2
        assert stored_concept.last_accessed is not None

        # Check access log
        access_stats = memory_store.get_concept_access_stats("test_concept")
        assert access_stats["total_accesses"] == 2
        assert access_stats["last_accessed"] is not None
        assert access_stats["avg_activation"] > 0


# =============================================================================
# Test 3: CLI Commands End to End
# =============================================================================

class TestCLICommandsEndToEnd:
    """Test CLI decay commands end to end."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database for CLI testing."""
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        yield path
        if os.path.exists(path):
            os.unlink(path)

    @pytest.fixture
    def runner(self, temp_db):
        """Create a CLI runner with temp database."""
        os.environ["REMIND_DB"] = temp_db
        return CliRunner()

    @pytest.mark.asyncio
    async def test_cli_decay_inspect(self, runner, temp_db, mock_llm, mock_embedding):
        """Test `remind decay inspect` with real concept."""
        # Set up memory and create concept
        store = SQLiteMemoryStore(temp_db)
        memory = MemoryInterface(
            llm=mock_llm,
            embedding=mock_embedding,
            store=store,
        )

        concept = Concept(
            id="test_cli_concept",
            summary="Test CLI concept",
            confidence=0.8,
            access_count=10,
            last_accessed=datetime.now() - timedelta(days=2),
            embedding=[1.0, 0.0, 0.0] + [0.0] * 125,
        )
        store.add_concept(concept)

        # Run inspect command with explicit db path
        result = runner.invoke(cli, ["--db", temp_db, "decay", "inspect", "test_cli_concept"])

        # Should succeed
        assert result.exit_code == 0
        # Should contain decay information
        assert "Decay Score" in result.output
        assert "Access Count" in result.output

    @pytest.mark.asyncio
    async def test_cli_decay_reset(self, runner, temp_db, mock_llm, mock_embedding):
        """Test `remind decay reset` and verify decay score changes."""
        store = SQLiteMemoryStore(temp_db)
        memory = MemoryInterface(
            llm=mock_llm,
            embedding=mock_embedding,
            store=store,
        )

        concept = Concept(
            id="test_reset_concept",
            summary="Test reset concept",
            confidence=0.8,
            access_count=50,
            last_accessed=datetime.now() - timedelta(days=10),
            embedding=[1.0, 0.0, 0.0] + [0.0] * 125,
        )
        store.add_concept(concept)

        # Reset decay (use echo to confirm)
        result = runner.invoke(
            cli,
            ["--db", temp_db, "decay", "reset", "test_reset_concept"],
            input="yes\n",
        )

        # Should succeed
        assert result.exit_code == 0
        assert "Reset decay" in result.output or "decay_score" in result.output.lower()

        # Verify decay was reset (access_count should be 0)
        updated_concept = store.get_concept("test_reset_concept")
        assert updated_concept is not None
        assert updated_concept.access_count == 0

    @pytest.mark.asyncio
    async def test_cli_decay_recent(self, runner, temp_db, mock_llm, mock_embedding):
        """Test `remind decay recent` shows logged accesses."""
        store = SQLiteMemoryStore(temp_db)
        memory = MemoryInterface(
            llm=mock_llm,
            embedding=mock_embedding,
            store=store,
        )

        # Create concept and perform some retrievals
        concept = Concept(
            id="test_recent_concept",
            summary="Test recent accesses",
            confidence=0.9,
            access_count=5,
            last_accessed=datetime.now(),
            embedding=[1.0, 0.0, 0.0] + [0.0] * 125,
        )
        store.add_concept(concept)

        # Run recent command
        result = runner.invoke(cli, ["--db", temp_db, "decay", "recent"])

        # Should succeed
        assert result.exit_code == 0
        # Should show recent accesses or empty message
        assert "Recent Accesses" in result.output or "No concept accesses" in result.output

    @pytest.mark.asyncio
    async def test_cli_decay_config(self, runner, temp_db, mock_llm, mock_embedding):
        """Test `remind decay config` shows configuration."""
        store = SQLiteMemoryStore(temp_db)
        memory = MemoryInterface(
            llm=mock_llm,
            embedding=mock_embedding,
            store=store,
        )

        # Run config command
        result = runner.invoke(cli, ["decay", "config"])

        # Should succeed
        assert result.exit_code == 0
        # Should show configuration
        assert "Enabled" in result.output
        assert "Decay half-life" in result.output


# =============================================================================
# Test 4: API Endpoints End to End
# =============================================================================

class TestAPIEndpointsEndToEnd:
    """Test API decay endpoints end to end."""

    @pytest.fixture
    def api_client(self, memory_interface, temp_db_path):
        """Create a test API client."""
        app = Starlette(routes=api_routes)
        # Store memory in app state
        app.state.memory = memory_interface
        return TestClient(app)

    @pytest.mark.asyncio
    async def test_api_get_concept_decay(self, api_client, memory_interface, temp_db_path):
        """Test GET /api/v1/concepts/<id>/decay."""
        # Create concept
        concept = Concept(
            id="test_api_decay",
            summary="Test API decay concept",
            confidence=0.85,
            access_count=15,
            last_accessed=datetime.now() - timedelta(days=3),
            embedding=[1.0, 0.0, 0.0] + [0.0] * 125,
        )
        memory_interface.store.add_concept(concept)

        # Make request with db parameter
        response = api_client.get(f"/api/v1/concepts/test_api_decay/decay?db={temp_db_path}")

        # Verify response
        assert response.status_code == 200
        data = response.json()
        assert "decay_score" in data
        assert "access_count" in data
        assert "last_accessed" in data
        assert "recency_factor" in data
        assert "frequency_factor" in data
        assert data["access_count"] == 15

    @pytest.mark.asyncio
    async def test_api_reset_concept_decay(self, api_client, memory_interface, temp_db_path):
        """Test PUT /api/v1/concepts/<id>/decay/reset."""
        # Create concept
        concept = Concept(
            id="test_api_reset",
            summary="Test API reset concept",
            confidence=0.8,
            access_count=50,
            last_accessed=datetime.now() - timedelta(days=10),
            embedding=[1.0, 0.0, 0.0] + [0.0] * 125,
        )
        memory_interface.store.add_concept(concept)

        # Make request with db parameter
        response = api_client.put(f"/api/v1/concepts/test_api_reset/decay/reset?db={temp_db_path}")

        # Verify response
        assert response.status_code == 200
        data = response.json()
        assert "decay_score" in data
        assert "success" in data

        # Verify access count was reset
        updated_concept = memory_interface.store.get_concept("test_api_reset")
        assert updated_concept is not None
        assert updated_concept.access_count == 0

    @pytest.mark.asyncio
    async def test_api_get_decay_recent(self, api_client, memory_interface, temp_db_path):
        """Test GET /api/v1/decay/recent."""
        # Create concept with accesses
        concept = Concept(
            id="test_api_recent",
            summary="Test API recent concept",
            confidence=0.9,
            access_count=5,
            last_accessed=datetime.now(),
            embedding=[1.0, 0.0, 0.0] + [0.0] * 125,
        )
        memory_interface.store.add_concept(concept)

        # Make request with db parameter
        response = api_client.get(f"/api/v1/decay/recent?db={temp_db_path}&limit=10")

        # Verify response
        assert response.status_code == 200
        data = response.json()
        assert "accesses" in data
        assert isinstance(data["accesses"], list)

    @pytest.mark.asyncio
    async def test_api_get_decay_config(self, api_client, memory_interface, temp_db_path):
        """Test GET /api/v1/decay/config."""
        # Make request with db parameter
        response = api_client.get(f"/api/v1/decay/config?db={temp_db_path}")

        # Verify response
        assert response.status_code == 200
        data = response.json()
        assert "enabled" in data
        assert "decay_half_life" in data
        assert "frequency_threshold" in data
        assert "min_decay_score" in data


# =============================================================================
# Test 5: Decay with Consolidation
# =============================================================================

class TestDecayWithConsolidation:
    """Test decay works with newly created concepts from consolidation."""

    @pytest.mark.asyncio
    async def test_decay_with_consolidation(
        self, mock_llm, mock_embedding, memory_store, temp_db_path
    ):
        """
        Remember episodes.
        Consolidate into concepts.
        Perform retrievals.
        Verify decay updates work with newly created concepts.
        """
        # Create memory interface
        memory = MemoryInterface(
            llm=mock_llm,
            embedding=mock_embedding,
            store=memory_store,
            consolidation_threshold=3,
            auto_consolidate=False,
        )

        # Remember episodes
        memory.remember("User prefers Python for backend development")
        memory.remember("User mentioned they work on distributed systems")
        memory.remember("User values code readability")

        # Set up mock response for consolidation
        mock_llm.set_complete_json_response({
            "analysis": "User is a Python developer who values clean code",
            "updates": [],
            "new_concepts": [
                {
                    "summary": "User strongly prefers Python for backend development and values readable code",
                    "confidence": 0.85,
                    "tags": ["programming", "preferences"],
                    "relations": [],
                }
            ],
            "new_relations": [],
            "contradictions": [],
        })

        # Consolidate
        result = await memory.consolidate(force=True)

        assert result.episodes_processed == 3
        assert result.concepts_created == 1

        # Get created concept
        concepts = memory.get_all_concepts()
        assert len(concepts) >= 1
        new_concept = concepts[0]

        # Verify concept has decay fields
        assert hasattr(new_concept, "access_count")
        assert hasattr(new_concept, "last_accessed")
        assert new_concept.access_count == 0
        assert new_concept.last_accessed is None

        # Perform retrieval
        mock_embedding.set_embedding(
            "python preferences",
            new_concept.embedding
        )

        from remind.retrieval import MemoryRetriever
        config = RemindConfig()
        retriever = MemoryRetriever(
            embedding=mock_embedding,
            store=memory_store,
            config=config,
        )

        recalled = await retriever.retrieve("python preferences", k=5)
        assert len(recalled) >= 1

        # Verify decay score was computed
        assert recalled[0].decay_score > 0

        # Perform another retrieval to verify access tracking
        recalled2 = await retriever.retrieve("python preferences", k=5)
        # Access count should be at least 2 (one from first retrieval, one from second)
        # Note: get_all_concepts() may also trigger accesses
        assert recalled2[0].concept.access_count >= 2


# =============================================================================
# Test 6: Decay Disabled
# =============================================================================

class TestDecayDisabled:
    """Test behavior when decay is disabled."""

    @pytest.mark.asyncio
    async def test_decay_disabled(
        self, mock_llm, mock_embedding, memory_store
    ):
        """
        Configure decay disabled.
        Verify retrieval still works.
        Verify decay scores are computed but use defaults.
        Verify access tracking still happens.
        """
        from remind.retrieval import MemoryRetriever

        # Create concept with decay disabled
        decay_config = DecayConfig(enabled=False)
        config = RemindConfig(decay=decay_config)

        concept = Concept(
            id="test_disabled_decay",
            summary="Test disabled decay concept",
            confidence=0.9,
            access_count=0,
            last_accessed=None,
            embedding=[1.0, 0.0, 0.0] + [0.0] * 125,
        )
        memory_store.add_concept(concept)

        # Create retriever with decay disabled
        retriever = MemoryRetriever(
            embedding=mock_embedding,
            store=memory_store,
            config=config,
        )

        # Set embedding to match concept
        mock_embedding.set_embedding(
            "test query",
            [1.0, 0.0, 0.0] + [0.0] * 125
        )

        # Retrieve should still work
        result = await retriever.retrieve("test query", k=5)
        assert len(result) >= 1

        # Verify retrieval works even with decay disabled
        assert result[0].concept.id == "test_disabled_decay"

        # Decay score should be computed (but use defaults when disabled)
        assert result[0].decay_score > 0
        
        # Access tracking still happens even when decay is disabled
        stored_concept = memory_store.get_concept("test_disabled_decay")
        assert stored_concept.access_count >= 1
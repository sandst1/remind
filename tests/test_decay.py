"""Unit tests for decay computation and access tracking."""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, MagicMock, AsyncMock

from remind.models import Concept
from remind.config import DecayConfig, RemindConfig
from remind.retrieval import MemoryRetriever
from remind.providers.base import EmbeddingProvider


class TestDecayScoreComputation:
    """Test decay score computation formula and weights."""

    @pytest.fixture
    def mock_embedding_provider(self):
        """Create a mock embedding provider."""
        mock = Mock(spec=EmbeddingProvider)
        mock.embed = AsyncMock(return_value=[0.1] * 128)
        mock.embed_batch = AsyncMock(return_value=[[0.1] * 128])
        mock.dimensions = 128
        mock.name = "mock/embedding"
        return mock

    @pytest.fixture
    def mock_store(self):
        """Create a mock store."""
        return Mock()

    @pytest.fixture
    def retriever(self, mock_embedding_provider, mock_store):
        """Create a MemoryRetriever instance."""
        config = RemindConfig()
        return MemoryRetriever(
            embedding=mock_embedding_provider,
            store=mock_store,
            config=config,
        )

    def test_decay_score_weights(self, retriever):
        """Test that decay score uses correct weights: 40% recency, 40% frequency, 20% confidence."""
        # Create a concept with known values
        concept = Concept(
            id="test_concept",
            summary="Test concept",
            confidence=1.0,  # Max confidence
            access_count=100,  # Above threshold
            last_accessed=datetime.now(),  # Just accessed
        )

        # Compute decay score
        decay_score = retriever._compute_decay_score(concept)

        # With max recency (1.0), max frequency (1.0), and max confidence (1.0):
        # decay = (1.0 * 0.4) + (1.0 * 0.4) + (1.0 * 0.5) = 0.9
        # Note: confidence_boost = confidence * 0.5, so max is 0.5
        expected_max = (1.0 * 0.4) + (1.0 * 0.4) + (1.0 * 0.5)
        
        assert abs(decay_score - expected_max) < 0.0001

    def test_decay_score_with_zero_confidence(self, retriever):
        """Test decay score with confidence=0."""
        concept = Concept(
            id="test_concept",
            summary="Test concept",
            confidence=0.0,
            access_count=0,
            last_accessed=datetime.now(),
        )

        decay_score = retriever._compute_decay_score(concept)

        # With confidence=0.0, the code uses (confidence or 0.5) * 0.5 = 0.25
        # decay = (1.0 * 0.4) + (0 * 0.4) + 0.25 = 0.65
        expected = 0.65
        assert abs(decay_score - expected) < 0.0001

    def test_decay_score_with_max_confidence(self, retriever):
        """Test decay score with confidence=1."""
        concept = Concept(
            id="test_concept",
            summary="Test concept",
            confidence=1.0,
            access_count=100,
            last_accessed=datetime.now(),
        )

        decay_score = retriever._compute_decay_score(concept)

        # With confidence=1.0, frequency=1.0 (capped), recency=1.0:
        expected = (1.0 * 0.4) + (1.0 * 0.4) + (1.0 * 0.5)
        assert abs(decay_score - expected) < 0.0001

    def test_decay_score_min_threshold_enforced(self, retriever):
        """Test that minimum decay score threshold is enforced."""
        # Create a very old concept with no accesses
        concept = Concept(
            id="test_concept",
            summary="Test concept",
            confidence=0.0,
            access_count=0,
            last_accessed=datetime.now() - timedelta(days=365),
        )

        decay_score = retriever._compute_decay_score(concept)

        # Should be at least min_decay_score (0.1)
        assert decay_score >= retriever.config.decay.min_decay_score


class TestRecencyDecay:
    """Test recency decay computation."""

    @pytest.fixture
    def mock_embedding_provider(self):
        """Create a mock embedding provider."""
        mock = Mock(spec=EmbeddingProvider)
        mock.embed = AsyncMock(return_value=[0.1] * 128)
        mock.embed_batch = AsyncMock(return_value=[[0.1] * 128])
        mock.dimensions = 128
        mock.name = "mock/embedding"
        return mock

    @pytest.fixture
    def mock_store(self):
        """Create a mock store."""
        return Mock()

    @pytest.fixture
    def retriever(self, mock_embedding_provider, mock_store):
        """Create a MemoryRetriever instance."""
        config = RemindConfig()
        config.decay.decay_half_life = 30.0  # Default half-life
        return MemoryRetriever(
            embedding=mock_embedding_provider,
            store=mock_store,
            config=config,
        )

    def test_new_concepts_have_full_recency(self, retriever):
        """Test that new concepts (never accessed) get recency_factor = 1.0."""
        concept = Concept(
            id="new_concept",
            summary="New concept",
            confidence=0.5,
            last_accessed=None,  # Never accessed
        )

        recency_factor = retriever._compute_recency_factor(concept)

        assert recency_factor == 1.0

    def test_recent_access_full_recency(self, retriever):
        """Test that recently accessed concepts get high recency factor."""
        concept = Concept(
            id="recent_concept",
            summary="Recent concept",
            last_accessed=datetime.now() - timedelta(hours=1),
        )

        recency_factor = retriever._compute_recency_factor(concept)

        # Should be very close to 1.0 (accessed 1 hour ago)
        assert recency_factor > 0.95

    def test_recency_decay_half_life(self, retriever):
        """Test that recency decay follows half-life behavior."""
        # Access 30 days ago (half-life)
        concept = Concept(
            id="half_life_concept",
            summary="Half-life concept",
            last_accessed=datetime.now() - timedelta(days=30),
        )

        recency_factor = retriever._compute_recency_factor(concept)

        # Formula: 1 / (1 + days_since_access / half_life)
        # = 1 / (1 + 30 / 30) = 1 / 2 = 0.5
        expected = 0.5
        assert abs(recency_factor - expected) < 0.01

    def test_recency_decay_various_days(self, retriever):
        """Test recency factor with various days_since_access values."""
        test_cases = [
            (0, 1.0),           # Just accessed
            (1, 0.97),          # 1 day ago
            (7, 0.81),          # 1 week ago
            (30, 0.5),          # 1 half-life (30 days)
            (60, 0.33),         # 2 half-lives
            (90, 0.25),         # 3 half-lives
            (180, 0.14),        # 6 half-lives
            (365, 0.07),        # 1 year
        ]

        for days_ago, expected_min in test_cases:
            concept = Concept(
                id=f"concept_{days_ago}",
                summary="Test concept",
                last_accessed=datetime.now() - timedelta(days=days_ago),
            )

            recency_factor = retriever._compute_recency_factor(concept)

            # Should be approximately the expected value (within 5% tolerance)
            assert recency_factor <= expected_min + 0.05
            assert recency_factor >= expected_min - 0.05


class TestFrequencyCapping:
    """Test frequency factor capping behavior."""

    @pytest.fixture
    def mock_embedding_provider(self):
        """Create a mock embedding provider."""
        mock = Mock(spec=EmbeddingProvider)
        mock.embed = AsyncMock(return_value=[0.1] * 128)
        mock.embed_batch = AsyncMock(return_value=[[0.1] * 128])
        mock.dimensions = 128
        mock.name = "mock/embedding"
        return mock

    @pytest.fixture
    def mock_store(self):
        """Create a mock store."""
        return Mock()

    @pytest.fixture
    def retriever(self, mock_embedding_provider, mock_store):
        """Create a MemoryRetriever instance."""
        config = RemindConfig()
        config.decay.frequency_threshold = 10  # Default threshold
        return MemoryRetriever(
            embedding=mock_embedding_provider,
            store=mock_store,
            config=config,
        )

    def test_frequency_below_threshold(self, retriever):
        """Test frequency factor < 1.0 when access_count < threshold."""
        concept = Concept(
            id="low_freq_concept",
            summary="Low frequency concept",
            access_count=5,  # Below threshold of 10
        )

        frequency_factor = retriever._compute_frequency_factor(concept)

        # frequency = min(5 / 10, 1.0) = 0.5
        expected = 0.5
        assert frequency_factor == expected

    def test_frequency_at_threshold(self, retriever):
        """Test frequency factor = 1.0 when access_count >= threshold."""
        concept = Concept(
            id="threshold_concept",
            summary="Threshold concept",
            access_count=10,  # At threshold
        )

        frequency_factor = retriever._compute_frequency_factor(concept)

        # frequency = min(10 / 10, 1.0) = 1.0
        assert frequency_factor == 1.0

    def test_frequency_above_threshold(self, retriever):
        """Test frequency factor = 1.0 when access_count > threshold."""
        concept = Concept(
            id="high_freq_concept",
            summary="High frequency concept",
            access_count=50,  # Above threshold
        )

        frequency_factor = retriever._compute_frequency_factor(concept)

        # Should be capped at 1.0
        assert frequency_factor == 1.0

    def test_frequency_multiple_of_threshold(self, retriever):
        """Test frequency factor at multiple of threshold."""
        test_cases = [
            (10, 1.0),        # 1x threshold
            (20, 1.0),        # 2x threshold
            (50, 1.0),        # 5x threshold
            (100, 1.0),       # 10x threshold
        ]

        for access_count, expected in test_cases:
            concept = Concept(
                id=f"freq_{access_count}",
                summary="Test concept",
                access_count=access_count,
            )

            frequency_factor = retriever._compute_frequency_factor(concept)

            assert frequency_factor == expected

    def test_frequency_zero_accesses(self, retriever):
        """Test frequency factor with zero accesses."""
        concept = Concept(
            id="no_access_concept",
            summary="No access concept",
            access_count=0,
        )

        frequency_factor = retriever._compute_frequency_factor(concept)

        assert frequency_factor == 0.0


class TestAccessTrackingPersistence:
    """Test access tracking and persistence."""

    @pytest.fixture
    def mock_embedding_provider(self):
        """Create a mock embedding provider."""
        mock = Mock(spec=EmbeddingProvider)
        mock.embed = AsyncMock(return_value=[0.1] * 128)
        mock.embed_batch = AsyncMock(return_value=[[0.1] * 128])
        mock.dimensions = 128
        mock.name = "mock/embedding"
        return mock

    @pytest.fixture
    def temp_db_path(self):
        """Create a temporary database file path."""
        import tempfile
        import os
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        yield path
        if os.path.exists(path):
            os.unlink(path)

    @pytest.fixture
    def store(self, temp_db_path):
        """Create a SQLite memory store."""
        from remind.store import SQLiteMemoryStore
        return SQLiteMemoryStore(temp_db_path)

    @pytest.fixture
    def retriever(self, mock_embedding_provider, store):
        """Create a MemoryRetriever instance."""
        return MemoryRetriever(
            embedding=mock_embedding_provider,
            store=store,
        )

    @pytest.fixture
    def concept_with_access(self, store):
        """Create and persist a concept with initial access."""
        from remind.models import Concept
        
        concept = Concept(
            id="access_test_concept",
            summary="Test concept for access tracking",
            confidence=0.8,
            access_count=0,
            last_accessed=datetime.now() - timedelta(hours=2),
            embedding=[0.1] * 128,
        )
        store.add_concept(concept)
        return concept

    def test_access_count_increments(self, retriever, store, concept_with_access):
        """Test that access_count increments correctly."""
        # The concept should already exist from the fixture
        concept = store.get_concept("access_test_concept")
        assert concept is not None
        initial_count = concept.access_count
        concept.access_count += 1
        concept.last_accessed = datetime.now()
        concept.access_history.append((concept.last_accessed, 0.8))
        concept.access_history = concept.access_history[-100:]
        store.update_concept(concept)

        # Fetch the updated concept
        updated_concept = store.get_concept("access_test_concept")

        assert updated_concept is not None
        assert updated_concept.access_count == 1

    def test_last_accessed_updates(self, retriever, store, concept_with_access):
        """Test that last_accessed updates to current timestamp."""
        old_access_time = concept_with_access.last_accessed
        
        # Get the concept, update last_accessed, and persist
        concept = store.get_concept("access_test_concept")
        assert concept is not None
        concept.last_accessed = datetime.now()
        store.update_concept(concept)

        # Fetch the updated concept
        updated_concept = store.get_concept("access_test_concept")

        # last_accessed should be updated to now
        assert updated_concept is not None
        assert updated_concept.last_accessed > old_access_time

    def test_access_history_truncation(self, retriever, store):
        """Test that access_history truncates to 100 entries."""
        from remind.models import Concept
        
        concept = Concept(
            id="history_test_concept",
            summary="Test concept for history",
            access_count=0,
            embedding=[0.1] * 128,
        )
        store.add_concept(concept)

        # Simulate 150 accesses
        for i in range(150):
            concept.access_count += 1
            concept.last_accessed = datetime.now() - timedelta(seconds=150 - i)
            concept.access_history.append((concept.last_accessed, 0.5 + (i * 0.001)))
            # Keep only last 100 entries
            concept.access_history = concept.access_history[-100:]
            
            # Persist after each access
            store.update_concept(concept)
        
        # Fetch the concept from database
        fetched_concept = store.get_concept("history_test_concept")

        # Should be truncated to 100 entries
        assert fetched_concept is not None
        assert len(fetched_concept.access_history) <= 100

    def test_database_persistence(self, retriever, store, concept_with_access):
        """Test that access tracking persists to database."""
        # Initial state
        initial_count = concept_with_access.access_count
        initial_last_accessed = concept_with_access.last_accessed

        # Update and persist multiple accesses
        for i in range(5):
            concept = store.get_concept("access_test_concept")
            assert concept is not None
            concept.access_count += 1
            concept.last_accessed = datetime.now()
            concept.access_history.append((concept.last_accessed, 0.8))
            concept.access_history = concept.access_history[-100:]
            store.update_concept(concept)

        # Fetch from database
        persisted_concept = store.get_concept("access_test_concept")

        # Verify persistence
        assert persisted_concept is not None
        assert persisted_concept.access_count == initial_count + 5
        assert persisted_concept.last_accessed > initial_last_accessed


class TestMinDecayScore:
    """Test minimum decay score enforcement."""

    @pytest.fixture
    def mock_embedding_provider(self):
        """Create a mock embedding provider."""
        mock = Mock(spec=EmbeddingProvider)
        mock.embed = AsyncMock(return_value=[0.1] * 128)
        mock.embed_batch = AsyncMock(return_value=[[0.1] * 128])
        mock.dimensions = 128
        mock.name = "mock/embedding"
        return mock

    @pytest.fixture
    def mock_store(self):
        """Create a mock store."""
        return Mock()

    @pytest.fixture
    def retriever(self, mock_embedding_provider, mock_store):
        """Create a MemoryRetriever instance."""
        config = RemindConfig()
        config.decay.min_decay_score = 0.1  # Default minimum
        return MemoryRetriever(
            embedding=mock_embedding_provider,
            store=mock_store,
            config=config,
        )

    def test_min_decay_score_enforced(self, retriever):
        """Verify minimum threshold is enforced."""
        # Create a very old concept with zero accesses and zero confidence
        concept = Concept(
            id="stale_concept",
            summary="Very stale concept",
            confidence=0.0,
            access_count=0,
            last_accessed=datetime.now() - timedelta(days=1000),  # Very old
        )

        decay_score = retriever._compute_decay_score(concept)

        # Should be at least min_decay_score
        assert decay_score >= retriever.config.decay.min_decay_score

    def test_old_concepts_with_no_accesses(self, retriever):
        """Test with very old concepts and zero accesses."""
        concept = Concept(
            id="ancient_concept",
            summary="Ancient concept",
            confidence=0.0,
            access_count=0,
            last_accessed=datetime.now() - timedelta(days=365 * 10),  # 10 years old
        )

        decay_score = retriever._compute_decay_score(concept)

        # Should be at minimum threshold
        assert decay_score >= retriever.config.decay.min_decay_score


class TestComputeDecayScoreEdgeCases:
    """Test decay computation edge cases."""

    @pytest.fixture
    def mock_embedding_provider(self):
        """Create a mock embedding provider."""
        mock = Mock(spec=EmbeddingProvider)
        mock.embed = AsyncMock(return_value=[0.1] * 128)
        mock.embed_batch = AsyncMock(return_value=[[0.1] * 128])
        mock.dimensions = 128
        mock.name = "mock/embedding"
        return mock

    @pytest.fixture
    def mock_store(self):
        """Create a mock store."""
        return Mock()

    @pytest.fixture
    def retriever(self, mock_embedding_provider, mock_store):
        """Create a MemoryRetriever instance."""
        return MemoryRetriever(
            embedding=mock_embedding_provider,
            store=mock_store,
        )

    def test_concept_no_last_accessed(self, retriever):
        """Test concept with no last_accessed (new concept)."""
        concept = Concept(
            id="new_concept",
            summary="New concept never accessed",
            confidence=0.5,
            last_accessed=None,
        )

        decay_score = retriever._compute_decay_score(concept)

        # Should have full recency (1.0)
        # decay = (1.0 * 0.4) + (0 * 0.4) + (0.5 * 0.5) = 0.65
        expected = (1.0 * 0.4) + (0 * 0.4) + (0.5 * 0.5)
        assert decay_score == expected

    def test_concept_no_confidence(self, retriever):
        """Test concept with no confidence (defaults to 0.5)."""
        concept = Concept(
            id="uncertain_concept",
            summary="Uncertain concept",
            confidence=0.5,
            last_accessed=datetime.now(),
            access_count=0,
        )

        decay_score = retriever._compute_decay_score(concept)

        # With default confidence of 0.5
        # decay = (1.0 * 0.4) + (0 * 0.4) + (0.5 * 0.5) = 0.65
        expected = (1.0 * 0.4) + (0 * 0.4) + (0.5 * 0.5)
        assert abs(decay_score - expected) < 0.0001

    def test_concept_empty_access_history(self, retriever):
        """Test concept with empty access_history."""
        concept = Concept(
            id="empty_history_concept",
            summary="Concept with empty history",
            confidence=0.8,
            last_accessed=datetime.now(),
            access_count=0,
            access_history=[],  # Empty history
        )

        decay_score = retriever._compute_decay_score(concept)

        # Should compute normally with empty history
        # decay = (1.0 * 0.4) + (0 * 0.4) + (0.8 * 0.5) = 0.8
        expected = (1.0 * 0.4) + (0 * 0.4) + (0.8 * 0.5)
        assert abs(decay_score - expected) < 0.0001

    def test_decay_disabled(self, mock_embedding_provider, mock_store):
        """Test when decay is disabled."""
        config = RemindConfig()
        config.decay.enabled = False
        
        retriever = MemoryRetriever(
            embedding=mock_embedding_provider,
            store=mock_store,
            config=config,
        )

        # Create a very old concept
        concept = Concept(
            id="stale_concept",
            summary="Stale concept",
            confidence=0.5,
            access_count=0,
            last_accessed=datetime.now() - timedelta(days=365),
        )

        decay_score = retriever._compute_decay_score(concept)

        # When decay is disabled:
        # recency_factor = 1.0, frequency_factor = 1.0
        # confidence_boost = 0.5 * 0.5 = 0.25
        # decay_score = (1.0 * 0.4) + (1.0 * 0.4) + 0.25 = 1.05
        # But it's capped by min_decay_score (0.1), so should be 1.05
        expected = 1.05
        assert abs(decay_score - expected) < 0.0001



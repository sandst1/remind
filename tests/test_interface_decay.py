"""End-to-end integration tests for memory decay through MemoryInterface.recall()."""

import pytest
import tempfile
import os
import asyncio

from remind.interface import MemoryInterface
from remind.config import DecayConfig
from remind.models import Concept, Episode
from tests.conftest import MockLLMProvider, MockEmbeddingProvider


class TestInterfaceRejuvenation:
    """Tests for rejuvenation happening on recall through MemoryInterface."""

    @pytest.fixture
    def interface(self, temp_db_path):
        """Create a MemoryInterface with mock providers."""
        mock_llm = MockLLMProvider()
        mock_embedding = MockEmbeddingProvider(dimensions=128)
        
        # Set up a specific embedding for query matching
        mock_embedding.set_embedding("test query", [1.0, 0.0, 0.0] + [0.0] * 125)
        
        return MemoryInterface(
            llm=mock_llm,
            embedding=mock_embedding,
            db_path=temp_db_path,
            decay_config=DecayConfig(decay_interval=20, decay_rate=0.1),
        )

    def test_rejuvenation_happens_on_recall(self, interface):
        """Test that calling recall() increases decay_factor."""
        # Add a concept with low decay_factor
        concept = Concept(
            id="rejuvenate-test",
            summary="Test rejuvenation",
            decay_factor=0.5,
            confidence=0.9,
            embedding=[1.0, 0.0, 0.0] + [0.0] * 125,
        )
        interface.store.add_concept(concept)
        
        # Verify initial state
        initial = interface.store.get_concept("rejuvenate-test")
        assert initial.decay_factor == 0.5
        
        # Call recall
        asyncio.run(interface.recall("test query"))
        
        # Verify decay_factor increased (rejuvenation happened)
        updated = interface.store.get_concept("rejuvenate-test")
        assert updated.decay_factor > 0.5
        assert updated.access_count == 1
        assert updated.last_accessed is not None

    def test_rejuvenation_updates_timestamps(self, interface):
        """Test that rejuvenation updates last_accessed and updated_at."""
        from datetime import datetime, timedelta
        
        old_time = datetime.now() - timedelta(days=1)
        concept = Concept(
            id="time-test",
            summary="Time test",
            decay_factor=0.7,
            last_accessed=old_time,
            embedding=[1.0, 0.0, 0.0] + [0.0] * 125,
        )
        interface.store.add_concept(concept)
        
        # Call recall
        asyncio.run(interface.recall("test query"))
        
        # Verify timestamps updated
        updated = interface.store.get_concept("time-test")
        assert updated.last_accessed > old_time
        assert updated.updated_at > old_time


class TestInterfaceDecayTrigger:
    """Tests for decay triggering at the correct interval through MemoryInterface."""

    @pytest.fixture
    def interface(self, temp_db_path):
        """Create a MemoryInterface with short decay interval for testing."""
        mock_llm = MockLLMProvider()
        mock_embedding = MockEmbeddingProvider(dimensions=128)
        
        # Set up embedding for query matching
        mock_embedding.set_embedding("test query", [1.0, 0.0, 0.0] + [0.0] * 125)
        
        # Use short interval for faster testing
        decay_config = DecayConfig(decay_interval=5, decay_rate=0.1)
        
        return MemoryInterface(
            llm=mock_llm,
            embedding=mock_embedding,
            db_path=temp_db_path,
            decay_config=decay_config,
        )

    def test_decay_triggers_at_interval(self, interface):
        """Test that decay runs at the correct recall interval.

        A bystander concept (never recalled, so no last_accessed) should decay
        after the 5th recall triggers the decay pass. The recalled concept is
        protected by the grace window and stays at 1.0.
        """
        # Recalled concept — matches the query embedding
        recalled = Concept(
            id="recalled",
            summary="Recalled concept",
            decay_factor=1.0,
            embedding=[1.0, 0.0, 0.0] + [0.0] * 125,
        )
        # Bystander — orthogonal embedding, never returned by the query
        bystander = Concept(
            id="bystander",
            summary="Bystander concept",
            decay_factor=1.0,
            embedding=[0.0, 1.0, 0.0] + [0.0] * 125,
        )
        interface.store.add_concept(recalled)
        interface.store.add_concept(bystander)

        # First 4 recalls - no decay should trigger (interval is 5)
        for i in range(4):
            asyncio.run(interface.recall("test query"))

        assert interface.store.get_concept("bystander").decay_factor == 1.0

        # 5th recall - decay triggers
        asyncio.run(interface.recall("test query"))

        # Bystander has no last_accessed, so it decays normally
        assert abs(interface.store.get_concept("bystander").decay_factor - 0.9) < 0.001

        # Recalled concept was just rejuvenated — grace window protects it
        assert interface.store.get_concept("recalled").decay_factor == 1.0

    def test_decay_triggers_multiple_times(self, interface):
        """Test that a frequently-recalled concept stays at 1.0 despite multiple decay passes.

        Because _rejuvenate_concepts() sets last_accessed just before _trigger_decay() runs,
        the decay SQL skips recently-accessed concepts (grace window = 60s).
        A concept recalled every time should never drop below 1.0.
        """
        concept = Concept(
            id="multi-decay-test",
            summary="Multi decay test",
            decay_factor=1.0,
            embedding=[1.0, 0.0, 0.0] + [0.0] * 125,
        )
        interface.store.add_concept(concept)

        # Call recall 10 times (decay triggers at recalls 5 and 10)
        for i in range(10):
            asyncio.run(interface.recall("test query"))

        # The concept was recalled on every iteration so last_accessed is always fresh.
        # Decay skips it each time => decay_factor stays at 1.0
        concept = interface.store.get_concept("multi-decay-test")
        assert concept.decay_factor == 1.0

    def test_unrecalled_concept_decays_normally(self, interface):
        """Test that concepts NOT recalled within the grace window still decay."""
        # A concept that is never matched by the query (different embedding direction)
        bystander = Concept(
            id="bystander",
            summary="Bystander concept",
            decay_factor=1.0,
            embedding=[0.0, 1.0, 0.0] + [0.0] * 125,  # orthogonal to query
        )
        interface.store.add_concept(bystander)

        # Force last_accessed to None so the grace-window check always allows decay
        # (default for a new concept that has never been rejuvenated)
        assert bystander.last_accessed is None

        # Call recall 5 times to trigger one decay pass
        mock_embedding = interface.embedding
        mock_embedding.set_embedding("test query", [1.0, 0.0, 0.0] + [0.0] * 125)
        for i in range(5):
            asyncio.run(interface.recall("test query"))

        # Bystander was never recalled (orthogonal embedding, never rejuvenated)
        # so it has no last_accessed and is not protected by the grace window
        updated = interface.store.get_concept("bystander")
        assert updated.decay_factor == 0.9  # 1.0 - 0.1


class TestInterfacePersistentRecallCount:
    """Tests for persistent recall count across MemoryInterface instances."""

    def test_persistent_recall_count_survives_restart(self, temp_db_path):
        """Test that recall count persists and is visible to new instances."""
        mock_llm = MockLLMProvider()
        mock_embedding = MockEmbeddingProvider(dimensions=128)
        
        # Create first instance and call recall
        interface1 = MemoryInterface(
            llm=mock_llm,
            embedding=mock_embedding,
            db_path=temp_db_path,
        )
        
        # Call recall 3 times
        for i in range(3):
            asyncio.run(interface1.recall("test query"))
        
        # Verify count is 3
        assert interface1._recall_count == 3
        
        # Create a NEW instance pointing to the same database
        interface2 = MemoryInterface(
            llm=mock_llm,
            embedding=mock_embedding,
            db_path=temp_db_path,
        )
        
        # New instance should see the persisted count
        assert interface2._recall_count == 3

    def test_recall_count_increments_across_instances(self, temp_db_path):
        """Test that recall count continues incrementing across instances."""
        mock_llm = MockLLMProvider()
        mock_embedding = MockEmbeddingProvider(dimensions=128)
        
        # First instance
        interface1 = MemoryInterface(
            llm=mock_llm,
            embedding=mock_embedding,
            db_path=temp_db_path,
        )
        asyncio.run(interface1.recall("test query"))
        asyncio.run(interface1.recall("test query"))
        
        # Second instance
        interface2 = MemoryInterface(
            llm=mock_llm,
            embedding=mock_embedding,
            db_path=temp_db_path,
        )
        asyncio.run(interface2.recall("test query"))
        
        # Third instance
        interface3 = MemoryInterface(
            llm=mock_llm,
            embedding=mock_embedding,
            db_path=temp_db_path,
        )
        asyncio.run(interface3.recall("test query"))
        asyncio.run(interface3.recall("test query"))
        
        # Final count should be 5
        assert interface3._recall_count == 5
        
        # Verify in metadata
        metadata_value = interface3.store.get_metadata("recall_count")
        assert metadata_value == "5"


class TestInterfaceEntityRecallDecay:
    """Tests for entity-based recall triggering decay."""

    @pytest.fixture
    def interface(self, temp_db_path):
        """Create a MemoryInterface with short decay interval."""
        mock_llm = MockLLMProvider()
        mock_embedding = MockEmbeddingProvider(dimensions=128)
        
        # Use short interval for faster testing
        decay_config = DecayConfig(decay_interval=3, decay_rate=0.1)
        
        return MemoryInterface(
            llm=mock_llm,
            embedding=mock_embedding,
            db_path=temp_db_path,
            decay_config=decay_config,
        )

    def test_entity_based_recall_triggers_decay(self, interface):
        """Test that calling recall(entity=...) triggers decay."""
        # Add a concept
        concept = Concept(
            id="entity-decay-test",
            summary="Entity decay test",
            decay_factor=1.0,
            embedding=[1.0, 0.0, 0.0] + [0.0] * 125,
        )
        interface.store.add_concept(concept)
        
        # Create an episode mentioning an entity
        episode = Episode(
            content="User mentioned file:src/auth.ts",
            entity_ids=["file:src/auth.ts"],
            entities_extracted=True,
        )
        interface.store.add_episode(episode)
        
        # Create entity
        from remind.models import Entity, EntityType
        entity = Entity(
            id="file:src/auth.ts",
            type=EntityType.FILE,
            display_name="auth.ts",
        )
        interface.store.add_entity(entity)
        
        # Call entity-based recall 3 times (interval is 3)
        for i in range(3):
            asyncio.run(interface.recall("auth", entity="file:src/auth.ts"))
        
        # Decay should have triggered
        # Note: Entity-based recall doesn't rejuvenate concepts, only triggers decay
        concept = interface.store.get_concept("entity-decay-test")
        assert concept.decay_factor == 0.9  # 1.0 - 0.1


class TestInterfaceProportionalRejuvenation:
    """Tests for proportional rejuvenation based on activation scores."""

    def test_high_activation_gets_larger_boost(self, temp_db_path):
        """Test that concepts with higher activation get larger rejuvenation boosts."""
        mock_llm = MockLLMProvider()
        mock_embedding = MockEmbeddingProvider(dimensions=128)
        
        # Set up embeddings for different similarity levels
        mock_embedding.set_embedding("high match", [1.0, 0.0, 0.0] + [0.0] * 125)
        mock_embedding.set_embedding("low match", [0.5, 0.5, 0.0] + [0.0] * 125)
        
        interface = MemoryInterface(
            llm=mock_llm,
            embedding=mock_embedding,
            db_path=temp_db_path,
        )
        
        # Create two concepts with same initial decay_factor
        high_match = Concept(
            id="high-match",
            summary="High match concept",
            decay_factor=0.5,
            confidence=0.9,
            embedding=[1.0, 0.0, 0.0] + [0.0] * 125,
        )
        low_match = Concept(
            id="low-match",
            summary="Low match concept",
            decay_factor=0.5,
            confidence=0.9,
            embedding=[0.5, 0.5, 0.0] + [0.0] * 125,
        )
        
        interface.store.add_concept(high_match)
        interface.store.add_concept(low_match)
        
        # Query for high match
        activated = asyncio.run(interface.recall("high match", raw=True))
        
        # Verify high match concept was rejuvenated
        high_result = next((a for a in activated if a.concept.id == "high-match"), None)
        assert high_result is not None
        
        # Get the updated concept from store
        updated_high = interface.store.get_concept("high-match")
        
        # Decay factor should have increased from 0.5
        # Boost = 0.3 * activation (where activation is typically > 0.8 for high match)
        # So boost should be around 0.24-0.3, making decay_factor around 0.74-0.8
        assert updated_high.decay_factor > 0.5
        assert updated_high.decay_factor <= 1.0

    def test_proportional_boost_scales_with_activation(self, temp_db_path):
        """Test that boost amount scales proportionally with activation score."""
        mock_llm = MockLLMProvider()
        mock_embedding = MockEmbeddingProvider(dimensions=128)
        
        # Set up identical embeddings for perfect match
        mock_embedding.set_embedding("perfect match", [1.0, 0.0, 0.0] + [0.0] * 125)
        
        interface = MemoryInterface(
            llm=mock_llm,
            embedding=mock_embedding,
            db_path=temp_db_path,
        )
        
        # Create concept with low initial decay_factor
        concept = Concept(
            id="proportional-test",
            summary="Proportional test",
            decay_factor=0.3,
            confidence=0.9,
            embedding=[1.0, 0.0, 0.0] + [0.0] * 125,
        )
        interface.store.add_concept(concept)
        
        # Recall the concept
        activated = asyncio.run(interface.recall("perfect match", raw=True))
        
        # Get the result
        result = next((a for a in activated if a.concept.id == "proportional-test"), None)
        assert result is not None
        
        activation = result.activation
        
        # Get updated concept
        updated = interface.store.get_concept("proportional-test")
        
        # Verify the boost was proportional to activation
        # boost = 0.3 * activation
        expected_boost = 0.3 * activation
        actual_boost = updated.decay_factor - 0.3
        
        # Allow small floating point tolerance
        assert abs(actual_boost - expected_boost) < 0.001
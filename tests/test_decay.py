"""Tests for memory decay and access tracking."""

import pytest
from datetime import datetime

from remind.decay import MemoryDecayer, DecayResult
from remind.retrieval import MemoryRetriever, ActivatedConcept
from remind.models import Concept, AccessEvent, Relation, RelationType


class TestAccessEventTracking:
    """Tests for access event recording during retrieval."""

    @pytest.mark.asyncio
    async def test_access_events_recorded_on_retrieve(
        self, memory_store, mock_embedding, sample_concepts_with_relations
    ):
        """Test that access events are recorded when concepts are retrieved."""
        # Add concepts to store
        for concept in sample_concepts_with_relations:
            memory_store.add_concept(concept)

        # Create retriever
        retriever = MemoryRetriever(
            embedding=mock_embedding,
            store=memory_store,
            initial_k=10,
            spread_hops=2,
            spread_decay=0.5,
            activation_threshold=0.1,
        )

        # Set embedding for query to match concept1
        mock_embedding.set_embedding(
            "python programming",
            [1.0, 0.0, 0.0] + [0.0] * 125,
        )

        # Perform retrieval
        result = await retriever.retrieve("python programming", k=3)

        # Verify access events were recorded
        access_events = memory_store.get_access_events()
        assert len(access_events) > 0

        # Verify at least concept1 was accessed
        concept_ids = {e.concept_id for e in access_events}
        assert "concept1" in concept_ids

    @pytest.mark.asyncio
    async def test_access_events_include_activation_level(
        self, memory_store, mock_embedding
    ):
        """Test that access events include correct activation levels."""
        # Add a concept
        concept = Concept(
            id="test_concept",
            summary="Test concept",
            confidence=0.9,
            embedding=[1.0, 0.0, 0.0] + [0.0] * 125,
        )
        memory_store.add_concept(concept)

        # Create retriever
        retriever = MemoryRetriever(
            embedding=mock_embedding,
            store=memory_store,
            activation_threshold=0.1,
        )

        # Set embedding for query
        mock_embedding.set_embedding("test", [1.0, 0.0, 0.0] + [0.0] * 125)

        # Perform retrieval
        await retriever.retrieve("test", k=1)

        # Check access event
        access_events = memory_store.get_access_events()
        assert len(access_events) == 1

        event = access_events[0]
        assert event.concept_id == "test_concept"
        # Activation should be high (similarity * confidence)
        assert event.activation > 0.5

    @pytest.mark.asyncio
    async def test_access_events_cleared_after_decay(
        self, memory_store, mock_embedding, sample_concepts_with_relations
    ):
        """Test that access events are cleared after decay runs."""
        # Add concepts
        for concept in sample_concepts_with_relations:
            memory_store.add_concept(concept)

        # Create retriever and perform retrieval
        retriever = MemoryRetriever(
            embedding=mock_embedding,
            store=memory_store,
            activation_threshold=0.1,
        )
        mock_embedding.set_embedding("test", [1.0, 0.0, 0.0] + [0.0] * 125)
        await retriever.retrieve("test", k=3)

        # Verify access events exist
        access_events = memory_store.get_access_events()
        assert len(access_events) > 0

        # Run decay
        decayer = MemoryDecayer(store=memory_store, decay_rate=0.95)
        decayer.decay()

        # Verify access events are cleared
        access_events = memory_store.get_access_events()
        assert len(access_events) == 0


class TestRecallCounter:
    """Tests for recall counter functionality."""

    def test_recall_counter_increments_on_retrieve(self, memory_store):
        """Test that recall counter increments on each retrieval."""
        initial_count = memory_store.get_recall_count()
        assert initial_count == 0

        memory_store.increment_recall_count()
        assert memory_store.get_recall_count() == 1

        memory_store.increment_recall_count()
        assert memory_store.get_recall_count() == 2

    def test_recall_counter_resets_after_decay(
        self, memory_store, sample_concepts_with_relations
    ):
        """Test that recall counter resets after decay runs."""
        # Increment counter
        memory_store.increment_recall_count()
        memory_store.increment_recall_count()
        assert memory_store.get_recall_count() == 2

        # Add concepts for decay
        for concept in sample_concepts_with_relations:
            memory_store.add_concept(concept)

        # Run decay
        decayer = MemoryDecayer(store=memory_store, decay_rate=0.95)
        decayer.decay()

        # Verify counter is reset
        assert memory_store.get_recall_count() == 0

    def test_decay_threshold_get_set(self, memory_store):
        """Test getting and setting decay threshold."""
        # Default threshold is 10
        assert memory_store.get_decay_threshold() == 10

        # Set new threshold
        memory_store.set_decay_threshold(5)
        assert memory_store.get_decay_threshold() == 5

        # Set back to 10
        memory_store.set_decay_threshold(10)


class TestConceptAccessFields:
    """Tests for concept access tracking fields."""

    def test_concept_has_access_fields(self, sample_concept):
        """Test that concepts have last_accessed_at and access_count fields."""
        assert hasattr(sample_concept, "last_accessed_at")
        assert hasattr(sample_concept, "access_count")
        assert sample_concept.last_accessed_at is None
        assert sample_concept.access_count == 0

    def test_access_fields_update_after_decay(
        self, memory_store, sample_concepts_with_relations
    ):
        """Test that access fields update after decay with access events."""
        # Add concepts
        for concept in sample_concepts_with_relations:
            memory_store.add_concept(concept)

        # Record access events with high activation to ensure reinforcement
        # Activation must be higher than decayed confidence to trigger reinforcement
        memory_store.record_access("concept1", 0.95)
        memory_store.record_access("concept2", 0.95)

        # Run decay
        decayer = MemoryDecayer(store=memory_store, decay_rate=0.95)
        decayer.decay()

        # Verify concept1 was updated
        updated_concept1 = memory_store.get_concept("concept1")
        assert updated_concept1.last_accessed_at is not None
        assert updated_concept1.access_count == 1

        # Verify concept2 was updated
        updated_concept2 = memory_store.get_concept("concept2")
        assert updated_concept2.last_accessed_at is not None
        assert updated_concept2.access_count == 1

    def test_access_count_increments_with_multiple_accesses(
        self, memory_store
    ):
        """Test that access_count increments with multiple decay runs."""
        # Add a concept
        concept = Concept(
            id="test_concept",
            summary="Test concept",
            confidence=0.8,
        )
        memory_store.add_concept(concept)

        # First access and decay
        memory_store.record_access("test_concept", 0.8)
        decayer = MemoryDecayer(store=memory_store, decay_rate=0.95)
        decayer.decay()

        concept = memory_store.get_concept("test_concept")
        assert concept.access_count == 1

        # Second access and decay
        memory_store.record_access("test_concept", 0.8)
        decayer.decay()

        concept = memory_store.get_concept("test_concept")
        assert concept.access_count == 2

    def test_last_accessed_at_updates_on_decay(self, memory_store):
        """Test that last_accessed_at updates to current time on decay."""
        concept = Concept(
            id="test_concept",
            summary="Test concept",
            confidence=0.8,
        )
        memory_store.add_concept(concept)

        # Record access
        memory_store.record_access("test_concept", 0.8)

        # Get time before decay
        before = datetime.now()

        # Run decay
        decayer = MemoryDecayer(store=memory_store, decay_rate=0.95)
        decayer.decay()

        # Get time after decay
        after = datetime.now()

        # Verify last_accessed_at is between before and after
        updated_concept = memory_store.get_concept("test_concept")
        assert before <= updated_concept.last_accessed_at <= after


class TestDecayResult:
    """Tests for DecayResult dataclass."""

    def test_decay_result_creation(self):
        """Test creating a DecayResult."""
        result = DecayResult(
            concepts_decayed=10,
            concepts_reinforced=3,
            access_events_processed=5,
        )
        assert result.concepts_decayed == 10
        assert result.concepts_reinforced == 3
        assert result.access_events_processed == 5
        assert result.confidence_changes == []

    def test_decay_result_to_dict(self):
        """Test serializing DecayResult to dictionary."""
        result = DecayResult(
            concepts_decayed=5,
            concepts_reinforced=2,
            access_events_processed=3,
            confidence_changes=[
                {"concept_id": "c1", "old": 0.9, "new": 0.85},
            ],
        )
        d = result.to_dict()
        assert d["concepts_decayed"] == 5
        assert d["concepts_reinforced"] == 2
        assert d["access_events_processed"] == 3
        assert len(d["confidence_changes"]) == 1
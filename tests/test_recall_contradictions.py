"""Tests for contradiction visibility on recall and timestamp formatting."""

import pytest
from datetime import datetime, timedelta

from remind.models import Concept, Episode, EpisodeType, Relation, RelationType
from remind.retrieval import MemoryRetriever, ActivatedConcept


class TestContradictionsInRecall:
    """Contradictions must always appear in format_for_llm output."""

    @pytest.fixture
    def retriever(self, memory_store, mock_embedding):
        return MemoryRetriever(embedding=mock_embedding, store=memory_store)

    def test_outbound_contradiction_shown(self, retriever, memory_store):
        """Outbound contradicts relation always appears in recall output."""
        c_target = Concept(id="target1", summary="Target concept")
        c_source = Concept(
            id="source1",
            summary="Source concept",
            relations=[
                Relation(type=RelationType.CONTRADICTS, target_id="target1", strength=0.8),
            ],
        )
        memory_store.add_concept(c_target)
        memory_store.add_concept(c_source)

        activated = [ActivatedConcept(concept=c_source, activation=0.9, source="embedding")]
        result = retriever.format_for_llm(activated)

        assert "Contradictions:" in result
        assert "contradicts [target1]" in result
        assert "Target concept" in result

    def test_inbound_contradiction_shown(self, retriever, memory_store):
        """Inbound contradicts (only on the other concept) still appears on recall."""
        c_recalled = Concept(id="recalled", summary="Recalled concept")
        c_other = Concept(
            id="other",
            summary="Other concept",
            relations=[
                Relation(type=RelationType.CONTRADICTS, target_id="recalled", strength=0.7),
            ],
        )
        memory_store.add_concept(c_recalled)
        memory_store.add_concept(c_other)

        activated = [ActivatedConcept(concept=c_recalled, activation=0.8, source="embedding")]
        result = retriever.format_for_llm(activated)

        assert "Contradictions:" in result
        assert "[other] contradicts this" in result
        assert "Other concept" in result

    def test_no_contradictions_shows_none_marker(self, retriever, memory_store):
        """When a concept has no contradictions, the marker is still present."""
        c = Concept(id="peaceful", summary="No conflicts here")
        memory_store.add_concept(c)

        activated = [ActivatedConcept(concept=c, activation=0.9, source="embedding")]
        result = retriever.format_for_llm(activated)

        assert "Contradictions: (none)" in result

    def test_contradiction_not_counted_in_max_relations(self, retriever, memory_store):
        """contradicts should not consume max_relations budget; other relations still show."""
        c_contradiction_target = Concept(id="contra", summary="Contradicting concept")
        c_implies_target = Concept(id="impl", summary="Implied concept")
        c_main = Concept(
            id="main",
            summary="Main concept",
            relations=[
                Relation(type=RelationType.CONTRADICTS, target_id="contra", strength=0.8),
                Relation(type=RelationType.IMPLIES, target_id="impl", strength=0.9),
            ],
        )
        memory_store.add_concept(c_contradiction_target)
        memory_store.add_concept(c_implies_target)
        memory_store.add_concept(c_main)

        activated = [ActivatedConcept(concept=c_main, activation=0.9, source="embedding")]
        result = retriever.format_for_llm(activated, max_relations=1)

        assert "contradicts [contra]" in result
        assert "implies:" in result
        assert "Implied concept" in result

    def test_contradiction_context_shown(self, retriever, memory_store):
        """Contradiction relation context is shown when present."""
        c_target = Concept(id="ctx_target", summary="Target")
        c_source = Concept(
            id="ctx_source",
            summary="Source",
            relations=[
                Relation(
                    type=RelationType.CONTRADICTS,
                    target_id="ctx_target",
                    strength=0.6,
                    context="only in production environments",
                ),
            ],
        )
        memory_store.add_concept(c_target)
        memory_store.add_concept(c_source)

        activated = [ActivatedConcept(concept=c_source, activation=0.8, source="embedding")]
        result = retriever.format_for_llm(activated)

        assert "only in production environments" in result

    def test_bidirectional_contradictions(self, retriever, memory_store):
        """Both outbound and inbound contradictions appear when both exist."""
        c_a = Concept(
            id="a",
            summary="Concept A",
            relations=[
                Relation(type=RelationType.CONTRADICTS, target_id="b", strength=0.8),
            ],
        )
        c_b = Concept(
            id="b",
            summary="Concept B",
            relations=[
                Relation(type=RelationType.CONTRADICTS, target_id="a", strength=0.7),
            ],
        )
        memory_store.add_concept(c_a)
        memory_store.add_concept(c_b)

        activated = [ActivatedConcept(concept=c_a, activation=0.9, source="embedding")]
        result = retriever.format_for_llm(activated)

        assert "contradicts [b]" in result
        assert "[b] contradicts this" in result


class TestTimestampsInRecall:
    """Recall output should include last-update timestamps."""

    @pytest.fixture
    def retriever(self, memory_store, mock_embedding):
        return MemoryRetriever(embedding=mock_embedding, store=memory_store)

    def test_concept_updated_at_in_header(self, retriever, memory_store):
        """Concept header includes last updated timestamp."""
        ts = datetime(2025, 6, 15, 10, 30)
        c = Concept(id="ts1", summary="Timestamped concept", updated_at=ts)
        memory_store.add_concept(c)

        activated = [ActivatedConcept(concept=c, activation=0.9, source="embedding")]
        result = retriever.format_for_llm(activated)

        assert "last updated: 2025-06-15 10:30" in result

    def test_episode_updated_at_in_source_episodes(self, retriever, memory_store):
        """Source episode lines include last updated timestamp."""
        ep_time = datetime(2025, 3, 1, 14, 0)
        ep = Episode(
            id="ep1",
            content="Some observation",
            episode_type=EpisodeType.OBSERVATION,
            created_at=ep_time,
            updated_at=ep_time,
        )
        memory_store.add_episode(ep)

        c = Concept(id="c1", summary="Concept", source_episodes=["ep1"])
        memory_store.add_concept(c)

        activated = [ActivatedConcept(concept=c, activation=0.9, source="embedding")]
        result = retriever.format_for_llm(activated, include_episodes=True)

        assert "2025-03-01 14:00" in result

    def test_entity_context_episodes_have_timestamps(self, retriever, memory_store):
        """format_entity_context includes episode timestamps."""
        from remind.models import Entity, EntityType

        entity = Entity(id="file:test.py", type=EntityType.FILE, display_name="test.py")
        memory_store.add_entity(entity)

        ep_time = datetime(2025, 5, 20, 9, 15)
        episodes = [
            Episode(
                content="Edited test.py",
                episode_type=EpisodeType.DECISION,
                created_at=ep_time,
                updated_at=ep_time,
            ),
        ]

        result = retriever.format_entity_context("file:test.py", episodes)
        assert "2025-05-20 09:15" in result


class TestEpisodeCreatedUpdated:
    """Episode model created_at / updated_at fields."""

    def test_new_episode_created_equals_updated(self):
        """Fresh episode has created_at == updated_at."""
        ep = Episode(content="test")
        assert ep.created_at == ep.updated_at

    def test_timestamp_property_returns_updated_at(self):
        """The .timestamp property returns updated_at for compat."""
        ep = Episode(content="test")
        assert ep.timestamp is ep.updated_at

    def test_timestamp_setter_updates_updated_at(self):
        """Setting .timestamp changes updated_at."""
        ep = Episode(content="test")
        new_time = datetime(2025, 1, 1, 12, 0)
        ep.timestamp = new_time
        assert ep.updated_at == new_time

    def test_to_dict_includes_all_time_fields(self):
        """to_dict emits created_at, updated_at, and legacy timestamp."""
        ep = Episode(content="test")
        d = ep.to_dict()
        assert "created_at" in d
        assert "updated_at" in d
        assert "timestamp" in d
        assert d["timestamp"] == d["updated_at"]

    def test_from_dict_legacy_timestamp_only(self):
        """Old JSON with only 'timestamp' sets created_at and updated_at from it."""
        d = {
            "id": "old1",
            "timestamp": "2024-01-15T10:00:00",
            "content": "Old episode",
        }
        ep = Episode.from_dict(d)
        assert ep.created_at == datetime(2024, 1, 15, 10, 0)
        assert ep.updated_at == ep.created_at

    def test_from_dict_with_created_and_updated(self):
        """JSON with both created_at and updated_at uses them directly."""
        d = {
            "id": "new1",
            "created_at": "2024-01-15T10:00:00",
            "updated_at": "2024-06-01T12:00:00",
            "timestamp": "2024-06-01T12:00:00",
            "content": "Updated episode",
        }
        ep = Episode.from_dict(d)
        assert ep.created_at == datetime(2024, 1, 15, 10, 0)
        assert ep.updated_at == datetime(2024, 6, 1, 12, 0)

    def test_from_dict_created_at_without_updated_at(self):
        """JSON with created_at but no updated_at defaults updated_at to created_at."""
        d = {
            "id": "partial1",
            "created_at": "2024-03-10T08:30:00",
            "content": "Partial data",
        }
        ep = Episode.from_dict(d)
        assert ep.created_at == datetime(2024, 3, 10, 8, 30)
        assert ep.updated_at == ep.created_at

    def test_serialization_roundtrip(self):
        """to_dict -> from_dict preserves created_at and updated_at."""
        created = datetime(2024, 1, 1, 0, 0)
        updated = datetime(2024, 6, 1, 12, 0)
        ep = Episode(content="roundtrip", created_at=created, updated_at=updated)

        d = ep.to_dict()
        restored = Episode.from_dict(d)

        assert restored.created_at == created
        assert restored.updated_at == updated


class TestStoreIncomingRelations:
    """SQLiteMemoryStore.get_incoming_relations works correctly."""

    def test_finds_incoming_contradicts(self, memory_store):
        """Returns concepts that contradict a given concept."""
        c_source = Concept(
            id="src",
            summary="Source",
            relations=[
                Relation(type=RelationType.CONTRADICTS, target_id="tgt", strength=0.8),
            ],
        )
        c_target = Concept(id="tgt", summary="Target")
        memory_store.add_concept(c_source)
        memory_store.add_concept(c_target)

        results = memory_store.get_incoming_relations("tgt", RelationType.CONTRADICTS)
        assert len(results) == 1
        concept, relation = results[0]
        assert concept.id == "src"
        assert relation.type == RelationType.CONTRADICTS

    def test_empty_when_no_incoming(self, memory_store):
        """Returns empty list when no incoming relations exist."""
        c = Concept(id="lonely", summary="No incoming")
        memory_store.add_concept(c)

        results = memory_store.get_incoming_relations("lonely", RelationType.CONTRADICTS)
        assert results == []

    def test_excludes_soft_deleted(self, memory_store):
        """Soft-deleted source concepts are not returned."""
        c_source = Concept(
            id="deleted_src",
            summary="Deleted source",
            relations=[
                Relation(type=RelationType.CONTRADICTS, target_id="alive_tgt", strength=0.5),
            ],
        )
        c_target = Concept(id="alive_tgt", summary="Alive target")
        memory_store.add_concept(c_source)
        memory_store.add_concept(c_target)

        memory_store.delete_concept("deleted_src")

        results = memory_store.get_incoming_relations("alive_tgt", RelationType.CONTRADICTS)
        assert results == []

    def test_filters_by_relation_type(self, memory_store):
        """Only returns relations of the requested type."""
        c_source = Concept(
            id="multi_src",
            summary="Source with multiple relation types",
            relations=[
                Relation(type=RelationType.IMPLIES, target_id="multi_tgt", strength=0.9),
                Relation(type=RelationType.CONTRADICTS, target_id="multi_tgt", strength=0.4),
            ],
        )
        c_target = Concept(id="multi_tgt", summary="Target")
        memory_store.add_concept(c_source)
        memory_store.add_concept(c_target)

        contradicts = memory_store.get_incoming_relations("multi_tgt", RelationType.CONTRADICTS)
        assert len(contradicts) == 1
        assert contradicts[0][1].type == RelationType.CONTRADICTS

        implies = memory_store.get_incoming_relations("multi_tgt", RelationType.IMPLIES)
        assert len(implies) == 1
        assert implies[0][1].type == RelationType.IMPLIES

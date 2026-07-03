"""Tests for memory store."""

import pytest
import tempfile
import os
from datetime import datetime, timedelta

from remind.models import Concept, Conflict, Episode, Fact, Relation, RelationType, Entity, EntityType, EntityRelation
from remind.store import SQLiteMemoryStore, cosine_similarity


class TestCosineSimilarity:
    def test_identical_vectors(self):
        v = [1.0, 2.0, 3.0]
        assert abs(cosine_similarity(v, v) - 1.0) < 0.001
    
    def test_orthogonal_vectors(self):
        v1 = [1.0, 0.0]
        v2 = [0.0, 1.0]
        assert abs(cosine_similarity(v1, v2)) < 0.001
    
    def test_opposite_vectors(self):
        v1 = [1.0, 2.0]
        v2 = [-1.0, -2.0]
        assert abs(cosine_similarity(v1, v2) + 1.0) < 0.001


class TestSQLiteMemoryStore:
    @pytest.fixture
    def store(self):
        """Create a temporary store for testing."""
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        store = SQLiteMemoryStore(path)
        yield store
        os.unlink(path)
    
    def test_add_and_get_concept(self, store):
        concept = Concept(
            summary="Test concept",
            confidence=0.8,
            tags=["test"],
        )
        
        concept_id = store.add_concept(concept)
        assert concept_id == concept.id
        
        retrieved = store.get_concept(concept_id)
        assert retrieved is not None
        assert retrieved.summary == "Test concept"
        assert retrieved.confidence == 0.8
        assert retrieved.tags == ["test"]
    
    def test_update_concept(self, store):
        concept = Concept(summary="Original")
        store.add_concept(concept)
        
        concept.summary = "Updated"
        concept.confidence = 0.9
        store.update_concept(concept)
        
        retrieved = store.get_concept(concept.id)
        assert retrieved.summary == "Updated"
        assert retrieved.confidence == 0.9
    
    def test_delete_concept(self, store):
        concept = Concept(summary="To delete")
        store.add_concept(concept)
        
        assert store.delete_concept(concept.id) == True
        assert store.get_concept(concept.id) is None
        assert store.delete_concept(concept.id) == False  # Already deleted
    
    def test_get_all_concepts(self, store):
        for i in range(3):
            store.add_concept(Concept(summary=f"Concept {i}"))
        
        concepts = store.get_all_concepts()
        assert len(concepts) == 3
    
    def test_get_concepts_summary(self, store):
        store.add_concept(Concept(summary="Test", confidence=0.7, tags=["a", "b"]))
        
        summaries = store.get_concepts_summary()
        assert len(summaries) == 1
        assert summaries[0]["summary"] == "Test"
        assert summaries[0]["confidence"] == 0.7
    
    def test_find_by_embedding(self, store):
        c1 = Concept(summary="Similar 1", embedding=[1.0, 0.0, 0.0])
        c2 = Concept(summary="Similar 2", embedding=[0.9, 0.1, 0.0])
        c3 = Concept(summary="Different", embedding=[0.0, 0.0, 1.0])
        
        store.add_concept(c1)
        store.add_concept(c2)
        store.add_concept(c3)
        
        # Query with vector similar to c1 and c2
        results = store.find_by_embedding([1.0, 0.0, 0.0], k=2)
        
        assert len(results) == 2
        assert results[0][0].summary == "Similar 1"  # Most similar
        assert results[0][1] > results[1][1]  # Similarity scores descending
    
    def test_relations_storage(self, store):
        c1 = Concept(summary="Concept 1")
        c2 = Concept(summary="Concept 2")
        
        store.add_concept(c1)
        store.add_concept(c2)
        
        c1.relations.append(Relation(
            type=RelationType.IMPLIES,
            target_id=c2.id,
            strength=0.8,
        ))
        store.update_concept(c1)
        
        # Verify relation is stored
        related = store.get_related(c1.id)
        assert len(related) == 1
        assert related[0][0].id == c2.id
        assert related[0][1].type == RelationType.IMPLIES
    
    def test_get_related_with_filter(self, store):
        c1 = Concept(summary="Root")
        c2 = Concept(summary="Implied")
        c3 = Concept(summary="Caused")
        
        store.add_concept(c1)
        store.add_concept(c2)
        store.add_concept(c3)
        
        c1.relations = [
            Relation(type=RelationType.IMPLIES, target_id=c2.id, strength=0.8),
            Relation(type=RelationType.CAUSES, target_id=c3.id, strength=0.7),
        ]
        store.update_concept(c1)
        
        # Get only IMPLIES relations
        related = store.get_related(c1.id, relation_types=[RelationType.IMPLIES])
        assert len(related) == 1
        assert related[0][0].id == c2.id
    
    def test_add_and_get_episode(self, store):
        episode = Episode(
            content="Test interaction",
            metadata={"source": "test"},
        )
        
        episode_id = store.add_episode(episode)
        assert episode_id == episode.id
        
        retrieved = store.get_episode(episode_id)
        assert retrieved is not None
        assert retrieved.content == "Test interaction"
        assert retrieved.metadata == {"source": "test"}
    
    def test_update_episode(self, store):
        episode = Episode(content="Original")
        store.add_episode(episode)
        
        episode.consolidated = True
        episode.summary = "Summarized"
        store.update_episode(episode)
        
        retrieved = store.get_episode(episode.id)
        assert retrieved.consolidated == True
        assert retrieved.summary == "Summarized"
    
    def test_get_unconsolidated_episodes(self, store):
        e1 = Episode(content="Unconsolidated 1")
        e2 = Episode(content="Consolidated", consolidated=True)
        e3 = Episode(content="Unconsolidated 2")
        
        store.add_episode(e1)
        store.add_episode(e2)
        store.add_episode(e3)
        
        unconsolidated = store.get_unconsolidated_episodes()
        assert len(unconsolidated) == 2
        assert all(not ep.consolidated for ep in unconsolidated)
    
    def test_get_recent_episodes(self, store):
        for i in range(5):
            store.add_episode(Episode(content=f"Episode {i}"))
        
        recent = store.get_recent_episodes(limit=3)
        assert len(recent) == 3
    
    def test_get_stats(self, store):
        store.add_concept(Concept(summary="Test"))
        store.add_episode(Episode(content="Test"))
        store.add_episode(Episode(content="Test 2"))
        
        stats = store.get_stats()
        assert stats["concepts"] == 1
        assert stats["episodes"] == 2
        assert stats["unconsolidated_episodes"] == 2
    
    def test_export_import(self, store):
        # Create some data
        c = Concept(summary="Export test", tags=["test"])
        e = Episode(content="Export episode")
        store.add_concept(c)
        store.add_episode(e)
        
        # Export
        data = store.export_data()
        assert len(data["concepts"]) == 1
        assert len(data["episodes"]) == 1
        
        # Create new store and import
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        new_store = SQLiteMemoryStore(path)
        
        result = new_store.import_data(data)
        assert result["concepts_imported"] == 1
        assert result["episodes_imported"] == 1
        
        # Verify
        assert len(new_store.get_all_concepts()) == 1
        
        os.unlink(path)

    # =========================================================================
    # Fact operations
    # =========================================================================

    def test_add_and_get_fact(self, store):
        fact = Fact(
            statement="Cache TTL is 300s",
            attribute="cache TTL",
            entity_ids=["tool:redis"],
            asserted_by="alice",
            source_ref="https://example.com/pr/1",
            source_episode_id="ep123",
        )

        fact_id = store.add_fact(fact)
        assert fact_id == fact.id

        retrieved = store.get_fact(fact_id)
        assert retrieved is not None
        assert retrieved.statement == "Cache TTL is 300s"
        assert retrieved.attribute == "cache TTL"
        assert retrieved.entity_ids == ["tool:redis"]
        assert retrieved.asserted_by == "alice"
        assert retrieved.source_ref == "https://example.com/pr/1"
        assert retrieved.source_episode_id == "ep123"
        assert retrieved.is_active
        assert retrieved.superseded_by is None

    def test_add_facts_batch(self, store):
        facts = [Fact(statement=f"Fact {i}") for i in range(3)]
        ids = store.add_facts_batch(facts)
        assert len(ids) == 3
        for fid in ids:
            assert store.get_fact(fid) is not None

    def test_get_facts_by_cluster(self, store):
        cluster = Concept(summary="Redis facts", concept_type="fact_cluster")
        store.add_concept(cluster)
        store.add_fact(Fact(cluster_id=cluster.id, statement="In cluster"))
        store.add_fact(Fact(statement="Not in cluster"))

        facts = store.get_facts(cluster_id=cluster.id)
        assert len(facts) == 1
        assert facts[0].statement == "In cluster"

    def test_get_facts_by_entity(self, store):
        store.add_fact(Fact(statement="Redis fact", entity_ids=["tool:redis", "subject:caching"]))
        store.add_fact(Fact(statement="Postgres fact", entity_ids=["tool:postgres"]))

        facts = store.get_facts(entity_id="tool:redis")
        assert len(facts) == 1
        assert facts[0].statement == "Redis fact"

    def test_supersede_fact(self, store):
        old = Fact(statement="TTL is 300s", attribute="TTL")
        new = Fact(statement="TTL is 600s", attribute="TTL")
        store.add_fact(old)
        store.add_fact(new)

        assert store.supersede_fact(old.id, new.id) is True

        superseded = store.get_fact(old.id)
        assert superseded.valid_to is not None
        assert superseded.superseded_by == new.id
        assert not superseded.is_active

        # Active-only filter excludes the superseded fact
        active = store.get_facts(active_only=True)
        assert [f.id for f in active] == [new.id]

    def test_supersede_missing_fact_returns_false(self, store):
        assert store.supersede_fact("nonexistent", "also-nonexistent") is False

    def test_get_facts_as_of(self, store):
        t0 = datetime(2026, 1, 1)
        t1 = datetime(2026, 3, 1)

        old = Fact(statement="Price is $29", attribute="price", valid_from=t0)
        new = Fact(statement="Price is $49", attribute="price", valid_from=t1)
        store.add_fact(old)
        store.add_fact(new)
        store.supersede_fact(old.id, new.id, at=t1)

        # Query between t0 and t1: only the old fact was valid
        facts = store.get_facts(as_of=datetime(2026, 2, 1))
        assert [f.id for f in facts] == [old.id]

        # Query after t1: only the new fact is valid
        facts = store.get_facts(as_of=datetime(2026, 4, 1))
        assert [f.id for f in facts] == [new.id]

        # Query before t0: nothing was valid yet
        assert store.get_facts(as_of=datetime(2025, 12, 1)) == []

    def test_delete_facts_for_cluster(self, store):
        cluster = Concept(summary="Cluster", concept_type="fact_cluster")
        store.add_concept(cluster)
        store.add_fact(Fact(cluster_id=cluster.id, statement="a"))
        store.add_fact(Fact(cluster_id=cluster.id, statement="b"))
        store.add_fact(Fact(statement="unrelated"))

        assert store.delete_facts_for_cluster(cluster.id) == 2
        assert store.get_facts(cluster_id=cluster.id) == []
        assert len(store.get_facts()) == 1

    def test_update_fact(self, store):
        fact = Fact(statement="Original", attribute=None)
        store.add_fact(fact)

        fact.statement = "Updated"
        fact.attribute = "some attr"
        store.update_fact(fact)

        retrieved = store.get_fact(fact.id)
        assert retrieved.statement == "Updated"
        assert retrieved.attribute == "some attr"

    def test_backfill_facts_from_specifics(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            store = SQLiteMemoryStore(path)
            cluster = Concept(
                summary="Legacy cluster",
                concept_type="fact_cluster",
                specifics=["TTL is 300s", "Uses Redis"],
                entity_ids=["tool:redis"],
            )
            store.add_concept(cluster)

            # Simulate a pre-facts database: drop the backfill flag and rows
            store.delete_facts_for_cluster(cluster.id)
            store.set_metadata("facts_backfill_v1", "")
            with store._connect() as conn:
                from sqlalchemy import text
                conn.execute(text("DELETE FROM metadata WHERE key='facts_backfill_v1'"))

            # Re-opening the store triggers the backfill
            store2 = SQLiteMemoryStore(path)
            facts = store2.get_facts(cluster_id=cluster.id)
            assert len(facts) == 2
            assert {f.statement for f in facts} == {"TTL is 300s", "Uses Redis"}
            assert all(f.entity_ids == ["tool:redis"] for f in facts)
            assert all(f.valid_from == cluster.created_at for f in facts)

            # Backfill is idempotent
            store3 = SQLiteMemoryStore(path)
            assert len(store3.get_facts(cluster_id=cluster.id)) == 2
        finally:
            os.unlink(path)

    def test_stats_include_fact_counts(self, store):
        a = Fact(statement="a")
        b = Fact(statement="b")
        store.add_fact(a)
        store.add_fact(b)
        store.supersede_fact(a.id, b.id)

        stats = store.get_stats()
        assert stats["facts"] == 2
        assert stats["active_facts"] == 1

    # =========================================================================
    # Conflict operations
    # =========================================================================

    def test_add_and_get_conflict(self, store):
        conflict = Conflict(
            kind="fact",
            fact_a_id="f1",
            fact_b_id="f2",
            concept_ids=["cluster1"],
            description='"TTL is 300s" vs "TTL is 600s"',
            severity="high",
        )
        conflict_id = store.add_conflict(conflict)

        retrieved = store.get_conflict(conflict_id)
        assert retrieved is not None
        assert retrieved.kind == "fact"
        assert retrieved.fact_a_id == "f1"
        assert retrieved.fact_b_id == "f2"
        assert retrieved.concept_ids == ["cluster1"]
        assert retrieved.severity == "high"
        assert retrieved.status == "open"

    def test_get_conflicts_filters(self, store):
        store.add_conflict(Conflict(kind="fact", description="a"))
        store.add_conflict(Conflict(kind="concept", concept_ids=["c1"], description="b"))
        resolved = Conflict(kind="fact", description="c", status="resolved")
        store.add_conflict(resolved)

        assert len(store.get_conflicts()) == 3
        assert len(store.get_conflicts(status="open")) == 2
        assert len(store.get_conflicts(kind="concept")) == 1
        assert len(store.get_conflicts(concept_id="c1")) == 1
        assert store.count_conflicts(status="open") == 2

    def test_update_conflict_lifecycle(self, store):
        conflict = Conflict(kind="fact", fact_a_id="f1", fact_b_id="f2", description="x")
        store.add_conflict(conflict)

        from datetime import datetime as _dt
        conflict.status = "resolved"
        conflict.resolved_at = _dt.now()
        conflict.resolution_note = "f2 is current"
        conflict.resolved_by = "alice"
        conflict.winning_fact_id = "f2"
        store.update_conflict(conflict)

        retrieved = store.get_conflict(conflict.id)
        assert retrieved.status == "resolved"
        assert retrieved.winning_fact_id == "f2"
        assert retrieved.resolved_by == "alice"
        assert retrieved.resolution_note == "f2 is current"
        assert retrieved.resolved_at is not None

    def test_find_open_conflict_for_facts(self, store):
        store.add_conflict(Conflict(kind="fact", fact_a_id="f1", fact_b_id="f2"))

        assert store.find_open_conflict_for_facts("f1", "f2") is not None
        # Order-insensitive
        assert store.find_open_conflict_for_facts("f2", "f1") is not None
        assert store.find_open_conflict_for_facts("f1", "f3") is None

    def test_backfill_conflicts_from_concept_dicts(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            store = SQLiteMemoryStore(path)
            cluster = Concept(
                summary="Cluster with conflict",
                concept_type="fact_cluster",
                specifics=["TTL is 300s", "TTL is 600s"],
                conflicts=[{
                    "fact_a": "TTL is 300s",
                    "fact_b": "TTL is 600s",
                    "reason": "contradictory values",
                    "detected_at": "2026-01-01T00:00:00",
                }],
            )
            store.add_concept(cluster)
            fact_a = Fact(cluster_id=cluster.id, statement="TTL is 300s")
            fact_b = Fact(cluster_id=cluster.id, statement="TTL is 600s")
            store.add_fact(fact_a)
            store.add_fact(fact_b)

            # Simulate a pre-conflicts database: remove the backfill flag
            with store._connect() as conn:
                from sqlalchemy import text
                conn.execute(text("DELETE FROM metadata WHERE key='conflicts_backfill_v1'"))
                conn.execute(text("DELETE FROM conflicts"))

            store2 = SQLiteMemoryStore(path)
            conflicts = store2.get_conflicts(status="open")
            assert len(conflicts) == 1
            c = conflicts[0]
            assert c.kind == "fact"
            assert c.concept_ids == [cluster.id]
            # Statements resolved to fact row IDs
            assert {c.fact_a_id, c.fact_b_id} == {fact_a.id, fact_b.id}
            assert "contradictory values" in c.description

            # Idempotent
            store3 = SQLiteMemoryStore(path)
            assert len(store3.get_conflicts()) == 1
        finally:
            os.unlink(path)

    def test_merge_duplicate_entities_merges_mentions_and_relations(self, store):
        canonical = Entity(id="other:act", type=EntityType.OTHER, display_name="act")
        duplicate = Entity(id="legal_act:act", type=EntityType.OTHER, display_name="act")
        target = Entity(id="subject:law", type=EntityType.SUBJECT, display_name="law")
        store.add_entity(canonical)
        store.add_entity(duplicate)
        store.add_entity(target)

        ep = Episode(content="Act reference")
        store.add_episode(ep)
        store.add_mention(ep.id, canonical.id)
        store.add_mention(ep.id, duplicate.id)

        store.add_entity_relation(
            EntityRelation(
                source_id=duplicate.id,
                target_id=target.id,
                relation_type="governs",
                strength=0.8,
                source_episode_id=ep.id,
            )
        )

        stats = store.merge_duplicate_entities()

        assert stats["groups_merged"] == 1
        assert stats["entities_removed"] == 1
        assert store.get_entity("legal_act:act") is None
        episodes = store.get_episodes_mentioning("other:act")
        assert len(episodes) == 1
        rels = store.get_entity_relations("other:act")
        assert any(r.target_id == "subject:law" for r in rels)


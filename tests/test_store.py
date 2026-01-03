"""Tests for memory store."""

import pytest
import tempfile
import os

from remind.models import Concept, Episode, Relation, RelationType
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


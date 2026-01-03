"""Tests for data models."""

import pytest
from datetime import datetime

from remind.models import (
    Concept,
    Episode,
    Relation,
    RelationType,
    ConsolidationResult,
)


class TestRelationType:
    def test_all_types_exist(self):
        """Ensure all expected relation types exist."""
        expected = [
            "implies", "contradicts", "specializes", "generalizes",
            "causes", "correlates", "part_of", "context_of"
        ]
        for name in expected:
            assert RelationType(name) is not None


class TestRelation:
    def test_creation(self):
        rel = Relation(
            type=RelationType.IMPLIES,
            target_id="abc123",
            strength=0.8,
            context="when coding"
        )
        assert rel.type == RelationType.IMPLIES
        assert rel.target_id == "abc123"
        assert rel.strength == 0.8
        assert rel.context == "when coding"
    
    def test_to_dict(self):
        rel = Relation(
            type=RelationType.CAUSES,
            target_id="xyz",
            strength=0.5,
        )
        d = rel.to_dict()
        assert d["type"] == "causes"
        assert d["target_id"] == "xyz"
        assert d["strength"] == 0.5
    
    def test_from_dict(self):
        d = {
            "type": "implies",
            "target_id": "test",
            "strength": 0.9,
            "context": "always",
        }
        rel = Relation.from_dict(d)
        assert rel.type == RelationType.IMPLIES
        assert rel.target_id == "test"
        assert rel.strength == 0.9
        assert rel.context == "always"


class TestConcept:
    def test_creation_with_defaults(self):
        concept = Concept(summary="Test concept")
        assert concept.summary == "Test concept"
        assert concept.confidence == 0.5
        assert concept.instance_count == 1
        assert len(concept.id) == 8
        assert concept.relations == []
        assert concept.tags == []
    
    def test_serialization_roundtrip(self):
        concept = Concept(
            summary="Test concept",
            confidence=0.8,
            tags=["test", "example"],
            conditions="when testing",
        )
        concept.relations.append(Relation(
            type=RelationType.IMPLIES,
            target_id="other",
            strength=0.7,
        ))
        
        d = concept.to_dict()
        restored = Concept.from_dict(d)
        
        assert restored.summary == concept.summary
        assert restored.confidence == concept.confidence
        assert restored.tags == concept.tags
        assert restored.conditions == concept.conditions
        assert len(restored.relations) == 1
        assert restored.relations[0].target_id == "other"
    
    def test_add_relation(self):
        concept = Concept(summary="Test")
        
        # Add first relation
        concept.add_relation(Relation(
            type=RelationType.IMPLIES,
            target_id="a",
            strength=0.5,
        ))
        assert len(concept.relations) == 1
        
        # Add different relation
        concept.add_relation(Relation(
            type=RelationType.CAUSES,
            target_id="b",
            strength=0.6,
        ))
        assert len(concept.relations) == 2
        
        # Update existing relation (same type + target)
        concept.add_relation(Relation(
            type=RelationType.IMPLIES,
            target_id="a",
            strength=0.9,
        ))
        assert len(concept.relations) == 2
        assert concept.relations[0].strength == 0.9
    
    def test_get_relations_by_type(self):
        concept = Concept(summary="Test")
        concept.relations = [
            Relation(type=RelationType.IMPLIES, target_id="a", strength=0.5),
            Relation(type=RelationType.IMPLIES, target_id="b", strength=0.6),
            Relation(type=RelationType.CAUSES, target_id="c", strength=0.7),
        ]
        
        implies_rels = concept.get_relations_by_type(RelationType.IMPLIES)
        assert len(implies_rels) == 2
        
        causes_rels = concept.get_relations_by_type(RelationType.CAUSES)
        assert len(causes_rels) == 1


class TestEpisode:
    def test_creation_with_defaults(self):
        episode = Episode(content="Test interaction")
        assert episode.content == "Test interaction"
        assert episode.consolidated == False
        assert len(episode.id) == 8
        assert episode.concepts_activated == []
    
    def test_serialization_roundtrip(self):
        episode = Episode(
            content="Test content",
            summary="Test summary",
            consolidated=True,
            metadata={"key": "value"},
        )
        
        d = episode.to_dict()
        restored = Episode.from_dict(d)
        
        assert restored.content == episode.content
        assert restored.summary == episode.summary
        assert restored.consolidated == episode.consolidated
        assert restored.metadata == episode.metadata


class TestConsolidationResult:
    def test_creation_with_defaults(self):
        result = ConsolidationResult()
        assert result.episodes_processed == 0
        assert result.concepts_created == 0
        assert result.concepts_updated == 0
        assert result.contradictions_found == 0
        assert result.created_concept_ids == []


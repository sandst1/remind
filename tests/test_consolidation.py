"""Tests for consolidation engine."""

import pytest
from datetime import datetime

from remind.consolidation import Consolidator
from remind.models import (
    Concept, Episode, EpisodeType, Relation, RelationType,
    ConsolidationResult,
)


class TestConsolidator:
    """Tests for Consolidator class."""

    @pytest.fixture
    def consolidator(self, mock_llm, mock_embedding, memory_store):
        """Create a consolidator with mocks."""
        return Consolidator(
            llm=mock_llm,
            embedding=mock_embedding,
            store=memory_store,
            batch_size=20,
            min_confidence=0.3,
        )

    @pytest.mark.asyncio
    async def test_consolidate_empty_store(self, consolidator):
        """Test consolidation with no episodes."""
        result = await consolidator.consolidate()

        assert result.episodes_processed == 0
        assert result.concepts_created == 0

    @pytest.mark.asyncio
    async def test_consolidate_fewer_than_threshold(self, consolidator, memory_store):
        """Test consolidation waits for minimum episodes."""
        # Add only 2 episodes (default needs 3)
        memory_store.add_episode(Episode(content="Episode 1", entities_extracted=True))
        memory_store.add_episode(Episode(content="Episode 2", entities_extracted=True))

        result = await consolidator.consolidate(force=False)

        # Should not process without force
        assert result.episodes_processed == 0

    @pytest.mark.asyncio
    async def test_consolidate_with_force(
        self, consolidator, memory_store, mock_llm, mock_embedding
    ):
        """Test forced consolidation with few episodes."""
        # Add 2 episodes
        e1 = Episode(content="User likes Python", entities_extracted=True)
        e2 = Episode(content="User prefers async", entities_extracted=True)
        memory_store.add_episode(e1)
        memory_store.add_episode(e2)

        # Set up mock response
        mock_llm.set_complete_json_response({
            "analysis": "User has programming preferences",
            "updates": [],
            "new_concepts": [
                {
                    "summary": "User prefers Python with async patterns",
                    "confidence": 0.7,
                    "source_episodes": [e1.id, e2.id],
                    "tags": ["programming", "preferences"],
                    "relations": [],
                }
            ],
            "new_relations": [],
            "contradictions": [],
        })

        result = await consolidator.consolidate(force=True)

        assert result.episodes_processed == 2
        assert result.concepts_created == 1

        # Verify concept was stored
        concepts = memory_store.get_all_concepts()
        assert len(concepts) == 1
        assert "Python" in concepts[0].summary

    @pytest.mark.asyncio
    async def test_consolidate_creates_concepts(
        self, consolidator, memory_store, mock_llm, mock_embedding, sample_episodes
    ):
        """Test consolidation creates new concepts."""
        for ep in sample_episodes:
            memory_store.add_episode(ep)

        mock_llm.set_complete_json_response({
            "analysis": "Multiple programming preferences observed",
            "updates": [],
            "new_concepts": [
                {
                    "summary": "User strongly prefers Python for backend development",
                    "confidence": 0.85,
                    "source_episodes": [sample_episodes[0].id],
                    "tags": ["programming", "python"],
                    "conditions": "for backend work",
                    "exceptions": [],
                    "relations": [],
                },
                {
                    "summary": "User values code readability over performance",
                    "confidence": 0.75,
                    "source_episodes": [sample_episodes[4].id],
                    "tags": ["code-quality"],
                    "relations": [],
                },
            ],
            "new_relations": [],
            "contradictions": [],
        })

        result = await consolidator.consolidate()

        assert result.concepts_created == 2
        assert len(result.created_concept_ids) == 2

        # Verify embeddings were generated
        calls = mock_embedding.get_call_history()
        assert len(calls) >= 2

    @pytest.mark.asyncio
    async def test_consolidate_creates_concept_with_conditions(
        self, consolidator, memory_store, mock_llm, mock_embedding
    ):
        """Test that concept conditions are preserved."""
        for i in range(3):
            ep = Episode(content=f"Episode {i}", entities_extracted=True)
            memory_store.add_episode(ep)

        mock_llm.set_complete_json_response({
            "analysis": "Test",
            "updates": [],
            "new_concepts": [
                {
                    "summary": "User prefers tabs",
                    "confidence": 0.7,
                    "conditions": "when writing Python code",
                    "exceptions": ["except for YAML files"],
                    "tags": [],
                    "relations": [],
                }
            ],
            "new_relations": [],
            "contradictions": [],
        })

        await consolidator.consolidate()

        concept = memory_store.get_all_concepts()[0]
        assert concept.conditions == "when writing Python code"
        assert "except for YAML files" in concept.exceptions

    @pytest.mark.asyncio
    async def test_consolidate_updates_existing_concepts(
        self, consolidator, memory_store, mock_llm, mock_embedding
    ):
        """Test consolidation updates existing concepts."""
        # Add existing concept
        existing = Concept(
            id="existing1",
            summary="User likes Python",
            confidence=0.6,
            embedding=[0.1] * 128,
        )
        memory_store.add_concept(existing)

        # Add new episodes
        e1 = Episode(content="User again chose Python", entities_extracted=True)
        e2 = Episode(content="Python was selected", entities_extracted=True)
        e3 = Episode(content="Another Python choice", entities_extracted=True)
        memory_store.add_episode(e1)
        memory_store.add_episode(e2)
        memory_store.add_episode(e3)

        mock_llm.set_complete_json_response({
            "analysis": "More evidence of Python preference",
            "updates": [
                {
                    "concept_id": "existing1",
                    "new_summary": "User consistently prefers Python for all projects",
                    "confidence_delta": 0.2,
                    "add_exceptions": ["except for mobile"],
                    "add_tags": ["strong-preference"],
                    "reasoning": "Multiple confirmations",
                }
            ],
            "new_concepts": [],
            "new_relations": [],
            "contradictions": [],
        })

        result = await consolidator.consolidate()

        assert result.concepts_updated == 1

        # Verify concept was updated
        updated = memory_store.get_concept("existing1")
        assert "consistently" in updated.summary
        assert updated.confidence == pytest.approx(0.8, abs=0.01)
        assert "except for mobile" in updated.exceptions
        assert "strong-preference" in updated.tags

    @pytest.mark.asyncio
    async def test_consolidate_update_increments_instance_count(
        self, consolidator, memory_store, mock_llm, mock_embedding
    ):
        """Test that updates increment instance count."""
        existing = Concept(
            id="existing1",
            summary="Test concept",
            instance_count=3,
            embedding=[0.1] * 128,
        )
        memory_store.add_concept(existing)

        for i in range(3):
            memory_store.add_episode(Episode(content=f"Ep {i}", entities_extracted=True))

        mock_llm.set_complete_json_response({
            "analysis": "Test",
            "updates": [
                {
                    "concept_id": "existing1",
                    "confidence_delta": 0.1,
                }
            ],
            "new_concepts": [],
            "new_relations": [],
            "contradictions": [],
        })

        await consolidator.consolidate()

        updated = memory_store.get_concept("existing1")
        assert updated.instance_count == 4

    @pytest.mark.asyncio
    async def test_consolidate_adds_relations(
        self, consolidator, memory_store, mock_llm, mock_embedding
    ):
        """Test consolidation adds relations between concepts."""
        # Add existing concepts
        c1 = Concept(id="concept_a", summary="User likes Python", embedding=[0.1] * 128)
        c2 = Concept(id="concept_b", summary="User prefers type hints", embedding=[0.1] * 128)
        memory_store.add_concept(c1)
        memory_store.add_concept(c2)

        # Add episodes
        for i in range(3):
            ep = Episode(content=f"Episode {i}", entities_extracted=True)
            memory_store.add_episode(ep)

        mock_llm.set_complete_json_response({
            "analysis": "Found relation between concepts",
            "updates": [],
            "new_concepts": [],
            "new_relations": [
                {
                    "source_id": "concept_a",
                    "target_id": "concept_b",
                    "type": "implies",
                    "strength": 0.8,
                    "context": "type hints are common in Python",
                }
            ],
            "contradictions": [],
        })

        await consolidator.consolidate()

        # Verify relation was added
        updated = memory_store.get_concept("concept_a")
        assert len(updated.relations) == 1
        assert updated.relations[0].type == RelationType.IMPLIES
        assert updated.relations[0].target_id == "concept_b"

    @pytest.mark.asyncio
    async def test_consolidate_creates_concept_with_relations(
        self, consolidator, memory_store, mock_llm, mock_embedding
    ):
        """Test new concepts can have relations."""
        # Add existing concept
        existing = Concept(id="existing", summary="Existing concept", embedding=[0.1] * 128)
        memory_store.add_concept(existing)

        for i in range(3):
            memory_store.add_episode(Episode(content=f"Ep {i}", entities_extracted=True))

        mock_llm.set_complete_json_response({
            "analysis": "Test",
            "updates": [],
            "new_concepts": [
                {
                    "summary": "New concept",
                    "confidence": 0.7,
                    "tags": [],
                    "relations": [
                        {
                            "type": "specializes",
                            "target_id": "existing",
                            "strength": 0.9,
                            "context": "more specific case",
                        }
                    ],
                }
            ],
            "new_relations": [],
            "contradictions": [],
        })

        await consolidator.consolidate()

        new_concept = [c for c in memory_store.get_all_concepts() if c.id != "existing"][0]
        assert len(new_concept.relations) == 1
        assert new_concept.relations[0].type == RelationType.SPECIALIZES

    @pytest.mark.asyncio
    async def test_consolidate_handles_contradictions(
        self, consolidator, memory_store, mock_llm, mock_embedding
    ):
        """Test consolidation reports contradictions."""
        # Add existing concept
        existing = Concept(id="existing1", summary="User dislikes JavaScript", embedding=[0.1] * 128)
        memory_store.add_concept(existing)

        # Add contradicting episode
        for i in range(3):
            memory_store.add_episode(Episode(content=f"Ep {i}", entities_extracted=True))

        mock_llm.set_complete_json_response({
            "analysis": "Found contradiction",
            "updates": [],
            "new_concepts": [],
            "new_relations": [],
            "contradictions": [
                {
                    "concept_id": "existing1",
                    "evidence": "User enjoyed building a React app",
                    "resolution": "May depend on context",
                }
            ],
        })

        result = await consolidator.consolidate()

        assert result.contradictions_found == 1
        assert len(result.contradiction_details) == 1
        assert result.contradiction_details[0]["concept_id"] == "existing1"

    @pytest.mark.asyncio
    async def test_consolidate_marks_episodes_consolidated(
        self, consolidator, memory_store, mock_llm, mock_embedding
    ):
        """Test episodes are marked as consolidated."""
        episodes = []
        for i in range(3):
            ep = Episode(content=f"Episode {i}", entities_extracted=True)
            memory_store.add_episode(ep)
            episodes.append(ep)

        mock_llm.set_complete_json_response({
            "analysis": "Processed",
            "updates": [],
            "new_concepts": [],
            "new_relations": [],
            "contradictions": [],
        })

        await consolidator.consolidate()

        # All episodes should be marked consolidated
        for ep in episodes:
            updated = memory_store.get_episode(ep.id)
            assert updated.consolidated == True

    @pytest.mark.asyncio
    async def test_consolidate_skips_low_confidence_concepts(
        self, consolidator, memory_store, mock_llm, mock_embedding
    ):
        """Test low confidence concepts are not created."""
        for i in range(3):
            ep = Episode(content=f"Episode {i}", entities_extracted=True)
            memory_store.add_episode(ep)

        mock_llm.set_complete_json_response({
            "analysis": "Low confidence observations",
            "updates": [],
            "new_concepts": [
                {
                    "summary": "Very uncertain concept",
                    "confidence": 0.1,  # Below min_confidence threshold of 0.3
                    "tags": [],
                    "relations": [],
                }
            ],
            "new_relations": [],
            "contradictions": [],
        })

        result = await consolidator.consolidate()

        # Concept should not be created due to low confidence
        assert result.concepts_created == 0
        assert len(memory_store.get_all_concepts()) == 0

    @pytest.mark.asyncio
    async def test_consolidate_clamps_confidence_update(
        self, consolidator, memory_store, mock_llm, mock_embedding
    ):
        """Test confidence is clamped to valid range during updates."""
        existing = Concept(
            id="existing1",
            summary="Test",
            confidence=0.9,
            embedding=[0.1] * 128,
        )
        memory_store.add_concept(existing)

        for i in range(3):
            memory_store.add_episode(Episode(content=f"Ep {i}", entities_extracted=True))

        mock_llm.set_complete_json_response({
            "analysis": "Test",
            "updates": [
                {
                    "concept_id": "existing1",
                    "confidence_delta": 0.5,  # Would push to 1.4
                }
            ],
            "new_concepts": [],
            "new_relations": [],
            "contradictions": [],
        })

        await consolidator.consolidate()

        updated = memory_store.get_concept("existing1")
        assert updated.confidence == 1.0  # Clamped to max

    @pytest.mark.asyncio
    async def test_consolidate_handles_missing_concept_for_update(
        self, consolidator, memory_store, mock_llm, mock_embedding
    ):
        """Test update to nonexistent concept is handled gracefully."""
        for i in range(3):
            memory_store.add_episode(Episode(content=f"Ep {i}", entities_extracted=True))

        mock_llm.set_complete_json_response({
            "analysis": "Test",
            "updates": [
                {
                    "concept_id": "nonexistent",
                    "confidence_delta": 0.1,
                }
            ],
            "new_concepts": [],
            "new_relations": [],
            "contradictions": [],
        })

        result = await consolidator.consolidate()

        # Counter still incremented (tracks attempts), but concept not actually changed
        # Verify no concept was created
        assert len(memory_store.get_all_concepts()) == 0

    @pytest.mark.asyncio
    async def test_consolidate_handles_missing_target_for_relation(
        self, consolidator, memory_store, mock_llm, mock_embedding
    ):
        """Test relation to nonexistent target is handled gracefully."""
        source = Concept(id="source", summary="Source", embedding=[0.1] * 128)
        memory_store.add_concept(source)

        for i in range(3):
            memory_store.add_episode(Episode(content=f"Ep {i}", entities_extracted=True))

        mock_llm.set_complete_json_response({
            "analysis": "Test",
            "updates": [],
            "new_concepts": [],
            "new_relations": [
                {
                    "source_id": "source",
                    "target_id": "nonexistent",
                    "type": "implies",
                    "strength": 0.8,
                }
            ],
            "contradictions": [],
        })

        # Should not raise
        await consolidator.consolidate()

        # Relation should not be added
        source = memory_store.get_concept("source")
        assert len(source.relations) == 0


class TestConsolidatorFormatting:
    """Tests for Consolidator formatting methods."""

    @pytest.fixture
    def consolidator(self, mock_llm, mock_embedding, memory_store):
        return Consolidator(
            llm=mock_llm,
            embedding=mock_embedding,
            store=memory_store,
        )

    def test_format_concepts_empty(self, consolidator):
        """Test formatting empty concept list."""
        result = consolidator._format_concepts([])
        assert "No existing concepts" in result

    def test_format_concepts_with_data(self, consolidator):
        """Test formatting concepts."""
        concepts = [
            {
                "id": "abc123",
                "summary": "User prefers Python",
                "confidence": 0.8,
                "instance_count": 3,
                "tags": ["programming"],
            }
        ]

        result = consolidator._format_concepts(concepts)

        assert "[abc123]" in result
        assert "conf: 0.80" in result
        assert "n=3" in result
        assert "programming" in result
        assert "User prefers Python" in result

    def test_format_concepts_without_tags(self, consolidator):
        """Test formatting concepts without tags."""
        concepts = [
            {
                "id": "abc123",
                "summary": "Test",
                "confidence": 0.5,
                "instance_count": 1,
                "tags": [],
            }
        ]

        result = consolidator._format_concepts(concepts)
        assert "[abc123]" in result
        assert "Test" in result

    def test_format_episodes(self, consolidator, sample_episodes):
        """Test formatting episodes."""
        result = consolidator._format_episodes(sample_episodes)

        assert "User prefers Python" in result
        assert "type=preference" in result
        assert "---" in result  # Separator

    def test_format_episodes_includes_entities(self, consolidator):
        """Test formatting episodes with entities."""
        episodes = [
            Episode(
                content="Test content",
                episode_type=EpisodeType.OBSERVATION,
                entity_ids=["file:test.py", "person:alice"],
            )
        ]

        result = consolidator._format_episodes(episodes)

        assert "file:test.py" in result
        assert "person:alice" in result

    def test_format_episodes_includes_low_confidence(self, consolidator):
        """Test formatting episodes with low confidence."""
        episodes = [
            Episode(
                content="Uncertain info",
                confidence=0.5,
            )
        ]

        result = consolidator._format_episodes(episodes)
        assert "conf=0.5" in result


class TestAnalyzeContradictions:
    """Tests for contradiction analysis."""

    @pytest.fixture
    def consolidator(self, mock_llm, mock_embedding, memory_store):
        return Consolidator(
            llm=mock_llm,
            embedding=mock_embedding,
            store=memory_store,
        )

    @pytest.mark.asyncio
    async def test_analyze_contradictions_empty(self, consolidator):
        """Test analysis with no concepts."""
        result = await consolidator.analyze_contradictions()
        assert result == []

    @pytest.mark.asyncio
    async def test_analyze_contradictions_single_concept(
        self, consolidator, memory_store
    ):
        """Test analysis with only one concept."""
        memory_store.add_concept(Concept(summary="Single concept"))

        result = await consolidator.analyze_contradictions()
        assert result == []

    @pytest.mark.asyncio
    async def test_analyze_contradictions_finds_issues(
        self, consolidator, memory_store, mock_llm
    ):
        """Test analysis finds contradictions."""
        c1 = Concept(id="c1", summary="User likes tabs")
        c2 = Concept(id="c2", summary="User likes spaces")
        memory_store.add_concept(c1)
        memory_store.add_concept(c2)

        mock_llm.set_complete_json_response({
            "contradictions": [
                {
                    "concept_ids": ["c1", "c2"],
                    "description": "Cannot prefer both tabs and spaces",
                    "severity": "medium",
                    "suggested_resolution": "Clarify context",
                }
            ],
            "missing_relations": [],
            "refinement_suggestions": [],
        })

        result = await consolidator.analyze_contradictions()

        assert len(result) == 1
        assert "c1" in result[0]["concept_ids"]
        assert "c2" in result[0]["concept_ids"]

    @pytest.mark.asyncio
    async def test_analyze_contradictions_includes_conditions(
        self, consolidator, memory_store, mock_llm
    ):
        """Test analysis includes concept conditions in prompt."""
        c1 = Concept(
            id="c1",
            summary="Test",
            conditions="when writing Python",
            exceptions=["except for scripts"],
        )
        c2 = Concept(id="c2", summary="Another")
        memory_store.add_concept(c1)
        memory_store.add_concept(c2)

        mock_llm.set_complete_json_response({
            "contradictions": [],
            "missing_relations": [],
            "refinement_suggestions": [],
        })

        await consolidator.analyze_contradictions()

        # Check the prompt included conditions
        call = mock_llm.get_call_history()[0]
        assert "when writing Python" in call["prompt"]
        assert "except for scripts" in call["prompt"]

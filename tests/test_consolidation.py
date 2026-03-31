"""Tests for consolidation engine."""

import pytest
from datetime import datetime

from remind.consolidation import Consolidator
from remind.models import (
    Concept, Episode, EpisodeType, Relation, RelationType,
    ConsolidationResult,
)
from tests.conftest import make_consolidation_response


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

        assert "[c-abc123]" in result
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
        assert "[c-abc123]" in result
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


class TestConceptChunking:
    """Tests for batched concept chunking during consolidation."""

    @pytest.fixture
    def consolidator(self, mock_llm, mock_embedding, memory_store):
        return Consolidator(
            llm=mock_llm,
            embedding=mock_embedding,
            store=memory_store,
            concepts_per_consolidation_pass=3,
        )

    def test_partition_concepts_empty(self, consolidator):
        result = consolidator._partition_concepts([])
        assert result == [[]]

    def test_partition_concepts_under_limit(self, consolidator):
        concepts = [
            {"id": "b", "summary": "B"},
            {"id": "a", "summary": "A"},
        ]
        result = consolidator._partition_concepts(concepts)
        assert len(result) == 1
        assert [c["id"] for c in result[0]] == ["a", "b"]

    def test_partition_concepts_exact_limit(self, consolidator):
        concepts = [{"id": f"c{i}", "summary": f"S{i}"} for i in range(3)]
        result = consolidator._partition_concepts(concepts)
        assert len(result) == 1
        assert len(result[0]) == 3

    def test_partition_concepts_multiple_chunks(self, consolidator):
        concepts = [{"id": f"c{i:02d}", "summary": f"S{i}"} for i in range(7)]
        result = consolidator._partition_concepts(concepts)
        assert len(result) == 3
        assert len(result[0]) == 3
        assert len(result[1]) == 3
        assert len(result[2]) == 1
        # Sorted by id
        all_ids = [c["id"] for chunk in result for c in chunk]
        assert all_ids == sorted(all_ids)

    def test_partition_concepts_stable_sort(self, consolidator):
        concepts = [
            {"id": "z", "summary": "Z"},
            {"id": "a", "summary": "A"},
            {"id": "m", "summary": "M"},
            {"id": "b", "summary": "B"},
        ]
        result = consolidator._partition_concepts(concepts)
        assert len(result) == 2
        assert [c["id"] for c in result[0]] == ["a", "b", "m"]
        assert [c["id"] for c in result[1]] == ["z"]

    def test_format_concept_index_empty(self, consolidator):
        assert consolidator._format_concept_index([]) == ""

    def test_format_concept_index_with_titles(self, consolidator):
        concepts = [
            {"id": "c1", "title": "First concept"},
            {"id": "c2", "title": None},
            {"id": "c3", "title": "Third"},
        ]
        result = consolidator._format_concept_index(concepts)
        assert "[c-c1] First concept" in result
        assert "[c-c2]" in result
        assert "[c-c3] Third" in result

    @pytest.mark.asyncio
    async def test_single_chunk_single_llm_call(
        self, consolidator, memory_store, mock_llm, mock_embedding
    ):
        """When concepts fit in one chunk, only one LLM call is made."""
        # 2 concepts, limit is 3 -> single chunk
        for i in range(2):
            memory_store.add_concept(Concept(
                id=f"existing_{i}",
                summary=f"Concept {i}",
                embedding=[0.1] * 128,
            ))
        for i in range(3):
            memory_store.add_episode(Episode(content=f"Ep {i}", entities_extracted=True))

        mock_llm.set_complete_json_response(make_consolidation_response(
            analysis="Single-chunk pass",
            new_concepts=[{
                "temp_id": "NEW_0",
                "summary": "Brand new concept",
                "confidence": 0.7,
                "tags": [],
                "relations": [],
            }],
        ))

        result = await consolidator.consolidate()

        json_calls = [c for c in mock_llm.get_call_history() if c["method"] == "complete_json"]
        assert len(json_calls) == 1
        assert result.concepts_created == 1

    @pytest.mark.asyncio
    async def test_multi_chunk_multiple_llm_calls(
        self, consolidator, memory_store, mock_llm, mock_embedding
    ):
        """When concepts exceed limit, multiple LLM calls are made and results merged."""
        # 5 concepts, limit is 3 -> 2 chunks (3 + 2)
        for i in range(5):
            memory_store.add_concept(Concept(
                id=f"c{i:02d}",
                summary=f"Existing concept {i}",
                embedding=[0.1] * 128,
            ))
        for i in range(3):
            memory_store.add_episode(Episode(content=f"Ep {i}", entities_extracted=True))

        mock_llm.set_complete_json_responses([
            make_consolidation_response(
                analysis="Chunk 0 analysis",
                updates=[{
                    "concept_id": "c00",
                    "confidence_delta": 0.1,
                }],
                new_concepts=[{
                    "temp_id": "NEW_0",
                    "summary": "New from chunk 0",
                    "confidence": 0.7,
                    "tags": [],
                    "relations": [],
                }],
            ),
            make_consolidation_response(
                analysis="Chunk 1 analysis",
                new_concepts=[{
                    "temp_id": "NEW_0",
                    "summary": "New from chunk 1",
                    "confidence": 0.6,
                    "tags": [],
                    "relations": [],
                }],
                contradictions=[{
                    "concept_id": "c03",
                    "evidence": "Episode contradicts it",
                    "resolution": None,
                }],
            ),
        ])

        result = await consolidator.consolidate()

        json_calls = [c for c in mock_llm.get_call_history() if c["method"] == "complete_json"]
        assert len(json_calls) == 2
        assert result.concepts_created == 2
        assert result.concepts_updated == 1
        assert result.contradictions_found == 1

        all_concepts = memory_store.get_all_concepts()
        new_summaries = {c.summary for c in all_concepts if not c.id.startswith("c0")}
        assert "New from chunk 0" in new_summaries
        assert "New from chunk 1" in new_summaries

    @pytest.mark.asyncio
    async def test_multi_chunk_temp_id_namespacing(
        self, consolidator, memory_store, mock_llm, mock_embedding
    ):
        """Temp IDs from different chunks don't collide after namespacing."""
        for i in range(5):
            memory_store.add_concept(Concept(
                id=f"c{i:02d}",
                summary=f"Concept {i}",
                embedding=[0.1] * 128,
            ))
        for i in range(3):
            memory_store.add_episode(Episode(content=f"Ep {i}", entities_extracted=True))

        # Both chunks emit NEW_0 -> should become NEW__c0__0 and NEW__c1__0
        mock_llm.set_complete_json_responses([
            make_consolidation_response(
                new_concepts=[{
                    "temp_id": "NEW_0",
                    "summary": "Chunk0 concept",
                    "confidence": 0.7,
                    "tags": [],
                    "relations": [],
                }],
                new_relations=[{
                    "source_id": "NEW_0",
                    "target_id": "c00",
                    "type": "specializes",
                    "strength": 0.8,
                }],
            ),
            make_consolidation_response(
                new_concepts=[{
                    "temp_id": "NEW_0",
                    "summary": "Chunk1 concept",
                    "confidence": 0.6,
                    "tags": [],
                    "relations": [],
                }],
            ),
        ])

        result = await consolidator.consolidate()

        assert result.concepts_created == 2
        all_concepts = memory_store.get_all_concepts()
        new_concepts = [c for c in all_concepts if "Chunk" in c.summary]
        assert len(new_concepts) == 2
        # The first concept should have a relation to c00
        chunk0_concept = next(c for c in new_concepts if "Chunk0" in c.summary)
        assert len(chunk0_concept.relations) == 1
        assert chunk0_concept.relations[0].target_id == "c00"

    @pytest.mark.asyncio
    async def test_multi_chunk_includes_other_concepts_index(
        self, consolidator, memory_store, mock_llm, mock_embedding
    ):
        """Each sub-pass prompt contains an index of concepts from other chunks."""
        for i in range(5):
            memory_store.add_concept(Concept(
                id=f"c{i:02d}",
                title=f"Title {i}",
                summary=f"Concept {i}",
                embedding=[0.1] * 128,
            ))
        for i in range(3):
            memory_store.add_episode(Episode(content=f"Ep {i}", entities_extracted=True))

        mock_llm.set_complete_json_response(make_consolidation_response())

        await consolidator.consolidate()

        json_calls = [c for c in mock_llm.get_call_history() if c["method"] == "complete_json"]
        assert len(json_calls) == 2

        # First chunk (c00, c01, c02) should have c03, c04 in "OTHER" index
        assert "OTHER KNOWN CONCEPTS" in json_calls[0]["prompt"]
        assert "[c-c03]" in json_calls[0]["prompt"]
        assert "[c-c04]" in json_calls[0]["prompt"]

        # Second chunk (c03, c04) should have c00, c01, c02 in "OTHER" index
        assert "OTHER KNOWN CONCEPTS" in json_calls[1]["prompt"]
        assert "[c-c00]" in json_calls[1]["prompt"]


class TestParallelConsolidation:
    """Tests for parallel consolidation with llm_concurrency > 1."""

    @pytest.fixture
    def parallel_consolidator(self, mock_llm, mock_embedding, memory_store):
        """Create a consolidator with parallel workers."""
        return Consolidator(
            llm=mock_llm,
            embedding=mock_embedding,
            store=memory_store,
            extraction_batch_size=20,
            consolidation_batch_size=20,
            min_confidence=0.3,
            llm_concurrency=4,
            extraction_llm_batch_size=3,
        )

    @pytest.mark.asyncio
    async def test_parallel_extraction_batches_episodes(
        self, parallel_consolidator, memory_store, mock_llm
    ):
        """Entity extraction groups episodes into batches of extraction_llm_batch_size."""
        for i in range(7):
            memory_store.add_episode(Episode(content=f"Episode {i}"))

        # Return batch results keyed by episode ID
        original_complete_json = mock_llm.complete_json
        call_count = 0

        async def mock_batch_response(prompt, **kwargs):
            nonlocal call_count
            call_count += 1
            import re
            ids = re.findall(r'\[ep-([a-f0-9-]+)\]', prompt)
            results = {}
            for ep_id in ids:
                results[ep_id] = {
                    "type": "observation",
                    "title": f"Title for {ep_id[:8]}",
                    "entities": [],
                    "entity_relationships": [],
                }
            return {"results": results}

        mock_llm.complete_json = mock_batch_response
        result = await parallel_consolidator._run_extraction_phase()

        assert result is not None
        assert result["episodes_processed"] == 7
        # 7 episodes / batch_size 3 = 3 batches (3 + 3 + 1)
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_extraction_progress_callback_reports_batches(
        self, parallel_consolidator, memory_store, mock_llm
    ):
        """Extraction progress callback receives one event per extraction batch."""
        for i in range(7):
            memory_store.add_episode(Episode(content=f"Episode {i}"))

        async def mock_batch_response(prompt, **kwargs):
            import re

            ids = re.findall(r'\[ep-([a-f0-9-]+)\]', prompt)
            return {
                "results": {
                    ep_id: {
                        "type": "observation",
                        "title": f"Title for {ep_id[:8]}",
                        "entities": [],
                        "entity_relationships": [],
                    }
                    for ep_id in ids
                }
            }

        mock_llm.complete_json = mock_batch_response
        progress_events = []

        await parallel_consolidator._run_extraction_phase(
            on_extraction_batch_complete=progress_events.append
        )

        assert len(progress_events) == 3
        assert [event["batch_num"] for event in progress_events] == [1, 2, 3]
        assert all(event["phase"] == "entity_extraction" for event in progress_events)

    @pytest.mark.asyncio
    async def test_parallel_consolidate_with_force(
        self, parallel_consolidator, memory_store, mock_llm, mock_embedding
    ):
        """Parallel consolidation produces same results as sequential."""
        e1 = Episode(content="User likes Python", entities_extracted=True)
        e2 = Episode(content="User prefers async", entities_extracted=True)
        e3 = Episode(content="User values typing", entities_extracted=True)
        for ep in [e1, e2, e3]:
            memory_store.add_episode(ep)

        mock_llm.set_complete_json_response({
            "analysis": "Programming preferences",
            "updates": [],
            "new_concepts": [
                {
                    "summary": "User prefers typed async Python",
                    "confidence": 0.8,
                    "source_episodes": [e1.id, e2.id, e3.id],
                    "tags": ["programming"],
                    "relations": [],
                }
            ],
            "new_relations": [],
            "contradictions": [],
        })

        result = await parallel_consolidator.consolidate(force=True)

        assert result.episodes_processed == 3
        assert result.concepts_created == 1

    @pytest.mark.asyncio
    async def test_parallel_multi_chunk_consolidation(
        self, mock_llm, mock_embedding, memory_store
    ):
        """Parallel chunk sub-passes produce correct merged results."""
        consolidator = Consolidator(
            llm=mock_llm,
            embedding=mock_embedding,
            store=memory_store,
            concepts_per_consolidation_pass=3,
            max_workers=4,
        )

        for i in range(5):
            memory_store.add_concept(Concept(
                id=f"c{i:02d}",
                summary=f"Existing concept {i}",
                embedding=[0.1] * 128,
            ))
        for i in range(3):
            memory_store.add_episode(Episode(content=f"Ep {i}", entities_extracted=True))

        mock_llm.set_complete_json_responses([
            make_consolidation_response(
                analysis="Chunk 0",
                new_concepts=[{
                    "temp_id": "NEW_0",
                    "summary": "From chunk 0",
                    "confidence": 0.7,
                    "tags": [],
                    "relations": [],
                }],
            ),
            make_consolidation_response(
                analysis="Chunk 1",
                new_concepts=[{
                    "temp_id": "NEW_0",
                    "summary": "From chunk 1",
                    "confidence": 0.6,
                    "tags": [],
                    "relations": [],
                }],
            ),
        ])

        result = await consolidator.consolidate()

        assert result.concepts_created == 2
        all_concepts = memory_store.get_all_concepts()
        new_summaries = {c.summary for c in all_concepts if "From chunk" in c.summary}
        assert "From chunk 0" in new_summaries
        assert "From chunk 1" in new_summaries

"""Integration tests for end-to-end workflows."""

import pytest
import asyncio

from remind.interface import MemoryInterface
from remind.models import EpisodeType, Concept


class TestEndToEndWorkflows:
    """End-to-end integration tests."""

    @pytest.fixture
    def memory(self, mock_llm, mock_embedding, memory_store):
        """Create memory interface for integration tests."""
        return MemoryInterface(
            llm=mock_llm,
            embedding=mock_embedding,
            store=memory_store,
            consolidation_threshold=3,
            auto_consolidate=False,
        )

    @pytest.mark.asyncio
    async def test_remember_consolidate_recall_workflow(
        self, memory, mock_llm, mock_embedding
    ):
        """Test the full remember -> consolidate -> recall workflow."""
        # Step 1: Remember multiple episodes
        memory.remember("User prefers Python for backend development")
        memory.remember("User mentioned they work on distributed systems")
        memory.remember("User values code readability")

        assert memory.pending_episodes_count == 3

        # Step 2: Consolidate
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

        result = await memory.consolidate(force=True)

        assert result.episodes_processed == 3
        assert result.concepts_created == 1
        assert memory.pending_episodes_count == 0

        # Step 3: Recall
        # Set embedding to match the new concept
        concepts = memory.get_all_concepts()
        mock_embedding.set_embedding("python preferences", concepts[0].embedding)

        recalled = await memory.recall("python preferences")

        assert "Python" in recalled
        assert "readable" in recalled.lower() or "clean" in recalled.lower()

    @pytest.mark.asyncio
    async def test_multi_session_workflow(
        self, mock_llm, mock_embedding, temp_db_path
    ):
        """Test workflow across multiple sessions."""
        # Session 1: Add some memories
        memory1 = MemoryInterface(
            llm=mock_llm,
            embedding=mock_embedding,
            db_path=temp_db_path,
        )

        memory1.remember("User likes FastAPI")
        memory1.remember("User prefers async patterns")
        memory1.remember("User works with PostgreSQL")

        mock_llm.set_complete_json_response({
            "analysis": "Web development preferences",
            "updates": [],
            "new_concepts": [
                {
                    "summary": "User builds async web apps with FastAPI and PostgreSQL",
                    "confidence": 0.8,
                    "tags": ["web", "async"],
                    "relations": [],
                }
            ],
            "new_relations": [],
            "contradictions": [],
        })

        await memory1.consolidate(force=True)

        # Session 2: New session with same database
        memory2 = MemoryInterface(
            llm=mock_llm,
            embedding=mock_embedding,
            db_path=temp_db_path,
        )

        # Verify concepts persisted
        concepts = memory2.get_all_concepts()
        assert len(concepts) == 1
        assert "FastAPI" in concepts[0].summary

        # Add more episodes
        memory2.remember("User started using Redis for caching")

        # Recall should find existing concepts
        mock_embedding.set_embedding("web development", concepts[0].embedding)
        recalled = await memory2.recall("web development")
        assert "FastAPI" in recalled

    @pytest.mark.asyncio
    async def test_entity_tracking_workflow(self, memory, mock_llm, mock_embedding):
        """Test entity-centric workflow."""
        # Remember episodes with explicit entities
        memory.remember(
            "Fixed authentication bug in auth.ts",
            entities=["file:src/auth.ts"],
            episode_type=EpisodeType.DECISION,
        )
        memory.remember(
            "Added rate limiting to auth.ts",
            entities=["file:src/auth.ts"],
            episode_type=EpisodeType.DECISION,
        )
        memory.remember(
            "Discussed auth changes with Alice",
            entities=["file:src/auth.ts", "person:alice"],
            episode_type=EpisodeType.OBSERVATION,
        )

        # Recall by entity
        result = await memory.recall("", entity="file:src/auth.ts")

        assert "auth.ts" in result
        assert "authentication" in result.lower() or "DECISION" in result

        # Check entity mention counts
        counts = memory.store.get_entity_mention_counts()
        auth_count = next((c for e, c in counts if e.id == "file:src/auth.ts"), 0)
        assert auth_count == 3

    @pytest.mark.asyncio
    async def test_concept_evolution_workflow(
        self, memory, mock_llm, mock_embedding
    ):
        """Test how concepts evolve through updates."""
        # Initial consolidation creates a concept
        memory.remember("User prefers spaces for indentation")
        memory.remember("User mentioned using 2-space indent")
        memory.remember("User configured editor for spaces")

        mock_llm.set_complete_json_response({
            "analysis": "User has indentation preferences",
            "updates": [],
            "new_concepts": [
                {
                    "summary": "User prefers spaces over tabs for indentation",
                    "confidence": 0.7,
                    "tags": ["code-style"],
                    "relations": [],
                }
            ],
            "new_relations": [],
            "contradictions": [],
        })

        await memory.consolidate(force=True)

        initial_concept = memory.get_all_concepts()[0]
        initial_confidence = initial_concept.confidence

        # More episodes reinforce the concept
        memory.remember("User changed project settings to use spaces")
        memory.remember("User advocated for spaces in team meeting")
        memory.remember("User created linter rule for spaces")

        mock_llm.set_complete_json_response({
            "analysis": "Further evidence of spacing preference",
            "updates": [
                {
                    "concept_id": initial_concept.id,
                    "new_summary": "User strongly prefers 2-space indentation over tabs",
                    "confidence_delta": 0.15,
                    "add_exceptions": [],
                    "add_tags": ["strong-preference"],
                    "reasoning": "Multiple confirmations",
                }
            ],
            "new_concepts": [],
            "new_relations": [],
            "contradictions": [],
        })

        await memory.consolidate(force=True)

        updated_concept = memory.get_concept(initial_concept.id)
        assert updated_concept.confidence > initial_confidence
        assert "strong-preference" in updated_concept.tags
        assert "2-space" in updated_concept.summary

    @pytest.mark.asyncio
    async def test_contradiction_detection_workflow(
        self, memory, mock_llm, mock_embedding
    ):
        """Test detection of contradicting information."""
        # Create initial concept
        memory.remember("User dislikes JavaScript")
        memory.remember("User avoids frontend work")
        memory.remember("User criticizes JS ecosystem")

        mock_llm.set_complete_json_response({
            "analysis": "User dislikes JavaScript",
            "updates": [],
            "new_concepts": [
                {
                    "summary": "User dislikes JavaScript and avoids frontend development",
                    "confidence": 0.8,
                    "tags": ["preferences"],
                    "relations": [],
                }
            ],
            "new_relations": [],
            "contradictions": [],
        })

        await memory.consolidate(force=True)
        existing_concept = memory.get_all_concepts()[0]

        # Add contradicting episodes
        memory.remember("User started learning React")
        memory.remember("User enjoyed building a React app")
        memory.remember("User praised TypeScript")

        mock_llm.set_complete_json_response({
            "analysis": "Contradicting information about JavaScript",
            "updates": [],
            "new_concepts": [],
            "new_relations": [],
            "contradictions": [
                {
                    "concept_id": existing_concept.id,
                    "evidence": "User enjoyed building a React app",
                    "resolution": "Opinion may have changed over time",
                }
            ],
        })

        result = await memory.consolidate(force=True)

        assert result.contradictions_found == 1
        assert len(result.contradiction_details) == 1

    @pytest.mark.asyncio
    async def test_episode_type_filtering_workflow(self, memory):
        """Test filtering by episode type."""
        memory.remember("Decided to use Redis", episode_type=EpisodeType.DECISION)
        memory.remember("Decided to use PostgreSQL", episode_type=EpisodeType.DECISION)
        memory.remember("Should we use GraphQL?", episode_type=EpisodeType.QUESTION)
        memory.remember("Noticed high latency", episode_type=EpisodeType.OBSERVATION)
        memory.remember("Prefers REST over GraphQL", episode_type=EpisodeType.PREFERENCE)

        decisions = memory.get_episodes_by_type(EpisodeType.DECISION)
        questions = memory.get_episodes_by_type(EpisodeType.QUESTION)
        observations = memory.get_episodes_by_type(EpisodeType.OBSERVATION)
        preferences = memory.get_episodes_by_type(EpisodeType.PREFERENCE)

        assert len(decisions) == 2
        assert len(questions) == 1
        assert len(observations) == 1
        assert len(preferences) == 1

    @pytest.mark.asyncio
    async def test_import_export_round_trip(self, memory, mock_llm, tmp_path):
        """Test export and import preserves data."""
        # Create some data
        memory.remember("Episode 1", episode_type=EpisodeType.DECISION)
        memory.remember("Episode 2", entities=["file:test.py"])

        mock_llm.set_complete_json_response({
            "analysis": "Test",
            "updates": [],
            "new_concepts": [
                {
                    "summary": "Test concept",
                    "confidence": 0.8,
                    "tags": ["test"],
                    "relations": [],
                }
            ],
            "new_relations": [],
            "contradictions": [],
        })

        await memory.consolidate(force=True)

        # Export
        export_path = tmp_path / "export.json"
        exported = memory.export_memory(path=str(export_path))

        # Create new memory and import
        memory2 = MemoryInterface(
            llm=memory.llm,
            embedding=memory.embedding,
            db_path=str(tmp_path / "imported.db"),
        )

        result = memory2.import_memory(str(export_path))

        assert result["concepts_imported"] == 1
        assert result["episodes_imported"] >= 2

        # Verify data matches
        assert len(memory2.get_all_concepts()) == 1
        assert memory2.get_all_concepts()[0].summary == "Test concept"


class TestErrorHandling:
    """Tests for error handling scenarios."""

    @pytest.fixture
    def memory(self, mock_llm, mock_embedding, memory_store):
        return MemoryInterface(
            llm=mock_llm,
            embedding=mock_embedding,
            store=memory_store,
        )

    @pytest.mark.asyncio
    async def test_llm_failure_during_consolidation(self, memory, mock_llm):
        """Test handling of LLM failures."""
        memory.remember("Episode 1")
        memory.remember("Episode 2")
        memory.remember("Episode 3")

        # Make LLM raise an exception
        async def raise_error(*args, **kwargs):
            raise Exception("LLM service unavailable")
        mock_llm.complete_json = raise_error

        with pytest.raises(Exception, match="LLM service unavailable"):
            await memory.consolidate(force=True)

        # Episodes should NOT be marked as consolidated
        pending = memory.get_pending_episodes()
        assert len(pending) == 3

    @pytest.mark.asyncio
    async def test_embedding_failure_during_recall(self, memory, mock_embedding):
        """Test handling of embedding failures during recall."""
        # Make embedding raise an exception
        async def raise_error(*args, **kwargs):
            raise Exception("Embedding service unavailable")
        mock_embedding.embed = raise_error

        with pytest.raises(Exception, match="Embedding service unavailable"):
            await memory.recall("test query")

    @pytest.mark.asyncio
    async def test_graceful_handling_of_invalid_update_target(
        self, memory, mock_llm, mock_embedding
    ):
        """Test handling of updates to nonexistent concepts."""
        memory.remember("Episode 1")
        memory.remember("Episode 2")
        memory.remember("Episode 3")

        # Response references nonexistent concept
        mock_llm.set_complete_json_response({
            "analysis": "Test",
            "updates": [
                {
                    "concept_id": "nonexistent_concept",
                    "confidence_delta": 0.1,
                }
            ],
            "new_concepts": [],
            "new_relations": [],
            "contradictions": [],
        })

        # Should not raise
        result = await memory.consolidate(force=True)

        # Verify no concept was actually created (update target didn't exist)
        assert len(memory.get_all_concepts()) == 0

    @pytest.mark.asyncio
    async def test_graceful_handling_of_invalid_relation_type(
        self, memory, mock_llm, mock_embedding
    ):
        """Test handling of invalid relation types."""
        c1 = Concept(id="c1", summary="Test", embedding=[0.1] * 128)
        c2 = Concept(id="c2", summary="Target", embedding=[0.1] * 128)
        memory.store.add_concept(c1)
        memory.store.add_concept(c2)

        for i in range(3):
            memory.remember(f"Ep {i}")

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
                            "type": "invalid_relation_type",
                            "target_id": "c2",
                            "strength": 0.5,
                        }
                    ],
                }
            ],
            "new_relations": [],
            "contradictions": [],
        })

        # Should not raise, but relation should be skipped
        result = await memory.consolidate(force=True)
        assert result.concepts_created == 1


class TestConcurrentOperations:
    """Tests for concurrent operations."""

    @pytest.mark.asyncio
    async def test_multiple_recalls(self, mock_llm, mock_embedding, memory_store):
        """Test multiple concurrent recalls."""
        memory = MemoryInterface(
            llm=mock_llm,
            embedding=mock_embedding,
            store=memory_store,
        )

        # Add some concepts
        for i in range(5):
            c = Concept(
                summary=f"Concept {i}",
                embedding=[float(i) / 10] * 128,
            )
            memory_store.add_concept(c)

        # Run multiple recalls concurrently
        queries = ["query1", "query2", "query3", "query4", "query5"]
        results = await asyncio.gather(*[
            memory.recall(q) for q in queries
        ])

        assert len(results) == 5
        for r in results:
            assert isinstance(r, str)

    @pytest.mark.asyncio
    async def test_remember_during_recall(self, mock_llm, mock_embedding, memory_store):
        """Test remembering while recall is happening."""
        memory = MemoryInterface(
            llm=mock_llm,
            embedding=mock_embedding,
            store=memory_store,
        )

        # Add initial concept
        c = Concept(summary="Initial", embedding=[0.5] * 128)
        memory_store.add_concept(c)

        # Start recall and remember concurrently
        async def recall_and_remember():
            recall_task = asyncio.create_task(memory.recall("test"))
            # Remember during recall
            memory.remember("New episode")
            return await recall_task

        result = await recall_and_remember()

        assert isinstance(result, str)
        assert memory.pending_episodes_count == 1


class TestEdgeCases:
    """Tests for edge cases."""

    @pytest.fixture
    def memory(self, mock_llm, mock_embedding, memory_store):
        return MemoryInterface(
            llm=mock_llm,
            embedding=mock_embedding,
            store=memory_store,
        )

    def test_remember_empty_content(self, memory):
        """Test remembering empty content."""
        episode_id = memory.remember("")

        episode = memory.store.get_episode(episode_id)
        assert episode.content == ""

    def test_remember_very_long_content(self, memory):
        """Test remembering very long content."""
        long_content = "x" * 10000
        episode_id = memory.remember(long_content)

        episode = memory.store.get_episode(episode_id)
        assert episode.content == long_content

    @pytest.mark.asyncio
    async def test_recall_empty_query(self, memory, mock_embedding):
        """Test recall with empty query."""
        c = Concept(summary="Test", embedding=[0.5] * 128)
        memory.store.add_concept(c)

        # Should not raise
        result = await memory.recall("")
        assert isinstance(result, str)

    def test_remember_special_characters(self, memory):
        """Test remembering content with special characters."""
        content = "User prefers <html> & 'quotes' \"double\" \n\ttabs"
        episode_id = memory.remember(content)

        episode = memory.store.get_episode(episode_id)
        assert episode.content == content

    def test_remember_unicode_content(self, memory):
        """Test remembering unicode content."""
        content = "User likes Python 🐍 and emoji 😀"
        episode_id = memory.remember(content)

        episode = memory.store.get_episode(episode_id)
        assert episode.content == content

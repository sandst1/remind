"""Tests for MemoryInterface - the main API."""

import pytest
import json
import tempfile
import os

from remind.interface import MemoryInterface
from remind.models import Episode, Concept, Entity, EntityType, EpisodeType


class TestMemoryInterface:
    """Tests for MemoryInterface class."""

    @pytest.fixture
    def memory(self, mock_llm, mock_embedding, memory_store):
        """Create a MemoryInterface with mocks."""
        return MemoryInterface(
            llm=mock_llm,
            embedding=mock_embedding,
            store=memory_store,
            consolidation_threshold=5,
            auto_consolidate=False,  # Manual for testing
            default_recall_k=5,
            spread_hops=2,
        )

    # =========================================================================
    # remember() tests
    # =========================================================================

    def test_remember_basic(self, memory):
        """Test basic remember functionality."""
        episode_id = memory.remember("User likes Python")

        assert episode_id is not None
        assert len(episode_id) == 8

        # Verify episode was stored
        episode = memory.store.get_episode(episode_id)
        assert episode is not None
        assert episode.content == "User likes Python"

    def test_remember_with_metadata(self, memory):
        """Test remember with metadata."""
        episode_id = memory.remember(
            "Important decision",
            metadata={"source": "meeting", "importance": "high"},
        )

        episode = memory.store.get_episode(episode_id)
        assert episode.metadata["source"] == "meeting"
        assert episode.metadata["importance"] == "high"

    def test_remember_with_explicit_type(self, memory):
        """Test remember with explicit episode type."""
        episode_id = memory.remember(
            "Decided to use async",
            episode_type=EpisodeType.DECISION,
        )

        episode = memory.store.get_episode(episode_id)
        assert episode.episode_type == EpisodeType.DECISION
        assert episode.entities_extracted == True  # Manual override counts as extracted

    def test_remember_with_all_episode_types(self, memory):
        """Test remember with all episode types."""
        types = [
            EpisodeType.OBSERVATION,
            EpisodeType.DECISION,
            EpisodeType.QUESTION,
            EpisodeType.META,
            EpisodeType.PREFERENCE,
        ]

        for ep_type in types:
            episode_id = memory.remember(f"Test {ep_type.value}", episode_type=ep_type)
            episode = memory.store.get_episode(episode_id)
            assert episode.episode_type == ep_type

    def test_remember_with_explicit_entities(self, memory):
        """Test remember with explicit entity list."""
        episode_id = memory.remember(
            "Modified auth.ts",
            entities=["file:src/auth.ts", "person:alice"],
        )

        episode = memory.store.get_episode(episode_id)
        assert "file:src/auth.ts" in episode.entity_ids
        assert "person:alice" in episode.entity_ids

        # Verify entities were created
        entity = memory.store.get_entity("file:src/auth.ts")
        assert entity is not None
        assert entity.type == EntityType.FILE

    def test_remember_creates_entities_from_ids(self, memory):
        """Test remember creates entity objects from IDs."""
        memory.remember(
            "Test",
            entities=["function:myFunc", "class:MyClass", "tool:redis"],
        )

        func = memory.store.get_entity("function:myFunc")
        assert func is not None
        assert func.type == EntityType.FUNCTION
        assert func.display_name == "myFunc"

        cls = memory.store.get_entity("class:MyClass")
        assert cls.type == EntityType.CLASS

        tool = memory.store.get_entity("tool:redis")
        assert tool.type == EntityType.TOOL

    def test_remember_with_confidence(self, memory):
        """Test remember with confidence level."""
        episode_id = memory.remember(
            "User might prefer TypeScript",
            confidence=0.6,
        )

        episode = memory.store.get_episode(episode_id)
        assert episode.confidence == 0.6

    def test_remember_clamps_confidence_high(self, memory):
        """Test confidence is clamped to max 1.0."""
        episode_id = memory.remember("High confidence", confidence=1.5)
        episode = memory.store.get_episode(episode_id)
        assert episode.confidence == 1.0

    def test_remember_clamps_confidence_low(self, memory):
        """Test confidence is clamped to min 0.0."""
        episode_id = memory.remember("Low confidence", confidence=-0.5)
        episode = memory.store.get_episode(episode_id)
        assert episode.confidence == 0.0

    def test_remember_updates_episode_buffer(self, memory):
        """Test episode buffer is updated."""
        assert len(memory._episode_buffer) == 0

        memory.remember("First")
        assert len(memory._episode_buffer) == 1

        memory.remember("Second")
        assert len(memory._episode_buffer) == 2

    def test_remember_creates_mentions(self, memory):
        """Test remember creates mention records."""
        episode_id = memory.remember(
            "Test",
            entities=["file:test.py"],
        )

        # Verify mention was created
        episodes = memory.store.get_episodes_mentioning("file:test.py")
        assert len(episodes) == 1
        assert episodes[0].id == episode_id

    # =========================================================================
    # recall() tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_recall_empty_memory(self, memory):
        """Test recall with no concepts."""
        result = await memory.recall("anything")
        assert "No relevant memories found" in result

    @pytest.mark.asyncio
    async def test_recall_returns_formatted_string(
        self, memory, sample_concept, mock_embedding
    ):
        """Test recall returns formatted string by default."""
        memory.store.add_concept(sample_concept)
        mock_embedding.set_embedding("python", sample_concept.embedding)

        result = await memory.recall("python")

        assert isinstance(result, str)
        assert "RELEVANT MEMORY" in result

    @pytest.mark.asyncio
    async def test_recall_raw_returns_objects(
        self, memory, sample_concept, mock_embedding
    ):
        """Test recall with raw=True returns objects."""
        memory.store.add_concept(sample_concept)
        mock_embedding.set_embedding("python", sample_concept.embedding)

        result = await memory.recall("python", raw=True)

        assert isinstance(result, list)
        if result:
            from remind.retrieval import ActivatedConcept
            assert isinstance(result[0], ActivatedConcept)

    @pytest.mark.asyncio
    async def test_recall_by_entity(self, memory, sample_episode, sample_entity):
        """Test recall by entity."""
        memory.store.add_episode(sample_episode)
        memory.store.add_entity(sample_entity)
        memory.store.add_mention(sample_episode.id, sample_entity.id)

        result = await memory.recall("", entity="file:src/auth.ts")

        assert "MEMORY ABOUT" in result

    @pytest.mark.asyncio
    async def test_recall_by_entity_raw(self, memory, sample_episode, sample_entity):
        """Test recall by entity with raw=True."""
        memory.store.add_episode(sample_episode)
        memory.store.add_entity(sample_entity)
        memory.store.add_mention(sample_episode.id, sample_entity.id)

        result = await memory.recall("", entity="file:src/auth.ts", raw=True)

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0].id == sample_episode.id

    @pytest.mark.asyncio
    async def test_recall_uses_default_k(self, memory, mock_embedding):
        """Test recall uses default_recall_k."""
        # Add multiple concepts
        for i in range(10):
            c = Concept(
                summary=f"Concept {i}",
                embedding=[float(i) / 10] * 128,
            )
            memory.store.add_concept(c)

        result = await memory.recall("query", raw=True)

        # Should return at most default_recall_k (5) concepts
        assert len(result) <= 5

    @pytest.mark.asyncio
    async def test_recall_with_custom_k(self, memory, mock_embedding):
        """Test recall with custom k value."""
        for i in range(10):
            c = Concept(
                summary=f"Concept {i}",
                embedding=[float(i) / 10] * 128,
            )
            memory.store.add_concept(c)

        result = await memory.recall("query", k=2, raw=True)

        assert len(result) <= 2

    @pytest.mark.asyncio
    async def test_recall_with_context(self, memory, mock_embedding, sample_concept):
        """Test recall includes context."""
        memory.store.add_concept(sample_concept)

        await memory.recall("query", context="additional context")

        calls = mock_embedding.get_call_history()
        assert any("additional context" in c.get("text", "") for c in calls)

    # =========================================================================
    # consolidate() and end_session() tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_consolidate_manual(self, memory, mock_llm, mock_embedding):
        """Test manual consolidation."""
        # Add episodes
        for i in range(5):
            ep = Episode(content=f"Episode {i}", entities_extracted=True)
            memory.store.add_episode(ep)

        mock_llm.set_complete_json_response({
            "analysis": "Test",
            "updates": [],
            "new_concepts": [
                {"summary": "New concept", "confidence": 0.7, "tags": [], "relations": []}
            ],
            "new_relations": [],
            "contradictions": [],
        })

        result = await memory.consolidate(force=True)

        assert result.episodes_processed == 5
        assert result.concepts_created == 1
        assert memory._last_consolidation is not None
        assert len(memory._episode_buffer) == 0  # Buffer cleared

    @pytest.mark.asyncio
    async def test_consolidate_updates_timestamp(self, memory, mock_llm):
        """Test consolidation updates last_consolidation timestamp."""
        for i in range(3):
            ep = Episode(content=f"Episode {i}", entities_extracted=True)
            memory.store.add_episode(ep)

        mock_llm.set_complete_json_response({
            "analysis": "Test",
            "updates": [],
            "new_concepts": [],
            "new_relations": [],
            "contradictions": [],
        })

        assert memory._last_consolidation is None

        await memory.consolidate(force=True)

        assert memory._last_consolidation is not None

    @pytest.mark.asyncio
    async def test_consolidate_clears_buffer_on_success(self, memory, mock_llm):
        """Test episode buffer is cleared after successful consolidation."""
        memory.remember("Episode 1")
        memory.remember("Episode 2")
        memory.remember("Episode 3")

        assert len(memory._episode_buffer) == 3

        mock_llm.set_complete_json_response({
            "analysis": "Test",
            "updates": [],
            "new_concepts": [],
            "new_relations": [],
            "contradictions": [],
        })

        await memory.consolidate(force=True)

        assert len(memory._episode_buffer) == 0

    @pytest.mark.asyncio
    async def test_end_session_with_pending(self, memory, mock_llm):
        """Test end_session triggers consolidation."""
        memory.remember("Episode 1")

        mock_llm.set_complete_json_response({
            "analysis": "Test",
            "updates": [],
            "new_concepts": [],
            "new_relations": [],
            "contradictions": [],
        })

        result = await memory.end_session()

        assert result.episodes_processed >= 1

    @pytest.mark.asyncio
    async def test_end_session_no_pending(self, memory):
        """Test end_session with no pending episodes."""
        result = await memory.end_session()

        assert result.episodes_processed == 0

    # =========================================================================
    # Properties and state tests
    # =========================================================================

    def test_pending_episodes_count(self, memory):
        """Test pending_episodes_count property."""
        assert memory.pending_episodes_count == 0

        memory.remember("First")
        assert memory.pending_episodes_count == 1

        memory.remember("Second")
        assert memory.pending_episodes_count == 2

    def test_should_consolidate_false(self, memory):
        """Test should_consolidate is False below threshold."""
        assert memory.should_consolidate == False

        memory.remember("First")
        memory.remember("Second")
        assert memory.should_consolidate == False

    def test_should_consolidate_true(self, memory):
        """Test should_consolidate is True at threshold."""
        # Add episodes up to threshold (5)
        for i in range(5):
            memory.remember(f"Episode {i}")

        assert memory.should_consolidate == True

    def test_get_pending_episodes(self, memory):
        """Test get_pending_episodes method."""
        memory.remember("First")
        memory.remember("Second")

        pending = memory.get_pending_episodes()

        assert len(pending) == 2

    def test_get_pending_episodes_limit(self, memory):
        """Test get_pending_episodes respects limit."""
        for i in range(10):
            memory.remember(f"Episode {i}")

        pending = memory.get_pending_episodes(limit=3)

        assert len(pending) == 3

    # =========================================================================
    # Direct access methods
    # =========================================================================

    def test_get_concept(self, memory, sample_concept):
        """Test get_concept method."""
        memory.store.add_concept(sample_concept)

        result = memory.get_concept(sample_concept.id)

        assert result is not None
        assert result.summary == sample_concept.summary

    def test_get_concept_not_found(self, memory):
        """Test get_concept returns None for nonexistent."""
        result = memory.get_concept("nonexistent")
        assert result is None

    def test_get_all_concepts(self, memory, sample_concepts_with_relations):
        """Test get_all_concepts method."""
        for c in sample_concepts_with_relations:
            memory.store.add_concept(c)

        result = memory.get_all_concepts()

        assert len(result) == 3

    def test_get_recent_episodes(self, memory):
        """Test get_recent_episodes method."""
        for i in range(5):
            memory.remember(f"Episode {i}")

        result = memory.get_recent_episodes(limit=3)

        assert len(result) == 3

    def test_get_episodes_by_type(self, memory):
        """Test get_episodes_by_type method."""
        memory.remember("Decision 1", episode_type=EpisodeType.DECISION)
        memory.remember("Decision 2", episode_type=EpisodeType.DECISION)
        memory.remember("Question", episode_type=EpisodeType.QUESTION)

        decisions = memory.get_episodes_by_type(EpisodeType.DECISION)

        assert len(decisions) == 2

    def test_get_entity(self, memory, sample_entity):
        """Test get_entity method."""
        memory.store.add_entity(sample_entity)

        result = memory.get_entity(sample_entity.id)

        assert result is not None
        assert result.display_name == sample_entity.display_name

    def test_get_entity_not_found(self, memory):
        """Test get_entity returns None for nonexistent."""
        result = memory.get_entity("nonexistent")
        assert result is None

    def test_get_all_entities(self, memory):
        """Test get_all_entities method."""
        memory.remember("Modified auth.ts", entities=["file:auth.ts", "person:bob"])

        entities = memory.get_all_entities()

        assert len(entities) == 2

    def test_get_episodes_mentioning(self, memory, sample_episode, sample_entity):
        """Test get_episodes_mentioning method."""
        memory.store.add_episode(sample_episode)
        memory.store.add_entity(sample_entity)
        memory.store.add_mention(sample_episode.id, sample_entity.id)

        result = memory.get_episodes_mentioning(sample_entity.id)

        assert len(result) == 1

    def test_get_entity_mention_counts(self, memory):
        """Test get_entity_mention_counts method."""
        # Create multiple episodes mentioning same entity
        for i in range(3):
            memory.remember(f"Episode {i}", entities=["file:common.py"])
        memory.remember("Other", entities=["file:other.py"])

        counts = memory.get_entity_mention_counts()

        # Should be sorted by count
        assert counts[0][0].id == "file:common.py"
        assert counts[0][1] == 3

    # =========================================================================
    # get_stats tests
    # =========================================================================

    def test_get_stats(self, memory, mock_llm, mock_embedding):
        """Test get_stats method."""
        memory.remember("Episode 1")
        memory.remember("Episode 2")

        stats = memory.get_stats()

        assert stats["episodes"] == 2
        assert stats["concepts"] == 0
        assert stats["unconsolidated_episodes"] == 2
        assert stats["consolidation_threshold"] == 5
        assert stats["auto_consolidate"] == False
        assert stats["llm_provider"] == "mock/llm"
        assert stats["embedding_provider"] == "mock/embedding"

    def test_get_stats_includes_buffer(self, memory):
        """Test stats includes session buffer info."""
        memory.remember("Test")

        stats = memory.get_stats()

        assert stats["session_episode_buffer"] == 1

    def test_get_stats_should_consolidate(self, memory):
        """Test stats includes should_consolidate."""
        stats = memory.get_stats()
        assert stats["should_consolidate"] == False

    # =========================================================================
    # Import/Export tests
    # =========================================================================

    def test_export_memory(self, memory, sample_concept):
        """Test export_memory method."""
        memory.remember("Test episode")
        memory.store.add_concept(sample_concept)

        data = memory.export_memory()

        assert "episodes" in data
        assert "concepts" in data
        assert "exported_at" in data
        assert len(data["episodes"]) == 1
        assert len(data["concepts"]) == 1

    def test_export_memory_to_file(self, memory, sample_concept, tmp_path):
        """Test export_memory to file."""
        memory.remember("Test episode")

        export_path = tmp_path / "export.json"
        data = memory.export_memory(path=str(export_path))

        assert export_path.exists()
        with open(export_path) as f:
            loaded = json.load(f)
        assert loaded["episodes"] == data["episodes"]

    def test_import_memory_from_dict(self, memory):
        """Test import_memory from dictionary."""
        data = {
            "concepts": [
                {
                    "id": "imported1",
                    "summary": "Imported concept",
                    "confidence": 0.7,
                    "tags": ["imported"],
                    "relations": [],
                    "source_episodes": [],
                    "exceptions": [],
                }
            ],
            "episodes": [
                {
                    "id": "ep_imported",
                    "content": "Imported episode",
                    "consolidated": False,
                    "metadata": {},
                    "concepts_activated": [],
                    "entity_ids": [],
                }
            ],
        }

        result = memory.import_memory(data)

        assert result["concepts_imported"] == 1
        assert result["episodes_imported"] == 1

        # Verify imported
        assert memory.get_concept("imported1") is not None

    def test_import_memory_from_file(self, memory, tmp_path):
        """Test import_memory from file."""
        data = {
            "concepts": [],
            "episodes": [
                {
                    "id": "from_file",
                    "content": "From file",
                    "consolidated": False,
                    "metadata": {},
                    "concepts_activated": [],
                    "entity_ids": [],
                }
            ],
        }

        import_path = tmp_path / "import.json"
        with open(import_path, "w") as f:
            json.dump(data, f)

        result = memory.import_memory(str(import_path))

        assert result["episodes_imported"] == 1

    # =========================================================================
    # Context manager tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_context_manager_enter(self, mock_llm, mock_embedding, temp_db_path):
        """Test async context manager enter."""
        async with MemoryInterface(
            llm=mock_llm,
            embedding=mock_embedding,
            db_path=temp_db_path,
        ) as memory:
            assert memory is not None
            memory.remember("Inside context")
            assert memory.pending_episodes_count == 1

    @pytest.mark.asyncio
    async def test_context_manager_exit_consolidates(
        self, mock_llm, mock_embedding, temp_db_path
    ):
        """Test context manager exit triggers consolidation."""
        mock_llm.set_complete_json_response({
            "analysis": "Test",
            "updates": [],
            "new_concepts": [],
            "new_relations": [],
            "contradictions": [],
        })

        async with MemoryInterface(
            llm=mock_llm,
            embedding=mock_embedding,
            db_path=temp_db_path,
        ) as memory:
            memory.remember("Episode 1")
            memory.remember("Episode 2")

        # After exit, consolidation should have run
        # Verify by checking call history
        assert len(mock_llm.get_call_history()) > 0


class TestMemoryInterfaceInitialization:
    """Tests for MemoryInterface initialization."""

    def test_init_with_store(self, mock_llm, mock_embedding, memory_store):
        """Test initialization with provided store."""
        memory = MemoryInterface(
            llm=mock_llm,
            embedding=mock_embedding,
            store=memory_store,
        )

        assert memory.store is memory_store

    def test_init_creates_store(self, mock_llm, mock_embedding, temp_db_path):
        """Test initialization creates store from path."""
        memory = MemoryInterface(
            llm=mock_llm,
            embedding=mock_embedding,
            db_path=temp_db_path,
        )

        assert memory.store is not None

    def test_init_default_values(self, mock_llm, mock_embedding, temp_db_path):
        """Test initialization with default values."""
        memory = MemoryInterface(
            llm=mock_llm,
            embedding=mock_embedding,
            db_path=temp_db_path,
        )

        assert memory.consolidation_threshold == 10
        assert memory.auto_consolidate == True
        assert memory.default_recall_k == 5

    def test_init_custom_values(self, mock_llm, mock_embedding, temp_db_path):
        """Test initialization with custom values."""
        memory = MemoryInterface(
            llm=mock_llm,
            embedding=mock_embedding,
            db_path=temp_db_path,
            consolidation_threshold=20,
            auto_consolidate=False,
            default_recall_k=10,
            spread_hops=3,
        )

        assert memory.consolidation_threshold == 20
        assert memory.auto_consolidate == False
        assert memory.default_recall_k == 10

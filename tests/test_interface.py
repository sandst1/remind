"""Tests for MemoryInterface - the main API."""

import pytest
import json
import tempfile
import os

from remind.interface import MemoryInterface
from remind.models import Episode, Concept, Entity, EntityType, EpisodeType, Fact, Conflict


class TestMemoryInterface:
    """Tests for MemoryInterface class."""

    @pytest.fixture
    def memory(self, mock_embedding, memory_store):
        """Create a MemoryInterface with mocks."""
        return MemoryInterface(
            embedding=mock_embedding,
            store=memory_store,
            default_recall_k=5,
            spread_hops=2,
        )

    # =========================================================================
    # remember() tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_remember_basic(self, memory):
        """Test basic remember functionality."""
        result = await memory.remember("User likes Python")

        assert result.episode_id is not None
        assert len(result.episode_id) == 8

        # Verify episode was stored
        episode = memory.store.get_episode(result.episode_id)
        assert episode is not None
        assert episode.content == "User likes Python"

    @pytest.mark.asyncio
    async def test_remember_with_metadata(self, memory):
        """Test remember with metadata."""
        result = await memory.remember(
            "Important decision",
            metadata={"source": "meeting", "importance": "high"},
        )

        episode = memory.store.get_episode(result.episode_id)
        assert episode.metadata["source"] == "meeting"
        assert episode.metadata["importance"] == "high"

    @pytest.mark.asyncio
    async def test_remember_with_provenance(self, memory):
        """Test remember stores asserted_by and source_ref."""
        result = await memory.remember(
            "TTL is 300s",
            asserted_by="  alice ",
            source_ref=" https://github.com/org/repo/pull/42 ",
        )

        episode = memory.store.get_episode(result.episode_id)
        assert episode.asserted_by == "alice"
        assert episode.source_ref == "https://github.com/org/repo/pull/42"

    @pytest.mark.asyncio
    async def test_remember_provenance_defaults_none(self, memory):
        """Provenance fields default to None when not provided."""
        result = await memory.remember("no provenance")
        episode = memory.store.get_episode(result.episode_id)
        assert episode.asserted_by is None
        assert episode.source_ref is None

    @pytest.mark.asyncio
    async def test_recall_accepts_as_of_string(self, memory):
        """recall() parses ISO as_of strings and doesn't blow up."""
        result = await memory.recall("anything", as_of="2026-01-15")
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_recall_rejects_invalid_as_of(self, memory):
        with pytest.raises(ValueError):
            await memory.recall("anything", as_of="not-a-date")

    @pytest.mark.asyncio
    async def test_remember_with_explicit_type(self, memory):
        """Test remember with explicit episode type."""
        result = await memory.remember(
            "Decided to use async",
            episode_type=EpisodeType.DECISION,
        )

        episode = memory.store.get_episode(result.episode_id)
        assert episode.episode_type == "decision"

    @pytest.mark.asyncio
    async def test_remember_with_all_episode_types(self, memory):
        """Test remember with all episode types."""
        types = [
            EpisodeType.OBSERVATION,
            EpisodeType.DECISION,
            EpisodeType.QUESTION,
            EpisodeType.META,
            EpisodeType.PREFERENCE,
            EpisodeType.OUTCOME,
            EpisodeType.FACT,
        ]

        for ep_type in types:
            result = await memory.remember(f"Test {ep_type.value}", episode_type=ep_type)
            episode = memory.store.get_episode(result.episode_id)
            assert episode.episode_type == ep_type.value

    @pytest.mark.asyncio
    async def test_remember_with_explicit_entities(self, memory):
        """Test remember with explicit entity list."""
        result = await memory.remember(
            "Modified auth.ts",
            entities=["file:src/auth.ts", "person:alice"],
        )

        episode = memory.store.get_episode(result.episode_id)
        assert "file:src/auth.ts" in episode.entity_ids
        assert "person:alice" in episode.entity_ids

        # Verify entities were created
        entity = memory.store.get_entity("file:src/auth.ts")
        assert entity is not None
        assert entity.type == EntityType.FILE

    @pytest.mark.asyncio
    async def test_remember_creates_entities_from_ids(self, memory):
        """Test remember creates entity objects from IDs (normalized to lowercase)."""
        await memory.remember(
            "Test",
            entities=["function:myFunc", "class:MyClass", "tool:redis"],
        )

        func = memory.store.get_entity("function:myfunc")
        assert func is not None
        assert func.type == EntityType.FUNCTION
        assert func.display_name == "myFunc"

        cls = memory.store.get_entity("class:myclass")
        assert cls.type == EntityType.CLASS

        tool = memory.store.get_entity("tool:redis")
        assert tool.type == EntityType.TOOL

    @pytest.mark.asyncio
    async def test_remember_with_confidence(self, memory):
        """Test remember with confidence level."""
        result = await memory.remember(
            "User might prefer TypeScript",
            confidence=0.6,
        )

        episode = memory.store.get_episode(result.episode_id)
        assert episode.confidence == 0.6

    @pytest.mark.asyncio
    async def test_remember_clamps_confidence_high(self, memory):
        """Test confidence is clamped to max 1.0."""
        result = await memory.remember("High confidence", confidence=1.5)
        episode = memory.store.get_episode(result.episode_id)
        assert episode.confidence == 1.0

    @pytest.mark.asyncio
    async def test_remember_clamps_confidence_low(self, memory):
        """Test confidence is clamped to min 0.0."""
        result = await memory.remember("Low confidence", confidence=-0.5)
        episode = memory.store.get_episode(result.episode_id)
        assert episode.confidence == 0.0

    @pytest.mark.asyncio
    async def test_remember_creates_mentions(self, memory):
        """Test remember creates mention records."""
        result = await memory.remember(
            "Test",
            entities=["file:test.py"],
        )

        # Verify mention was created
        episodes = memory.store.get_episodes_mentioning("file:test.py")
        assert len(episodes) == 1
        assert episodes[0].id == result.episode_id

    # =========================================================================
    # remember() fact handling tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_remember_fact_creates_fact_row(self, memory):
        """Test remember with fact type creates Fact row."""
        memory.store.add_entity(Entity(id="tool:redis", type=EntityType.TOOL))
        
        result = await memory.remember(
            "Cache TTL is 600s",
            episode_type=EpisodeType.FACT,
            entities=["tool:redis"],
        )

        assert result.fact_id is not None
        assert result.cluster_id is not None
        assert result.cluster_created is True

        fact = memory.store.get_fact(result.fact_id)
        assert fact is not None
        assert fact.statement == "Cache TTL is 600s"

    @pytest.mark.asyncio
    async def test_remember_fact_detects_collisions(self, memory):
        """Test remember returns collisions for potentially conflicting facts."""
        memory.store.add_entity(Entity(id="tool:redis", type=EntityType.TOOL))
        
        # First fact
        await memory.remember(
            "Cache TTL is 300s",
            episode_type=EpisodeType.FACT,
            entities=["tool:redis"],
        )

        # Second potentially conflicting fact
        result = await memory.remember(
            "Cache TTL is 600s",
            episode_type=EpisodeType.FACT,
            entities=["tool:redis"],
        )

        assert len(result.collisions) == 1
        assert "300s" in result.collisions[0].statement

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
        """Test recall with raw=True returns list of ActivatedConcept."""
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

    # =========================================================================
    # Conflict lifecycle tests
    # =========================================================================

    def _setup_fact_conflict(self, memory):
        """Create a cluster with two conflicting active facts and an open conflict."""
        cluster = Concept(
            title="Cache config",
            summary="Cache facts",
            concept_type="fact_cluster",
            specifics=["TTL is 300s", "TTL is 600s"],
            evidence=["TTL is 300s", "TTL is 600s"],
        )
        memory.store.add_concept(cluster)
        fact_a = Fact(cluster_id=cluster.id, statement="TTL is 300s")
        fact_b = Fact(cluster_id=cluster.id, statement="TTL is 600s")
        memory.store.add_fact(fact_a)
        memory.store.add_fact(fact_b)
        conflict = Conflict(
            kind="fact",
            fact_a_id=fact_a.id,
            fact_b_id=fact_b.id,
            concept_ids=[cluster.id],
            description='"TTL is 300s" vs "TTL is 600s": contradictory values',
        )
        memory.store.add_conflict(conflict)
        cluster.conflicts = [{
            "fact_a": "TTL is 300s",
            "fact_b": "TTL is 600s",
            "fact_a_id": fact_a.id,
            "fact_b_id": fact_b.id,
            "reason": "contradictory values",
        }]
        memory.store.update_concept(cluster)
        return cluster, fact_a, fact_b, conflict

    @pytest.mark.asyncio
    async def test_resolve_fact_conflict(self, memory):
        cluster, fact_a, fact_b, conflict = self._setup_fact_conflict(memory)

        resolved = await memory.resolve_conflict(
            conflict.id,
            winning_fact_id=fact_b.id,
            note="600s confirmed in config",
            resolved_by="alice",
        )

        assert resolved.status == "resolved"
        assert resolved.winning_fact_id == fact_b.id
        assert resolved.resolved_by == "alice"

        # Loser superseded by winner
        loser = memory.store.get_fact(fact_a.id)
        assert not loser.is_active
        assert loser.superseded_by == fact_b.id
        assert memory.store.get_fact(fact_b.id).is_active

        # Cluster render cache refreshed, conflict dicts cleared
        updated_cluster = memory.store.get_concept(cluster.id)
        assert updated_cluster.specifics == ["TTL is 600s"]
        assert updated_cluster.conflicts == []

    @pytest.mark.asyncio
    async def test_resolve_requires_valid_winner(self, memory):
        _, fact_a, fact_b, conflict = self._setup_fact_conflict(memory)

        # Invalid winner should raise ValueError
        with pytest.raises(ValueError):
            await memory.resolve_conflict(conflict.id, winning_fact_id="bogus")

        # Still open
        assert memory.store.get_conflict(conflict.id).status == "open"

    @pytest.mark.asyncio
    async def test_dismiss_conflict_keeps_both_active(self, memory):
        cluster, fact_a, fact_b, conflict = self._setup_fact_conflict(memory)

        dismissed = memory.dismiss_conflict(
            conflict.id, note="different environments", dismissed_by="bob",
        )

        assert dismissed.status == "dismissed"
        assert memory.store.get_fact(fact_a.id).is_active
        assert memory.store.get_fact(fact_b.id).is_active

        # Warning cleared from the cluster
        assert memory.store.get_concept(cluster.id).conflicts == []

    @pytest.mark.asyncio
    async def test_list_conflicts_default_open(self, memory):
        _, fact_a, fact_b, conflict = self._setup_fact_conflict(memory)

        conflicts = memory.list_conflicts()
        assert len(conflicts) == 1
        
        await memory.resolve_conflict(conflict.id, winning_fact_id=fact_b.id)
        
        assert memory.list_conflicts() == []
        assert len(memory.list_conflicts(status="resolved")) == 1

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

    @pytest.mark.asyncio
    async def test_get_recent_episodes(self, memory):
        """Test get_recent_episodes method."""
        for i in range(5):
            await memory.remember(f"Episode {i}")

        result = memory.get_recent_episodes(limit=3)

        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_get_episodes_by_type(self, memory):
        """Test get_episodes_by_type method."""
        await memory.remember("Decision 1", episode_type=EpisodeType.DECISION)
        await memory.remember("Decision 2", episode_type=EpisodeType.DECISION)
        await memory.remember("Question", episode_type=EpisodeType.QUESTION)

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

    @pytest.mark.asyncio
    async def test_get_all_entities(self, memory):
        """Test get_all_entities method."""
        await memory.remember("Modified auth.ts", entities=["file:auth.ts", "person:bob"])

        entities = memory.get_all_entities()

        assert len(entities) == 2

    def test_get_episodes_mentioning(self, memory, sample_episode, sample_entity):
        """Test get_episodes_mentioning method."""
        memory.store.add_episode(sample_episode)
        memory.store.add_entity(sample_entity)
        memory.store.add_mention(sample_episode.id, sample_entity.id)

        result = memory.get_episodes_mentioning(sample_entity.id)

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_get_entity_mention_counts(self, memory):
        """Test get_entity_mention_counts method."""
        # Create multiple episodes mentioning same entity
        for i in range(3):
            await memory.remember(f"Episode {i}", entities=["file:common.py"])
        await memory.remember("Other", entities=["file:other.py"])

        counts = memory.get_entity_mention_counts()

        # Should be sorted by count
        assert counts[0][0].id == "file:common.py"
        assert counts[0][1] == 3

    # =========================================================================
    # get_stats tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_get_stats(self, memory, mock_embedding):
        """Test get_stats method."""
        await memory.remember("Episode 1")
        await memory.remember("Episode 2")

        stats = memory.get_stats()

        assert stats["episodes"] == 2
        assert stats["concepts"] == 0
        assert stats["unconsolidated_episodes"] == 2

    # =========================================================================
    # Import/Export tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_export_memory(self, memory, sample_concept):
        """Test export_memory method."""
        await memory.remember("Test episode")
        memory.store.add_concept(sample_concept)

        data = memory.export_memory()

        assert "episodes" in data
        assert "concepts" in data
        assert "version" in data
        assert len(data["episodes"]) == 1
        assert len(data["concepts"]) == 1

    @pytest.mark.asyncio
    async def test_export_memory_to_file(self, memory, sample_concept, tmp_path):
        """Test export_memory to file (manual write)."""
        await memory.remember("Test episode")

        export_path = tmp_path / "export.json"
        data = memory.export_memory()
        
        # Manual file write since export_memory doesn't take path anymore
        with open(export_path, "w") as f:
            json.dump(data, f)

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

    def test_import_memory_from_dict_with_episodes(self, memory, tmp_path):
        """Test import_memory from dictionary with episodes."""
        data = {
            "concepts": [],
            "episodes": [
                {
                    "id": "from_dict",
                    "content": "From dict",
                    "consolidated": False,
                    "metadata": {},
                    "concepts_activated": [],
                    "entity_ids": [],
                }
            ],
        }

        result = memory.import_memory(data)

        assert result["episodes_imported"] == 1

    # =========================================================================
    # Topic tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_update_episode_topic_reassign_and_clear(self, memory):
        ta = memory.create_topic("TopicAlpha", "")
        tb = memory.create_topic("TopicBeta", "")
        result = await memory.remember("hello", topic=ta.id)
        ep = memory.store.get_episode(result.episode_id)
        assert ep.topic_id == ta.id

        memory.update_episode(result.episode_id, topic=tb.name)
        ep = memory.store.get_episode(result.episode_id)
        assert ep.topic_id == tb.id

        memory.update_episode(result.episode_id, topic="")
        ep = memory.store.get_episode(result.episode_id)
        assert ep.topic_id is None

    def test_update_concept_topic_reassign_and_clear(self, memory):
        ta = memory.create_topic("TopicAlpha", "")
        tb = memory.create_topic("TopicBeta", "")
        c = Concept(summary="concept body", topic_id=ta.id)
        memory.store.add_concept(c)

        updated = memory.update_concept(c.id, topic=tb.name)
        assert updated is not None
        assert updated.topic_id == tb.id

        updated = memory.update_concept(c.id, topic="")
        assert updated is not None
        assert updated.topic_id is None


class TestMemoryInterfaceInitialization:
    """Tests for MemoryInterface initialization."""

    def test_init_with_store(self, mock_embedding, memory_store):
        """Test initialization with provided store."""
        memory = MemoryInterface(
            embedding=mock_embedding,
            store=memory_store,
        )

        assert memory.store is memory_store

    def test_init_creates_store(self, mock_embedding, temp_db_path):
        """Test initialization creates store from path."""
        memory = MemoryInterface(
            embedding=mock_embedding,
            db_path=temp_db_path,
        )

        assert memory.store is not None

    def test_init_default_values(self, mock_embedding, temp_db_path):
        """Test initialization with default values."""
        memory = MemoryInterface(
            embedding=mock_embedding,
            db_path=temp_db_path,
        )

        assert memory.default_recall_k == 3

    def test_init_custom_values(self, mock_embedding, temp_db_path):
        """Test initialization with custom values."""
        memory = MemoryInterface(
            embedding=mock_embedding,
            db_path=temp_db_path,
            default_recall_k=10,
            spread_hops=3,
        )

        assert memory.default_recall_k == 10

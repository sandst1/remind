"""Tests for memory retrieval with spreading activation."""

import pytest

from remind.retrieval import MemoryRetriever, ActivatedConcept
from remind.models import Concept, Episode, Entity, EntityType, Relation, RelationType, EpisodeType


class TestActivatedConcept:
    """Tests for ActivatedConcept dataclass."""

    def test_creation(self, sample_concept):
        """Test creating an activated concept."""
        ac = ActivatedConcept(
            concept=sample_concept,
            activation=0.85,
            source="embedding",
            hops=0,
        )
        assert ac.activation == 0.85
        assert ac.source == "embedding"
        assert ac.hops == 0

    def test_repr(self, sample_concept):
        """Test string representation."""
        ac = ActivatedConcept(
            concept=sample_concept,
            activation=0.75,
            source="spread",
            hops=1,
        )
        repr_str = repr(ac)
        assert "activation=0.750" in repr_str
        assert "source=spread" in repr_str

    def test_repr_embedding_source(self, sample_concept):
        """Test repr with embedding source."""
        ac = ActivatedConcept(
            concept=sample_concept,
            activation=0.9,
            source="embedding",
            hops=0,
        )
        repr_str = repr(ac)
        assert "source=embedding" in repr_str


class TestMemoryRetriever:
    """Tests for MemoryRetriever class."""

    @pytest.fixture
    def retriever(self, mock_embedding, memory_store):
        """Create a retriever with mock embedding."""
        return MemoryRetriever(
            embedding=mock_embedding,
            store=memory_store,
            initial_k=10,
            spread_hops=2,
            spread_decay=0.5,
            activation_threshold=0.1,
        )

    @pytest.mark.asyncio
    async def test_retrieve_empty_store(self, retriever):
        """Test retrieval from empty store returns empty list."""
        result = await retriever.retrieve("test query")
        assert result == []

    @pytest.mark.asyncio
    async def test_retrieve_finds_similar_concepts(
        self, retriever, memory_store, sample_concepts_with_relations, mock_embedding
    ):
        """Test basic retrieval finds similar concepts."""
        # Add concepts to store
        for concept in sample_concepts_with_relations:
            memory_store.add_concept(concept)

        # Set embedding for query to be similar to concept1
        mock_embedding.set_embedding(
            "python programming",
            [1.0, 0.0, 0.0] + [0.0] * 125
        )

        result = await retriever.retrieve("python programming", k=3)

        assert len(result) > 0
        # First result should be most similar
        assert result[0].concept.id == "concept1"
        assert result[0].source == "embedding"

    @pytest.mark.asyncio
    async def test_retrieve_returns_sorted_by_activation(
        self, retriever, memory_store, mock_embedding
    ):
        """Test results are sorted by activation level."""
        # Add concepts with different similarity levels
        c1 = Concept(
            id="high_match",
            summary="Python programming",
            confidence=0.9,
            embedding=[1.0, 0.0, 0.0] + [0.0] * 125,
        )
        c2 = Concept(
            id="low_match",
            summary="JavaScript coding",
            confidence=0.9,
            embedding=[0.1, 0.9, 0.0] + [0.0] * 125,
        )
        memory_store.add_concept(c1)
        memory_store.add_concept(c2)

        mock_embedding.set_embedding("python", [1.0, 0.0, 0.0] + [0.0] * 125)

        result = await retriever.retrieve("python", k=5)

        if len(result) >= 2:
            assert result[0].activation >= result[1].activation

    @pytest.mark.asyncio
    async def test_retrieve_spreads_activation(
        self, retriever, memory_store, sample_concepts_with_relations, mock_embedding
    ):
        """Test that activation spreads through relations."""
        # Add concepts to store
        for concept in sample_concepts_with_relations:
            memory_store.add_concept(concept)

        # Set embedding for query to match only concept1
        mock_embedding.set_embedding(
            "python programming",
            [1.0, 0.0, 0.0] + [0.0] * 125
        )

        result = await retriever.retrieve("python programming", k=5, include_weak=True)

        # Should find concept1 via embedding
        concept_ids = [ac.concept.id for ac in result]
        assert "concept1" in concept_ids

    @pytest.mark.asyncio
    async def test_retrieve_with_context(self, retriever, mock_embedding, memory_store):
        """Test retrieval includes context in embedding."""
        c = Concept(
            summary="Test concept",
            embedding=[0.5] * 128,
        )
        memory_store.add_concept(c)

        await retriever.retrieve("query", context="additional context")

        call = mock_embedding.get_call_history()[0]
        assert "additional context" in call["text"]

    @pytest.mark.asyncio
    async def test_retrieve_respects_k_limit(
        self, retriever, memory_store, mock_embedding
    ):
        """Test retrieval respects k limit."""
        # Add many concepts
        for i in range(10):
            c = Concept(
                id=f"concept_{i}",
                summary=f"Concept {i}",
                confidence=0.9,
                embedding=[float(i) / 10] + [0.0] * 127,
            )
            memory_store.add_concept(c)

        mock_embedding.set_embedding("test", [0.5] + [0.0] * 127)

        result = await retriever.retrieve("test", k=3)

        assert len(result) <= 3

    @pytest.mark.asyncio
    async def test_retrieve_weights_by_confidence(
        self, retriever, memory_store, mock_embedding
    ):
        """Test that concept confidence affects activation."""
        # Add two equally similar concepts with different confidence
        c1 = Concept(
            id="high_conf",
            summary="High confidence concept",
            confidence=0.95,
            embedding=[1.0, 0.0, 0.0] + [0.0] * 125,
        )
        c2 = Concept(
            id="low_conf",
            summary="Low confidence concept",
            confidence=0.3,
            embedding=[1.0, 0.0, 0.0] + [0.0] * 125,
        )
        memory_store.add_concept(c1)
        memory_store.add_concept(c2)

        mock_embedding.set_embedding("test", [1.0, 0.0, 0.0] + [0.0] * 125)

        result = await retriever.retrieve("test", k=5)

        # High confidence should have higher activation
        high_conf_result = next((r for r in result if r.concept.id == "high_conf"), None)
        low_conf_result = next((r for r in result if r.concept.id == "low_conf"), None)

        if high_conf_result and low_conf_result:
            assert high_conf_result.activation > low_conf_result.activation

    @pytest.mark.asyncio
    async def test_retrieve_by_tags(self, retriever, memory_store, sample_concepts_with_relations):
        """Test tag-based retrieval."""
        for concept in sample_concepts_with_relations:
            memory_store.add_concept(concept)

        result = await retriever.retrieve_by_tags(["programming", "python"])

        assert len(result) > 0
        # Concept with both tags should rank highest
        assert result[0].id == "concept1"

    @pytest.mark.asyncio
    async def test_retrieve_by_tags_single_tag(self, retriever, memory_store):
        """Test tag-based retrieval with single tag."""
        c1 = Concept(id="c1", summary="Test", tags=["python", "backend"])
        c2 = Concept(id="c2", summary="Test", tags=["javascript"])
        memory_store.add_concept(c1)
        memory_store.add_concept(c2)

        result = await retriever.retrieve_by_tags(["python"])

        assert len(result) == 1
        assert result[0].id == "c1"

    @pytest.mark.asyncio
    async def test_retrieve_by_tags_no_match(self, retriever, memory_store):
        """Test tag-based retrieval with no matches."""
        c = Concept(id="c1", summary="Test", tags=["python"])
        memory_store.add_concept(c)

        result = await retriever.retrieve_by_tags(["rust"])

        assert result == []

    @pytest.mark.asyncio
    async def test_retrieve_by_entity(self, retriever, memory_store, sample_episode, sample_entity):
        """Test entity-based retrieval."""
        # Add episode and entity with mention
        memory_store.add_episode(sample_episode)
        memory_store.add_entity(sample_entity)
        memory_store.add_mention(sample_episode.id, sample_entity.id)

        episodes = await retriever.retrieve_by_entity("file:src/auth.ts")

        assert len(episodes) == 1
        assert episodes[0].id == sample_episode.id

    @pytest.mark.asyncio
    async def test_retrieve_by_entity_multiple_episodes(self, retriever, memory_store):
        """Test entity retrieval with multiple episodes."""
        entity = Entity(id="file:test.py", type=EntityType.FILE, display_name="test.py")
        memory_store.add_entity(entity)

        for i in range(5):
            ep = Episode(content=f"Episode {i} about test.py")
            memory_store.add_episode(ep)
            memory_store.add_mention(ep.id, entity.id)

        episodes = await retriever.retrieve_by_entity("file:test.py")

        assert len(episodes) == 5

    @pytest.mark.asyncio
    async def test_retrieve_by_entity_respects_limit(self, retriever, memory_store):
        """Test entity retrieval respects limit."""
        entity = Entity(id="file:test.py", type=EntityType.FILE, display_name="test.py")
        memory_store.add_entity(entity)

        for i in range(10):
            ep = Episode(content=f"Episode {i}")
            memory_store.add_episode(ep)
            memory_store.add_mention(ep.id, entity.id)

        episodes = await retriever.retrieve_by_entity("file:test.py", limit=3)

        assert len(episodes) == 3

    @pytest.mark.asyncio
    async def test_retrieve_related_entities(self, retriever, memory_store):
        """Test finding co-occurring entities."""
        # Create episodes that mention multiple entities
        e1 = Episode(content="Alice worked on auth.ts", entity_ids=["person:alice", "file:auth.ts"])
        e2 = Episode(content="Alice also worked on user.ts", entity_ids=["person:alice", "file:user.ts"])
        e3 = Episode(content="Bob worked on auth.ts", entity_ids=["person:bob", "file:auth.ts"])

        memory_store.add_episode(e1)
        memory_store.add_episode(e2)
        memory_store.add_episode(e3)

        for eid in ["person:alice", "person:bob", "file:auth.ts", "file:user.ts"]:
            entity_type, name = eid.split(":", 1)
            memory_store.add_entity(Entity(
                id=eid,
                type=EntityType.PERSON if entity_type == "person" else EntityType.FILE,
                display_name=name,
            ))

        memory_store.add_mention(e1.id, "person:alice")
        memory_store.add_mention(e1.id, "file:auth.ts")
        memory_store.add_mention(e2.id, "person:alice")
        memory_store.add_mention(e2.id, "file:user.ts")
        memory_store.add_mention(e3.id, "person:bob")
        memory_store.add_mention(e3.id, "file:auth.ts")

        related = await retriever.retrieve_related_entities("file:auth.ts")

        assert len(related) == 2  # alice and bob
        entity_ids = [e.id for e, _ in related]
        assert "person:alice" in entity_ids
        assert "person:bob" in entity_ids

    @pytest.mark.asyncio
    async def test_retrieve_related_entities_sorted_by_count(self, retriever, memory_store):
        """Test related entities are sorted by co-occurrence count."""
        entity = Entity(id="file:main.py", type=EntityType.FILE, display_name="main.py")
        alice = Entity(id="person:alice", type=EntityType.PERSON, display_name="Alice")
        bob = Entity(id="person:bob", type=EntityType.PERSON, display_name="Bob")

        memory_store.add_entity(entity)
        memory_store.add_entity(alice)
        memory_store.add_entity(bob)

        # Alice mentioned 3 times with main.py, Bob only once
        # Note: entity_ids must be set on episodes for co-occurrence counting
        for i in range(3):
            ep = Episode(content=f"Alice ep {i}", entity_ids=["file:main.py", "person:alice"])
            memory_store.add_episode(ep)
            memory_store.add_mention(ep.id, "file:main.py")
            memory_store.add_mention(ep.id, "person:alice")

        ep_bob = Episode(content="Bob ep", entity_ids=["file:main.py", "person:bob"])
        memory_store.add_episode(ep_bob)
        memory_store.add_mention(ep_bob.id, "file:main.py")
        memory_store.add_mention(ep_bob.id, "person:bob")

        related = await retriever.retrieve_related_entities("file:main.py")

        assert related[0][0].id == "person:alice"
        assert related[0][1] == 3
        assert related[1][0].id == "person:bob"
        assert related[1][1] == 1

    @pytest.mark.asyncio
    async def test_find_related_chain(
        self, retriever, memory_store, sample_concepts_with_relations
    ):
        """Test finding path between concepts."""
        for concept in sample_concepts_with_relations:
            memory_store.add_concept(concept)

        # Find path from concept1 to concept3 (through concept2)
        path = await retriever.find_related_chain("concept1", "concept3")

        assert path is not None
        assert len(path) >= 2
        # Path should include concept1 and concept3
        path_ids = [c.id for c, _ in path]
        assert "concept1" in path_ids
        assert "concept3" in path_ids

    @pytest.mark.asyncio
    async def test_find_related_chain_direct(self, retriever, memory_store):
        """Test finding direct path between concepts."""
        c1 = Concept(id="start", summary="Start")
        c2 = Concept(id="end", summary="End")
        c1.relations.append(Relation(type=RelationType.IMPLIES, target_id="end", strength=0.8))

        memory_store.add_concept(c1)
        memory_store.add_concept(c2)

        path = await retriever.find_related_chain("start", "end")

        assert path is not None
        assert len(path) == 2
        assert path[0][0].id == "start"
        assert path[1][0].id == "end"

    @pytest.mark.asyncio
    async def test_find_related_chain_not_found(self, retriever, memory_store):
        """Test returns None when no path exists."""
        c1 = Concept(id="isolated1", summary="Isolated concept 1")
        c2 = Concept(id="isolated2", summary="Isolated concept 2")
        memory_store.add_concept(c1)
        memory_store.add_concept(c2)

        path = await retriever.find_related_chain("isolated1", "isolated2")
        assert path is None

    @pytest.mark.asyncio
    async def test_find_related_chain_nonexistent_concept(self, retriever, memory_store):
        """Test returns None for nonexistent concepts."""
        c1 = Concept(id="exists", summary="Existing concept")
        memory_store.add_concept(c1)

        path = await retriever.find_related_chain("exists", "nonexistent")
        assert path is None

        path = await retriever.find_related_chain("nonexistent", "exists")
        assert path is None


class TestRetrieverFormatting:
    """Tests for formatting methods."""

    @pytest.fixture
    def retriever(self, mock_embedding, memory_store):
        return MemoryRetriever(
            embedding=mock_embedding,
            store=memory_store,
        )

    def test_format_for_llm_empty(self, retriever):
        """Test formatting empty result list."""
        result = retriever.format_for_llm([])
        assert "No relevant memories found" in result

    def test_format_for_llm_with_concepts(self, retriever, sample_concept, memory_store):
        """Test formatting activated concepts."""
        memory_store.add_concept(sample_concept)

        activated = [ActivatedConcept(
            concept=sample_concept,
            activation=0.8,
            source="embedding",
            hops=0,
        )]

        result = retriever.format_for_llm(activated)

        assert "RELEVANT MEMORY" in result
        assert sample_concept.summary in result
        assert "confidence: 0.80" in result

    def test_format_for_llm_with_spread_source(self, retriever, sample_concept, memory_store):
        """Test formatting shows spread source."""
        memory_store.add_concept(sample_concept)

        activated = [ActivatedConcept(
            concept=sample_concept,
            activation=0.6,
            source="spread",
            hops=1,
        )]

        result = retriever.format_for_llm(activated)
        assert "via association" in result

    def test_format_for_llm_with_conditions(self, retriever, memory_store):
        """Test formatting includes conditions."""
        concept = Concept(
            summary="User prefers Python",
            conditions="for backend development",
            confidence=0.8,
        )
        memory_store.add_concept(concept)

        activated = [ActivatedConcept(
            concept=concept,
            activation=0.8,
            source="embedding",
            hops=0,
        )]

        result = retriever.format_for_llm(activated)
        assert "Applies when:" in result
        assert "backend development" in result

    def test_format_for_llm_with_exceptions(self, retriever, memory_store):
        """Test formatting includes exceptions."""
        concept = Concept(
            summary="User prefers Python",
            exceptions=["not for mobile", "not for games"],
            confidence=0.8,
        )
        memory_store.add_concept(concept)

        activated = [ActivatedConcept(
            concept=concept,
            activation=0.8,
            source="embedding",
            hops=0,
        )]

        result = retriever.format_for_llm(activated)
        assert "Exceptions:" in result
        assert "not for mobile" in result

    def test_format_for_llm_with_relations(self, retriever, memory_store):
        """Test formatting includes relations."""
        c1 = Concept(id="c1", summary="Main concept", confidence=0.8)
        c2 = Concept(id="c2", summary="Related concept", confidence=0.7)
        c1.relations.append(Relation(type=RelationType.IMPLIES, target_id="c2", strength=0.9))

        memory_store.add_concept(c1)
        memory_store.add_concept(c2)

        activated = [ActivatedConcept(
            concept=c1,
            activation=0.8,
            source="embedding",
            hops=0,
        )]

        result = retriever.format_for_llm(activated, include_relations=True)
        assert "implies:" in result
        assert "Related concept" in result

    def test_format_entity_context_empty(self, retriever):
        """Test formatting with no episodes."""
        result = retriever.format_entity_context("file:test.py", [])
        assert "No memories about" in result

    def test_format_entity_context_with_episodes(self, retriever, memory_store):
        """Test formatting entity context with episodes."""
        entity = Entity(id="file:auth.ts", type=EntityType.FILE, display_name="auth.ts")
        memory_store.add_entity(entity)

        episodes = [
            Episode(content="Made auth changes", episode_type=EpisodeType.DECISION),
            Episode(content="Found bug in auth", episode_type=EpisodeType.OBSERVATION),
        ]

        result = retriever.format_entity_context("file:auth.ts", episodes)

        assert "MEMORY ABOUT" in result
        assert "auth.ts" in result
        assert "DECISION" in result.upper()

    def test_format_entity_context_groups_by_type(self, retriever, memory_store):
        """Test formatting groups episodes by type."""
        entity = Entity(id="file:test.py", type=EntityType.FILE, display_name="test.py")
        memory_store.add_entity(entity)

        episodes = [
            Episode(content="Decision 1", episode_type=EpisodeType.DECISION),
            Episode(content="Decision 2", episode_type=EpisodeType.DECISION),
            Episode(content="Question 1", episode_type=EpisodeType.QUESTION),
            Episode(content="Observation 1", episode_type=EpisodeType.OBSERVATION),
        ]

        result = retriever.format_entity_context("file:test.py", episodes, include_type_breakdown=True)

        # Types should appear in order
        decision_pos = result.find("[DECISIONS]")
        question_pos = result.find("[QUESTIONS]")
        observation_pos = result.find("[OBSERVATIONS]")

        assert decision_pos < question_pos < observation_pos

    def test_format_entity_context_without_type_breakdown(self, retriever, memory_store):
        """Test formatting without type grouping."""
        entity = Entity(id="file:test.py", type=EntityType.FILE, display_name="test.py")
        memory_store.add_entity(entity)

        episodes = [
            Episode(content="Episode 1", episode_type=EpisodeType.OBSERVATION),
            Episode(content="Episode 2", episode_type=EpisodeType.DECISION),
        ]

        result = retriever.format_entity_context(
            "file:test.py", episodes, include_type_breakdown=False
        )

        # Should show type labels inline
        assert "[obs]" in result or "[dec]" in result

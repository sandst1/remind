"""Tests for hybrid recall (entity-overlap episode scoring) and fact episode type."""

import pytest
from datetime import datetime, timedelta

from remind.models import (
    Concept, Episode, Entity, EntityType, EpisodeType,
    Relation, RelationType,
)
from remind.retrieval import (
    MemoryRetriever, ActivatedConcept, ScoredEpisode, _EPISODE_TYPE_WEIGHTS,
)


class TestFactEpisodeType:
    """Tests for the FACT episode type."""

    def test_fact_in_episode_type_enum(self):
        assert EpisodeType.FACT.value == "fact"

    def test_create_fact_episode(self):
        ep = Episode(
            content="Redis cache TTL is 300 seconds",
            episode_type=EpisodeType.FACT,
        )
        assert ep.episode_type == EpisodeType.FACT
        assert ep.content == "Redis cache TTL is 300 seconds"

    def test_fact_serialization_round_trip(self):
        ep = Episode(
            content="API rate limit is 100 req/s per tenant",
            episode_type=EpisodeType.FACT,
            metadata={"source": "config"},
        )
        data = ep.to_dict()
        restored = Episode.from_dict(data)
        assert restored.episode_type == EpisodeType.FACT
        assert restored.content == ep.content

    def test_fact_type_weight_is_highest(self):
        assert _EPISODE_TYPE_WEIGHTS[EpisodeType.FACT] >= max(
            v for k, v in _EPISODE_TYPE_WEIGHTS.items() if k != EpisodeType.FACT
        )


class TestScoredEpisode:
    """Tests for the ScoredEpisode dataclass."""

    def test_creation(self):
        ep = Episode(content="test", episode_type=EpisodeType.FACT)
        se = ScoredEpisode(episode=ep, score=0.75)
        assert se.score == 0.75
        assert se.episode is ep

    def test_repr(self):
        ep = Episode(content="test", episode_type=EpisodeType.DECISION)
        se = ScoredEpisode(episode=ep, score=0.6)
        r = repr(se)
        assert "score=0.600" in r
        assert "type=decision" in r


class TestEpisodeScoring:
    """Tests for the _score_episode static method."""

    def test_entity_overlap_dominates(self):
        """Episodes with more entity overlap should score higher."""
        ep_high = Episode(
            content="ep1",
            entity_ids=["tool:redis", "concept:auth", "file:config.py"],
            episode_type=EpisodeType.OBSERVATION,
            consolidated=True,
        )
        ep_low = Episode(
            content="ep2",
            entity_ids=["tool:redis", "person:alice"],
            episode_type=EpisodeType.OBSERVATION,
            consolidated=True,
        )
        concept_entities = {"tool:redis", "concept:auth", "file:config.py"}
        now = datetime.now()

        score_high = MemoryRetriever._score_episode(ep_high, concept_entities, now)
        score_low = MemoryRetriever._score_episode(ep_low, concept_entities, now)
        assert score_high > score_low

    def test_unconsolidated_bonus(self):
        """Unconsolidated episodes should score higher than consolidated ones."""
        base = dict(
            content="test",
            entity_ids=["tool:redis"],
            episode_type=EpisodeType.OBSERVATION,
        )
        ep_uncons = Episode(**base, consolidated=False)
        ep_cons = Episode(**base, consolidated=True)
        entities = {"tool:redis"}
        now = datetime.now()

        score_uncons = MemoryRetriever._score_episode(ep_uncons, entities, now)
        score_cons = MemoryRetriever._score_episode(ep_cons, entities, now)
        assert score_uncons > score_cons

    def test_fact_type_scores_higher_than_meta(self):
        """Fact episodes should score higher than meta episodes (all else equal)."""
        base = dict(
            content="test",
            entity_ids=["tool:redis"],
            consolidated=True,
        )
        ep_fact = Episode(**base, episode_type=EpisodeType.FACT)
        ep_meta = Episode(**base, episode_type=EpisodeType.META)
        entities = {"tool:redis"}
        now = datetime.now()

        score_fact = MemoryRetriever._score_episode(ep_fact, entities, now)
        score_meta = MemoryRetriever._score_episode(ep_meta, entities, now)
        assert score_fact > score_meta

    def test_recency_boost(self):
        """Newer episodes should score slightly higher."""
        base = dict(
            content="test",
            entity_ids=["tool:redis"],
            episode_type=EpisodeType.OBSERVATION,
            consolidated=True,
        )
        now = datetime.now()
        ep_new = Episode(**base, created_at=now, updated_at=now)
        ep_old = Episode(**base, created_at=now - timedelta(days=60), updated_at=now - timedelta(days=60))
        entities = {"tool:redis"}

        score_new = MemoryRetriever._score_episode(ep_new, entities, now)
        score_old = MemoryRetriever._score_episode(ep_old, entities, now)
        assert score_new > score_old

    def test_no_entities_scores_low(self):
        """Episode with no entities should get minimal entity overlap score."""
        ep = Episode(
            content="test",
            entity_ids=[],
            episode_type=EpisodeType.OBSERVATION,
            consolidated=True,
        )
        now = datetime.now()
        score = MemoryRetriever._score_episode(ep, {"tool:redis"}, now)
        # Should still have some score from type weight + recency
        assert score > 0
        assert score < 0.5


class TestRetrieveRelatedEpisodes:
    """Tests for retrieve_related_episodes method."""

    @pytest.fixture
    def retriever(self, mock_embedding, memory_store):
        return MemoryRetriever(
            embedding=mock_embedding,
            store=memory_store,
        )

    def test_empty_activated_returns_empty(self, retriever):
        result = retriever.retrieve_related_episodes([])
        assert result == []

    def test_finds_episodes_sharing_entities(self, retriever, memory_store):
        """Episodes sharing entities with concept sources should be found."""
        # Source episode for concept
        source_ep = Episode(
            content="Redis config discussion",
            entity_ids=["tool:redis", "concept:caching"],
            entities_extracted=True,
        )
        memory_store.add_episode(source_ep)

        # Create entity + mention records
        for eid, etype in [("tool:redis", EntityType.TOOL), ("concept:caching", EntityType.SUBJECT)]:
            memory_store.add_entity(Entity(id=eid, type=etype, display_name=eid.split(":")[1]))
            memory_store.add_mention(source_ep.id, eid)

        # Concept that references the source episode
        concept = Concept(
            id="c1",
            summary="Redis caching configuration",
            confidence=0.8,
            source_episodes=[source_ep.id],
            embedding=[0.5] * 128,
        )
        memory_store.add_concept(concept)

        # Related episode (shares tool:redis entity)
        related_ep = Episode(
            content="Redis TTL is 300s",
            episode_type=EpisodeType.FACT,
            entity_ids=["tool:redis"],
        )
        memory_store.add_episode(related_ep)
        memory_store.add_mention(related_ep.id, "tool:redis")

        # Unrelated episode
        unrelated_ep = Episode(
            content="Postgres schema migration",
            entity_ids=["tool:postgres"],
        )
        memory_store.add_episode(unrelated_ep)
        memory_store.add_entity(Entity(id="tool:postgres", type=EntityType.TOOL, display_name="postgres"))
        memory_store.add_mention(unrelated_ep.id, "tool:postgres")

        activated = [ActivatedConcept(concept=concept, activation=0.8, source="embedding")]
        results = retriever.retrieve_related_episodes(activated, max_episodes=10)

        episode_ids = [se.episode.id for se in results]
        assert related_ep.id in episode_ids
        assert unrelated_ep.id not in episode_ids
        # Source episode should be excluded
        assert source_ep.id not in episode_ids

    def test_excludes_source_episodes(self, retriever, memory_store):
        """Source episodes of matched concepts should not appear in results."""
        ep = Episode(
            content="Source episode",
            entity_ids=["tool:redis"],
            entities_extracted=True,
        )
        memory_store.add_episode(ep)
        memory_store.add_entity(Entity(id="tool:redis", type=EntityType.TOOL, display_name="redis"))
        memory_store.add_mention(ep.id, "tool:redis")

        concept = Concept(
            id="c1",
            summary="Test",
            confidence=0.8,
            source_episodes=[ep.id],
            embedding=[0.5] * 128,
        )
        memory_store.add_concept(concept)

        activated = [ActivatedConcept(concept=concept, activation=0.8, source="embedding")]
        results = retriever.retrieve_related_episodes(activated)

        assert all(se.episode.id != ep.id for se in results)

    def test_results_sorted_by_score(self, retriever, memory_store):
        """Results should be sorted by score descending."""
        # Source episode
        source_ep = Episode(content="Source", entity_ids=["tool:redis", "concept:auth"])
        memory_store.add_episode(source_ep)
        for eid, etype in [("tool:redis", EntityType.TOOL), ("concept:auth", EntityType.SUBJECT)]:
            memory_store.add_entity(Entity(id=eid, type=etype, display_name=eid.split(":")[1]))
            memory_store.add_mention(source_ep.id, eid)

        concept = Concept(
            id="c1", summary="Test", confidence=0.8,
            source_episodes=[source_ep.id], embedding=[0.5] * 128,
        )
        memory_store.add_concept(concept)

        # Episode with 2 overlapping entities (higher score)
        ep_high = Episode(
            content="High overlap",
            entity_ids=["tool:redis", "concept:auth"],
            episode_type=EpisodeType.FACT,
        )
        memory_store.add_episode(ep_high)
        memory_store.add_mention(ep_high.id, "tool:redis")
        memory_store.add_mention(ep_high.id, "concept:auth")

        # Episode with 1 overlapping entity (lower score)
        ep_low = Episode(
            content="Low overlap",
            entity_ids=["tool:redis"],
            episode_type=EpisodeType.META,
            consolidated=True,
        )
        memory_store.add_episode(ep_low)
        memory_store.add_mention(ep_low.id, "tool:redis")

        activated = [ActivatedConcept(concept=concept, activation=0.8, source="embedding")]
        results = retriever.retrieve_related_episodes(activated)

        assert len(results) >= 2
        assert results[0].score >= results[1].score

    def test_respects_max_episodes(self, retriever, memory_store):
        """Should respect the max_episodes limit."""
        source_ep = Episode(content="Source", entity_ids=["tool:redis"])
        memory_store.add_episode(source_ep)
        memory_store.add_entity(Entity(id="tool:redis", type=EntityType.TOOL, display_name="redis"))
        memory_store.add_mention(source_ep.id, "tool:redis")

        concept = Concept(
            id="c1", summary="Test", confidence=0.8,
            source_episodes=[source_ep.id], embedding=[0.5] * 128,
        )
        memory_store.add_concept(concept)

        for i in range(10):
            ep = Episode(content=f"Episode {i}", entity_ids=["tool:redis"])
            memory_store.add_episode(ep)
            memory_store.add_mention(ep.id, "tool:redis")

        activated = [ActivatedConcept(concept=concept, activation=0.8, source="embedding")]
        results = retriever.retrieve_related_episodes(activated, max_episodes=3)
        assert len(results) <= 3


class TestStoreFindepisodesByEntities:
    """Tests for the find_episodes_by_entities store method."""

    def test_finds_matching_episodes(self, memory_store):
        """Should find episodes sharing the specified entities."""
        memory_store.add_entity(Entity(id="tool:redis", type=EntityType.TOOL, display_name="redis"))

        ep = Episode(content="Redis info", entity_ids=["tool:redis"])
        memory_store.add_episode(ep)
        memory_store.add_mention(ep.id, "tool:redis")

        results = memory_store.find_episodes_by_entities(["tool:redis"])
        assert len(results) == 1
        assert results[0].id == ep.id

    def test_excludes_specified_episodes(self, memory_store):
        """Should exclude episodes in the exclude set."""
        memory_store.add_entity(Entity(id="tool:redis", type=EntityType.TOOL, display_name="redis"))

        ep1 = Episode(content="Episode 1", entity_ids=["tool:redis"])
        ep2 = Episode(content="Episode 2", entity_ids=["tool:redis"])
        memory_store.add_episode(ep1)
        memory_store.add_episode(ep2)
        memory_store.add_mention(ep1.id, "tool:redis")
        memory_store.add_mention(ep2.id, "tool:redis")

        results = memory_store.find_episodes_by_entities(
            ["tool:redis"], exclude_episode_ids={ep1.id},
        )
        assert len(results) == 1
        assert results[0].id == ep2.id

    def test_ordered_by_overlap_count(self, memory_store):
        """Episodes with more matching entities should come first."""
        for eid, etype in [("tool:redis", EntityType.TOOL), ("concept:auth", EntityType.SUBJECT)]:
            memory_store.add_entity(Entity(id=eid, type=etype, display_name=eid.split(":")[1]))

        ep_two = Episode(content="Two entities", entity_ids=["tool:redis", "concept:auth"])
        ep_one = Episode(content="One entity", entity_ids=["tool:redis"])
        memory_store.add_episode(ep_two)
        memory_store.add_episode(ep_one)
        memory_store.add_mention(ep_two.id, "tool:redis")
        memory_store.add_mention(ep_two.id, "concept:auth")
        memory_store.add_mention(ep_one.id, "tool:redis")

        results = memory_store.find_episodes_by_entities(["tool:redis", "concept:auth"])
        assert len(results) == 2
        assert results[0].id == ep_two.id

    def test_empty_entity_ids(self, memory_store):
        """Empty entity list should return empty results."""
        results = memory_store.find_episodes_by_entities([])
        assert results == []

    def test_respects_limit(self, memory_store):
        """Should respect the limit parameter."""
        memory_store.add_entity(Entity(id="tool:redis", type=EntityType.TOOL, display_name="redis"))

        for i in range(10):
            ep = Episode(content=f"Episode {i}", entity_ids=["tool:redis"])
            memory_store.add_episode(ep)
            memory_store.add_mention(ep.id, "tool:redis")

        results = memory_store.find_episodes_by_entities(["tool:redis"], limit=3)
        assert len(results) == 3

    def test_excludes_soft_deleted(self, memory_store):
        """Should not return soft-deleted episodes."""
        memory_store.add_entity(Entity(id="tool:redis", type=EntityType.TOOL, display_name="redis"))

        ep = Episode(content="Will be deleted", entity_ids=["tool:redis"])
        memory_store.add_episode(ep)
        memory_store.add_mention(ep.id, "tool:redis")

        memory_store.delete_episode(ep.id)

        results = memory_store.find_episodes_by_entities(["tool:redis"])
        assert len(results) == 0

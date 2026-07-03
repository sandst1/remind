"""Tests for the deterministic fact processing module."""

import pytest
from datetime import datetime

from remind.facts import (
    jaccard_similarity,
    find_matching_cluster,
    create_fact_cluster,
    detect_collisions,
    create_fact_from_episode,
    FactResult,
    ClusterMatch,
)
from remind.models import Episode, Concept, Fact, Entity, EntityType


class TestJaccardSimilarity:
    """Tests for Jaccard similarity function."""
    
    def test_identical_sets(self):
        result = jaccard_similarity({"a", "b", "c"}, {"a", "b", "c"})
        assert result == 1.0
    
    def test_disjoint_sets(self):
        result = jaccard_similarity({"a", "b"}, {"c", "d"})
        assert result == 0.0
    
    def test_partial_overlap(self):
        result = jaccard_similarity({"a", "b", "c"}, {"b", "c", "d"})
        assert result == pytest.approx(0.5)  # 2/4
    
    def test_empty_sets(self):
        assert jaccard_similarity(set(), set()) == 0.0
        assert jaccard_similarity({"a"}, set()) == 0.0
        assert jaccard_similarity(set(), {"b"}) == 0.0
    
    def test_subset(self):
        result = jaccard_similarity({"a", "b"}, {"a", "b", "c", "d"})
        assert result == pytest.approx(0.5)  # 2/4


class TestFindMatchingCluster:
    """Tests for cluster matching by entity overlap."""
    
    def test_no_entities_returns_none(self, memory_store):
        result = find_matching_cluster(memory_store, [])
        assert result is None
    
    def test_no_clusters_returns_none(self, memory_store):
        result = find_matching_cluster(memory_store, ["concept:caching"])
        assert result is None
    
    def test_finds_matching_cluster(self, memory_store):
        # Create entity and cluster
        entity = Entity(id="tool:redis", type=EntityType.TOOL, display_name="Redis")
        memory_store.add_entity(entity)
        
        cluster = Concept(
            title="Redis config",
            summary="Facts about Redis",
            concept_type="fact_cluster",
            entity_ids=["tool:redis"],
        )
        memory_store.add_concept(cluster)
        
        result = find_matching_cluster(memory_store, ["tool:redis"])
        
        assert result is not None
        assert result.cluster.id == cluster.id
        assert result.similarity == 1.0
        assert "tool:redis" in result.shared_entities
    
    def test_returns_best_match(self, memory_store):
        # Create two clusters with different overlaps
        for eid in ["tool:redis", "subject:caching", "subject:performance"]:
            memory_store.add_entity(Entity(id=eid, type=EntityType.SUBJECT))
        
        cluster1 = Concept(
            id="cluster1",
            title="Redis config",
            concept_type="fact_cluster",
            entity_ids=["tool:redis"],
        )
        cluster2 = Concept(
            id="cluster2",
            title="Caching performance",
            concept_type="fact_cluster",
            entity_ids=["subject:caching", "subject:performance"],
        )
        memory_store.add_concept(cluster1)
        memory_store.add_concept(cluster2)
        
        # Query with overlap to both
        result = find_matching_cluster(
            memory_store,
            ["subject:caching", "subject:performance", "tool:redis"],
            threshold=0.3,
        )
        
        # Should match cluster2 with 2/4 overlap
        assert result is not None
        assert result.cluster.id == "cluster2"
    
    def test_threshold_filtering(self, memory_store):
        entity = Entity(id="tool:redis", type=EntityType.TOOL)
        memory_store.add_entity(entity)
        
        cluster = Concept(
            title="Redis config",
            concept_type="fact_cluster",
            entity_ids=["tool:redis", "concept:other"],
        )
        memory_store.add_concept(cluster)
        
        # Low overlap shouldn't match with high threshold
        result = find_matching_cluster(
            memory_store,
            ["tool:redis", "concept:unrelated1", "concept:unrelated2"],
            threshold=0.6,
        )
        assert result is None


class TestCreateFactCluster:
    """Tests for fact cluster creation."""
    
    def test_creates_cluster_with_single_entity(self, memory_store):
        entity = Entity(id="tool:redis", type=EntityType.TOOL, display_name="Redis")
        memory_store.add_entity(entity)
        
        cluster = create_fact_cluster(
            memory_store,
            ["tool:redis"],
            "Cache TTL is 300s",
        )
        
        assert cluster.concept_type == "fact_cluster"
        assert "Redis" in cluster.title
        assert cluster.specifics == "Cache TTL is 300s"
    
    def test_creates_cluster_with_multiple_entities(self, memory_store):
        for eid in ["tool:redis", "subject:caching", "file:config.py"]:
            etype = EntityType.TOOL if eid.startswith("tool:") else (
                EntityType.SUBJECT if eid.startswith("subject:") else EntityType.FILE
            )
            memory_store.add_entity(Entity(id=eid, type=etype, display_name=eid.split(":")[1]))
        
        cluster = create_fact_cluster(
            memory_store,
            ["tool:redis", "subject:caching", "file:config.py"],
            "Initial fact",
        )
        
        assert "redis" in cluster.title.lower()
        assert "caching" in cluster.title.lower()
    
    def test_cluster_has_entity_ids(self, memory_store):
        entity = Entity(id="tool:redis", type=EntityType.TOOL)
        memory_store.add_entity(entity)
        
        cluster = create_fact_cluster(memory_store, ["tool:redis"], "test")
        
        assert "tool:redis" in cluster.entity_ids


class TestDetectCollisions:
    """Tests for collision detection."""
    
    def _setup_cluster_with_fact(self, store):
        cluster = Concept(
            id="cluster1",
            title="Redis config",
            concept_type="fact_cluster",
            entity_ids=["tool:redis"],
        )
        store.add_concept(cluster)
        
        fact = Fact(
            id="fact1",
            cluster_id=cluster.id,
            statement="Cache TTL is 300s",
            entity_ids=["tool:redis"],
            valid_from=datetime.now(),
        )
        store.add_fact(fact)
        
        return cluster, fact
    
    def test_detects_entity_overlap(self, memory_store):
        cluster, existing_fact = self._setup_cluster_with_fact(memory_store)
        
        new_fact = Fact(
            id="fact2",
            cluster_id=cluster.id,
            statement="Cache TTL is 600s",
            entity_ids=["tool:redis"],
        )
        
        collisions = detect_collisions(
            memory_store,
            cluster.id,
            new_fact,
            ["tool:redis"],
        )
        
        assert len(collisions) == 1
        assert collisions[0].id == existing_fact.id
    
    def test_no_collision_without_overlap(self, memory_store):
        cluster, _ = self._setup_cluster_with_fact(memory_store)
        
        new_fact = Fact(
            id="fact2",
            cluster_id=cluster.id,
            statement="Redis version is 7.0",
            entity_ids=["concept:version"],
        )
        
        collisions = detect_collisions(
            memory_store,
            cluster.id,
            new_fact,
            ["concept:version"],
        )
        
        assert len(collisions) == 0
    
    def test_excludes_new_fact_from_results(self, memory_store):
        cluster, _ = self._setup_cluster_with_fact(memory_store)
        
        # Same fact should not collide with itself
        new_fact = Fact(
            id="fact1",  # Same ID
            cluster_id=cluster.id,
            statement="test",
            entity_ids=["tool:redis"],
        )
        
        collisions = detect_collisions(
            memory_store,
            cluster.id,
            new_fact,
            ["tool:redis"],
        )
        
        assert len(collisions) == 0


class TestCreateFactFromEpisode:
    """Tests for the main fact creation entry point."""
    
    def test_creates_fact_and_cluster(self, memory_store):
        entity = Entity(id="tool:redis", type=EntityType.TOOL, display_name="Redis")
        memory_store.add_entity(entity)
        
        episode = Episode(
            content="Cache TTL is 300s",
            episode_type="fact",
            entity_ids=["tool:redis"],
        )
        memory_store.add_episode(episode)
        
        result = create_fact_from_episode(memory_store, episode)
        
        assert isinstance(result, FactResult)
        assert result.cluster_created is True
        assert result.fact_id is not None
        assert result.cluster_id is not None
        assert result.episode_id == episode.id
    
    def test_adds_to_existing_cluster(self, memory_store):
        entity = Entity(id="tool:redis", type=EntityType.TOOL)
        memory_store.add_entity(entity)
        
        # Create first fact
        ep1 = Episode(
            content="Cache TTL is 300s",
            episode_type="fact",
            entity_ids=["tool:redis"],
        )
        memory_store.add_episode(ep1)
        result1 = create_fact_from_episode(memory_store, ep1)
        
        # Create second fact
        ep2 = Episode(
            content="Cache size is 1GB",
            episode_type="fact",
            entity_ids=["tool:redis"],
        )
        memory_store.add_episode(ep2)
        result2 = create_fact_from_episode(memory_store, ep2)
        
        assert result2.cluster_created is False
        assert result2.cluster_id == result1.cluster_id
    
    def test_detects_collisions(self, memory_store):
        entity = Entity(id="tool:redis", type=EntityType.TOOL)
        memory_store.add_entity(entity)
        
        # Create first fact
        ep1 = Episode(
            content="Cache TTL is 300s",
            episode_type="fact",
            entity_ids=["tool:redis"],
        )
        memory_store.add_episode(ep1)
        create_fact_from_episode(memory_store, ep1)
        
        # Create potentially conflicting fact
        ep2 = Episode(
            content="Cache TTL is 600s",
            episode_type="fact",
            entity_ids=["tool:redis"],
        )
        memory_store.add_episode(ep2)
        result2 = create_fact_from_episode(memory_store, ep2)
        
        assert len(result2.collisions) == 1
        assert "300s" in result2.collisions[0].statement
    
    def test_marks_episode_processed(self, memory_store):
        entity = Entity(id="tool:redis", type=EntityType.TOOL)
        memory_store.add_entity(entity)
        
        episode = Episode(
            content="Cache TTL is 300s",
            episode_type="fact",
            entity_ids=["tool:redis"],
        )
        memory_store.add_episode(episode)
        
        assert episode.consolidated is False
        
        create_fact_from_episode(memory_store, episode)
        
        updated = memory_store.get_episode(episode.id)
        assert updated.consolidated is True
    
    def test_preserves_provenance(self, memory_store):
        entity = Entity(id="tool:redis", type=EntityType.TOOL)
        memory_store.add_entity(entity)
        
        episode = Episode(
            content="Cache TTL is 300s",
            episode_type="fact",
            entity_ids=["tool:redis"],
            asserted_by="alice",
            source_ref="https://example.com/pr/1",
        )
        memory_store.add_episode(episode)
        
        result = create_fact_from_episode(memory_store, episode)
        
        fact = memory_store.get_fact(result.fact_id)
        assert fact.asserted_by == "alice"
        assert fact.source_ref == "https://example.com/pr/1"

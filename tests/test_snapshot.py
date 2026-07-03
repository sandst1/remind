"""Tests for the snapshot engine (batch memory reads)."""

import pytest
from datetime import datetime

from remind.snapshot import (
    parse_scopes,
    SnapshotEngine,
    SnapshotScope,
    _episode_to_dict,
    _concept_to_dict,
    _fact_to_dict,
)
from remind.models import Episode, Concept, Fact, Conflict, Entity, EntityType, Topic


class TestParseScopes:
    """Tests for scope specification parsing."""
    
    def test_simple_scopes(self):
        scopes = parse_scopes(["pending", "conflicts", "stats"])
        
        assert len(scopes) == 3
        assert scopes[0].scope_type == "pending"
        assert scopes[0].value is None
        assert scopes[1].scope_type == "conflicts"
        assert scopes[2].scope_type == "stats"
    
    def test_parameterized_scopes(self):
        scopes = parse_scopes([
            "entity:concept:caching",
            "recent:10",
            "concept:abc123",
        ])
        
        assert len(scopes) == 3
        assert scopes[0].scope_type == "entity"
        assert scopes[0].value == "concept:caching"
        assert scopes[1].scope_type == "recent"
        assert scopes[1].value == "10"
        assert scopes[2].scope_type == "concept"
        assert scopes[2].value == "abc123"
    
    def test_query_scope(self):
        scopes = parse_scopes(["query:authentication issues"])
        
        assert scopes[0].scope_type == "query"
        assert scopes[0].value == "authentication issues"


class TestHelperFunctions:
    """Tests for dict conversion helper functions."""
    
    def test_episode_to_dict(self):
        episode = Episode(
            id="ep123",
            content="Test content",
            episode_type="decision",
            entity_ids=["file:test.py"],
            asserted_by="alice",
            consolidated=True,
        )
        
        d = _episode_to_dict(episode)
        
        assert d["id"] == "ep123"
        assert d["type"] == "decision"
        assert d["content"] == "Test content"
        assert d["entity_ids"] == ["file:test.py"]
        assert d["asserted_by"] == "alice"
        assert d["processed"] is True
    
    def test_concept_to_dict(self):
        concept = Concept(
            id="concept123",
            title="Test Concept",
            summary="A test concept",
            concept_type="pattern",
            confidence=0.8,
        )
        
        d = _concept_to_dict(concept)
        
        assert d["id"] == "concept123"
        assert d["title"] == "Test Concept"
        assert d["type"] == "pattern"
        assert d["confidence"] == 0.8
    
    def test_fact_to_dict(self):
        fact = Fact(
            id="fact123",
            cluster_id="cluster1",
            statement="Cache TTL is 300s",
            valid_from=datetime(2024, 1, 1),
            asserted_by="bob",
        )
        
        d = _fact_to_dict(fact)
        
        assert d["id"] == "fact123"
        assert d["cluster_id"] == "cluster1"
        assert d["statement"] == "Cache TTL is 300s"
        assert d["active"] is True
        assert d["asserted_by"] == "bob"


class TestSnapshotEnginePending:
    """Tests for pending scope."""
    
    @pytest.fixture
    def engine(self, memory_store, mock_embedding):
        return SnapshotEngine(memory_store, mock_embedding)
    
    @pytest.mark.asyncio
    async def test_pending_empty(self, engine):
        result = await engine.snapshot(["pending"])
        
        assert "pending" in result
        assert result["pending"]["count"] == 0
        assert result["pending"]["episodes"] == []
    
    @pytest.mark.asyncio
    async def test_pending_with_episodes(self, engine, memory_store):
        ep1 = Episode(content="Pending 1")
        ep2 = Episode(content="Pending 2")
        memory_store.add_episode(ep1)
        memory_store.add_episode(ep2)
        
        result = await engine.snapshot(["pending"])
        
        assert result["pending"]["count"] == 2
        assert len(result["pending"]["episodes"]) == 2
    
    @pytest.mark.asyncio
    async def test_pending_includes_entities(self, engine, memory_store):
        entity = Entity(id="file:test.py", type=EntityType.FILE, display_name="test.py")
        memory_store.add_entity(entity)
        
        ep = Episode(content="Test", entity_ids=["file:test.py"])
        memory_store.add_episode(ep)
        
        result = await engine.snapshot(["pending"])
        
        assert len(result["pending"]["entities"]) == 1
        assert result["pending"]["entities"][0]["id"] == "file:test.py"


class TestSnapshotEngineConflicts:
    """Tests for conflicts scope."""
    
    @pytest.fixture
    def engine(self, memory_store, mock_embedding):
        return SnapshotEngine(memory_store, mock_embedding)
    
    @pytest.mark.asyncio
    async def test_conflicts_empty(self, engine):
        result = await engine.snapshot(["conflicts"])
        
        assert "conflicts" in result
        assert result["conflicts"]["count"] == 0
    
    @pytest.mark.asyncio
    async def test_conflicts_with_data(self, engine, memory_store):
        fact_a = Fact(id="fact_a", statement="A", cluster_id="c1")
        fact_b = Fact(id="fact_b", statement="B", cluster_id="c1")
        memory_store.add_fact(fact_a)
        memory_store.add_fact(fact_b)
        
        conflict = Conflict(
            kind="fact",
            fact_a_id=fact_a.id,
            fact_b_id=fact_b.id,
            status="open",
            description="A vs B",
        )
        memory_store.add_conflict(conflict)
        
        result = await engine.snapshot(["conflicts"])
        
        assert result["conflicts"]["count"] == 1
        c = result["conflicts"]["conflicts"][0]
        assert "fact_a" in c
        assert c["fact_a"]["statement"] == "A"


class TestSnapshotEngineEntity:
    """Tests for entity scope."""
    
    @pytest.fixture
    def engine(self, memory_store, mock_embedding):
        return SnapshotEngine(memory_store, mock_embedding)
    
    @pytest.mark.asyncio
    async def test_entity_not_found(self, engine):
        result = await engine.snapshot(["entity:nonexistent"])
        
        assert "entity:nonexistent" in result
        assert "error" in result["entity:nonexistent"]
    
    @pytest.mark.asyncio
    async def test_entity_with_episodes(self, engine, memory_store):
        entity = Entity(id="file:test.py", type=EntityType.FILE, display_name="test.py")
        memory_store.add_entity(entity)
        
        ep = Episode(content="Test", entity_ids=["file:test.py"])
        memory_store.add_episode(ep)
        memory_store.add_mention(ep.id, entity.id)
        
        result = await engine.snapshot(["entity:file:test.py"])
        
        key = "entity:file:test.py"
        assert key in result
        assert result[key]["entity"]["id"] == "file:test.py"
        assert len(result[key]["episodes"]) == 1


class TestSnapshotEngineConcept:
    """Tests for concept scope."""
    
    @pytest.fixture
    def engine(self, memory_store, mock_embedding):
        return SnapshotEngine(memory_store, mock_embedding)
    
    @pytest.mark.asyncio
    async def test_concept_not_found(self, engine):
        result = await engine.snapshot(["concept:nonexistent"])
        
        assert "error" in result["concept:nonexistent"]
    
    @pytest.mark.asyncio
    async def test_concept_basic(self, engine, memory_store):
        concept = Concept(
            id="concept123",
            title="Test Pattern",
            summary="A test pattern",
            concept_type="pattern",
        )
        memory_store.add_concept(concept)
        
        result = await engine.snapshot(["concept:concept123"])
        
        key = "concept:concept123"
        assert key in result
        assert result[key]["concept"]["title"] == "Test Pattern"
    
    @pytest.mark.asyncio
    async def test_fact_cluster_includes_facts(self, engine, memory_store):
        cluster = Concept(
            id="cluster1",
            title="Redis config",
            concept_type="fact_cluster",
        )
        memory_store.add_concept(cluster)
        
        active_fact = Fact(
            id="fact1",
            cluster_id=cluster.id,
            statement="Active fact",
        )
        superseded_fact = Fact(
            id="fact2",
            cluster_id=cluster.id,
            statement="Old fact",
            valid_to=datetime.now(),
        )
        memory_store.add_fact(active_fact)
        memory_store.add_fact(superseded_fact)
        
        result = await engine.snapshot(["concept:cluster1"])
        
        key = "concept:cluster1"
        assert len(result[key]["active_facts"]) == 1
        assert len(result[key]["superseded_facts"]) == 1
        assert result[key]["active_facts"][0]["statement"] == "Active fact"


class TestSnapshotEngineRecent:
    """Tests for recent scope."""
    
    @pytest.fixture
    def engine(self, memory_store, mock_embedding):
        return SnapshotEngine(memory_store, mock_embedding)
    
    @pytest.mark.asyncio
    async def test_recent_default(self, engine, memory_store):
        for i in range(15):
            memory_store.add_episode(Episode(content=f"Episode {i}"))
        
        result = await engine.snapshot(["recent:10"])
        
        assert result["recent"]["count"] == 10
    
    @pytest.mark.asyncio
    async def test_recent_custom_limit(self, engine, memory_store):
        for i in range(10):
            memory_store.add_episode(Episode(content=f"Episode {i}"))
        
        result = await engine.snapshot(["recent:5"])
        
        assert result["recent"]["count"] == 5


class TestSnapshotEngineStats:
    """Tests for stats scope."""
    
    @pytest.fixture
    def engine(self, memory_store, mock_embedding):
        return SnapshotEngine(memory_store, mock_embedding)
    
    @pytest.mark.asyncio
    async def test_stats_empty(self, engine):
        result = await engine.snapshot(["stats"])
        
        assert "stats" in result
        assert result["stats"]["total_episodes"] == 0
        assert result["stats"]["total_concepts"] == 0
        assert result["stats"]["pending_episodes"] == 0
    
    @pytest.mark.asyncio
    async def test_stats_with_data(self, engine, memory_store):
        # Add episodes
        for i in range(5):
            ep = Episode(content=f"Episode {i}", episode_type="observation")
            if i < 2:
                ep.consolidated = True
            memory_store.add_episode(ep)
        
        # Add concepts
        memory_store.add_concept(Concept(title="C1", concept_type="pattern"))
        memory_store.add_concept(Concept(title="C2", concept_type="fact_cluster"))
        
        # Add open conflict
        memory_store.add_conflict(Conflict(kind="fact", status="open"))
        
        result = await engine.snapshot(["stats"])
        
        assert result["stats"]["total_episodes"] == 5
        assert result["stats"]["total_concepts"] == 2
        assert result["stats"]["pending_episodes"] == 3
        assert result["stats"]["open_conflicts"] == 1
        assert result["stats"]["episode_types"]["observation"] == 5
        assert result["stats"]["concept_types"]["pattern"] == 1
        assert result["stats"]["concept_types"]["fact_cluster"] == 1


class TestSnapshotEngineTopic:
    """Tests for topic scope."""
    
    @pytest.fixture
    def engine(self, memory_store, mock_embedding):
        return SnapshotEngine(memory_store, mock_embedding)
    
    @pytest.mark.asyncio
    async def test_topic_not_found(self, engine):
        result = await engine.snapshot(["topic:nonexistent"])
        
        assert "error" in result["topic:nonexistent"]
    
    @pytest.mark.asyncio
    async def test_topic_with_data(self, engine, memory_store):
        topic = Topic(id="arch", name="Architecture", description="")
        memory_store.create_topic(topic)
        
        ep = Episode(content="Test", topic_id="arch")
        memory_store.add_episode(ep)
        
        result = await engine.snapshot(["topic:arch"])
        
        key = "topic:arch"
        assert key in result
        assert result[key]["topic"]["name"] == "Architecture"
        assert result[key]["episode_count"] == 1


class TestSnapshotEngineMultipleScopes:
    """Tests for combining multiple scopes."""
    
    @pytest.fixture
    def engine(self, memory_store, mock_embedding):
        return SnapshotEngine(memory_store, mock_embedding)
    
    @pytest.mark.asyncio
    async def test_multiple_scopes(self, engine, memory_store):
        ep = Episode(content="Test")
        memory_store.add_episode(ep)
        
        result = await engine.snapshot(["pending", "stats", "recent:5"])
        
        assert "pending" in result
        assert "stats" in result
        assert "recent" in result
        assert "timestamp" in result
        assert "scopes" in result
    
    @pytest.mark.asyncio
    async def test_unknown_scope_returns_error(self, engine):
        result = await engine.snapshot(["unknown_scope"])
        
        assert "error:unknown_scope" in result

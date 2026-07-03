"""Tests for the apply engine (batch memory operations)."""

import pytest
import json

from remind.apply import (
    parse_compact_line,
    parse_changeset,
    ApplyEngine,
    ApplyResult,
    OpResult,
    OpError,
)
from remind.models import Episode, Concept, Fact, Conflict, Entity, EntityType


class TestParseCompactLine:
    """Tests for compact line format parsing."""
    
    def test_simple_remember(self):
        op, err = parse_compact_line(
            'remember t=fact e=tool:redis "Cache TTL is 600s"',
            1,
        )
        
        assert err is None
        assert op["op"] == "remember"
        assert op["t"] == "fact"
        assert op["e"] == "tool:redis"
        assert op["content"] == "Cache TTL is 600s"
    
    def test_remember_with_ref(self):
        op, err = parse_compact_line(
            'remember as=f1 t=fact "Cache TTL is 600s"',
            1,
        )
        
        assert err is None
        assert op["as"] == "f1"
    
    def test_supersede(self):
        op, err = parse_compact_line(
            'supersede old=fact:abc123 new=$f1',
            1,
        )
        
        assert err is None
        assert op["op"] == "supersede"
        assert op["old"] == "fact:abc123"
        assert op["new"] == "$f1"
    
    def test_resolve_with_note(self):
        op, err = parse_compact_line(
            'resolve id=conflict:7 winner=fact:b3d01 "confirmed by bob"',
            1,
        )
        
        assert err is None
        assert op["op"] == "resolve"
        assert op["id"] == "conflict:7"
        assert op["winner"] == "fact:b3d01"
        assert op["note"] == "confirmed by bob"
    
    def test_comma_separated_entities(self):
        op, err = parse_compact_line(
            'remember t=fact e=tool:redis,concept:caching "test"',
            1,
        )
        
        assert err is None
        assert op["e"] == ["tool:redis", "concept:caching"]
    
    def test_processed_with_ids(self):
        op, err = parse_compact_line(
            'processed ids=ep:11,ep:12',
            1,
        )
        
        assert err is None
        assert op["op"] == "processed"
        assert op["ids"] == ["ep:11", "ep:12"]
    
    def test_empty_line_returns_none(self):
        op, err = parse_compact_line("", 1)
        assert op is None
        assert err is None
    
    def test_comment_returns_none(self):
        op, err = parse_compact_line("# This is a comment", 1)
        assert op is None
        assert err is None
    
    def test_newline_escape(self):
        op, err = parse_compact_line(
            'remember t=fact "Line 1\\nLine 2"',
            1,
        )
        
        assert err is None
        assert op["content"] == "Line 1\nLine 2"
    
    def test_parse_error_returns_op_error(self):
        # Unterminated quote
        op, err = parse_compact_line('remember t=fact "unterminated', 1)
        
        assert op is None
        assert err is not None
        assert err.line == 1
        assert "Parse error" in err.message


class TestParseChangeset:
    """Tests for changeset parsing (auto-detection)."""
    
    def test_json_array(self):
        text = '[{"op": "remember", "content": "test"}]'
        ops, errors = parse_changeset(text)
        
        assert len(ops) == 1
        assert ops[0]["op"] == "remember"
        assert len(errors) == 0
    
    def test_json_object(self):
        text = '{"op": "remember", "content": "test"}'
        ops, errors = parse_changeset(text)
        
        assert len(ops) == 1
        assert ops[0]["op"] == "remember"
    
    def test_compact_format(self):
        text = '''
remember t=fact "Fact 1"
remember t=fact "Fact 2"
processed ids=ep:1,ep:2
'''
        ops, errors = parse_changeset(text)
        
        assert len(ops) == 3
        assert len(errors) == 0
        assert ops[0]["op"] == "remember"
        assert ops[1]["op"] == "remember"
        assert ops[2]["op"] == "processed"
    
    def test_json_parse_error(self):
        text = '[{invalid json}'
        ops, errors = parse_changeset(text)
        
        assert len(ops) == 0
        assert len(errors) == 1
        assert "JSON parse error" in errors[0].message
    
    def test_empty_returns_empty(self):
        ops, errors = parse_changeset("")
        assert ops == []
        assert errors == []


class TestApplyEngineValidation:
    """Tests for apply engine validation."""
    
    @pytest.fixture
    def engine(self, memory_store, mock_embedding):
        return ApplyEngine(memory_store, mock_embedding)
    
    def test_validates_unknown_op(self, engine):
        errors = engine._validate_ops([{"op": "unknown_op"}])
        
        assert len(errors) == 1
        assert "Unknown operation" in errors[0].message
    
    def test_validates_missing_op(self, engine):
        errors = engine._validate_ops([{"content": "test"}])
        
        assert len(errors) == 1
        assert "Missing 'op'" in errors[0].message
    
    def test_validates_remember_content(self, engine):
        errors = engine._validate_ops([{"op": "remember"}])
        
        assert len(errors) == 1
        assert "requires 'content'" in errors[0].message
    
    def test_validates_supersede_fields(self, engine):
        errors = engine._validate_ops([{"op": "supersede", "old": "x"}])
        
        assert len(errors) == 1
        assert "requires 'old' and 'new'" in errors[0].message
    
    def test_validates_resolve_fields(self, engine):
        errors = engine._validate_ops([{"op": "resolve", "id": "x"}])
        
        assert len(errors) == 1
        assert "requires 'id' and 'winner'" in errors[0].message
    
    def test_validates_dangling_ref(self, engine):
        errors = engine._validate_ops([
            {"op": "supersede", "old": "fact:x", "new": "$undeclared"},
        ])
        
        assert len(errors) == 1
        assert "Reference used before declaration" in errors[0].message
    
    def test_validates_duplicate_ref(self, engine):
        errors = engine._validate_ops([
            {"op": "remember", "as": "f1", "content": "test1"},
            {"op": "remember", "as": "f1", "content": "test2"},
        ])
        
        assert len(errors) == 1
        assert "Duplicate ref" in errors[0].message
    
    def test_valid_changeset_no_errors(self, engine):
        errors = engine._validate_ops([
            {"op": "remember", "as": "f1", "content": "test"},
            {"op": "supersede", "old": "fact:x", "new": "$f1"},
        ])
        
        assert len(errors) == 0


class TestApplyEngineExecution:
    """Tests for apply engine execution."""
    
    @pytest.fixture
    def engine(self, memory_store, mock_embedding):
        return ApplyEngine(memory_store, mock_embedding)
    
    @pytest.mark.asyncio
    async def test_topic_creation(self, engine, memory_store):
        result = await engine.apply([
            {"op": "topic", "name": "Architecture Decisions"},
        ])
        
        assert result.success
        
        topic = memory_store.get_topic("architecture-decisions")
        assert topic is not None
        assert topic.name == "Architecture Decisions"
    
    @pytest.mark.asyncio
    async def test_processed_marks_episodes(self, engine, memory_store):
        ep1 = Episode(content="Episode 1")
        ep2 = Episode(content="Episode 2")
        memory_store.add_episode(ep1)
        memory_store.add_episode(ep2)
        
        result = await engine.apply([
            {"op": "processed", "ids": [ep1.id, ep2.id]},
        ])
        
        assert result.success
        assert memory_store.get_episode(ep1.id).consolidated
        assert memory_store.get_episode(ep2.id).consolidated
    
    @pytest.mark.asyncio
    async def test_dry_run_validates_without_executing(self, engine, memory_store):
        result = await engine.apply(
            [{"op": "remember", "content": "Test"}],
            dry_run=True,
        )
        
        assert result.success
        assert result.ops_executed == 1


class TestApplyEngineConflictOperations:
    """Tests for conflict-related apply operations."""
    
    @pytest.fixture
    def engine(self, memory_store, mock_embedding):
        return ApplyEngine(memory_store, mock_embedding)
    
    def _setup_conflict(self, store):
        """Create two conflicting facts and an open conflict."""
        cluster = Concept(
            id="cluster1",
            title="Redis config",
            concept_type="fact_cluster",
        )
        store.add_concept(cluster)
        
        fact_a = Fact(
            id="fact_a",
            cluster_id=cluster.id,
            statement="TTL is 300s",
        )
        fact_b = Fact(
            id="fact_b",
            cluster_id=cluster.id,
            statement="TTL is 600s",
        )
        store.add_fact(fact_a)
        store.add_fact(fact_b)
        
        conflict = Conflict(
            id="conflict1",
            kind="fact",
            fact_a_id=fact_a.id,
            fact_b_id=fact_b.id,
            status="open",
        )
        store.add_conflict(conflict)
        
        return cluster, fact_a, fact_b, conflict
    
    @pytest.mark.asyncio
    async def test_resolve_conflict(self, engine, memory_store):
        _, fact_a, fact_b, conflict = self._setup_conflict(memory_store)
        
        result = await engine.apply([
            {
                "op": "resolve",
                "id": conflict.id,
                "winner": fact_b.id,
                "note": "600s is correct",
            },
        ])
        
        assert result.success
        
        # Conflict should be resolved
        updated_conflict = memory_store.get_conflict(conflict.id)
        assert updated_conflict.status == "resolved"
        
        # Loser should be superseded
        loser = memory_store.get_fact(fact_a.id)
        assert not loser.is_active
    
    @pytest.mark.asyncio
    async def test_dismiss_conflict(self, engine, memory_store):
        _, fact_a, fact_b, conflict = self._setup_conflict(memory_store)
        
        result = await engine.apply([
            {
                "op": "dismiss",
                "id": conflict.id,
                "note": "Different environments",
            },
        ])
        
        assert result.success
        
        updated_conflict = memory_store.get_conflict(conflict.id)
        assert updated_conflict.status == "dismissed"
        
        # Both facts should still be active
        assert memory_store.get_fact(fact_a.id).is_active
        assert memory_store.get_fact(fact_b.id).is_active
    
    @pytest.mark.asyncio
    async def test_resolve_already_resolved_fails(self, engine, memory_store):
        _, _, fact_b, conflict = self._setup_conflict(memory_store)
        
        # Resolve once
        await engine.apply([
            {"op": "resolve", "id": conflict.id, "winner": fact_b.id},
        ])
        
        # Try to resolve again
        result = await engine.apply([
            {"op": "resolve", "id": conflict.id, "winner": fact_b.id},
        ])
        
        assert not result.success
        assert "not open" in result.errors[0].message.lower() or "not open" in result.results[0].error.lower()


class TestApplyEngineCompactFormat:
    """Tests for applying compact format changesets - parsing and validation only."""
    
    @pytest.fixture
    def engine(self, memory_store, mock_embedding):
        return ApplyEngine(memory_store, mock_embedding)
    
    @pytest.mark.asyncio
    async def test_compact_format_parsing_dry_run(self, engine, memory_store):
        """Test that compact format is correctly parsed."""
        changeset = '''
remember t=observation "First observation"
remember t=decision "Made a decision"
'''
        result = await engine.apply(changeset, dry_run=True)
        
        assert result.success
        assert result.ops_executed == 2

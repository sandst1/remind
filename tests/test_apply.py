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


def current_revisions(store):
    from remind.operations import record_revision
    return {row["id"]: record_revision(store, row["id"])
            for name, rows in store.export_data()["records"].items()
            if name in {"episodes", "concepts", "facts", "conflicts", "entities", "evidence"}
            for row in rows}


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

    @pytest.mark.parametrize("content", [
        "x <= 450 here",
        "<=450 is the limit",
        "limit is <= 450 mm",
        "x >= 450 here",
        "x=5",
        "a < b",
        "a > b",
    ])
    def test_quoted_content_with_operators(self, content):
        op, err = parse_compact_line(f'remember t=fact e=concept:x "{content}"', 1)

        assert err is None
        assert op["content"] == content
        assert op["t"] == "fact"
        assert op["e"] == "concept:x"

    def test_quoted_field_value_with_equals(self):
        op, err = parse_compact_line('remember t=fact by="a=b" "x <= 450"', 1)

        assert err is None
        assert op["by"] == "a=b"
        assert op["content"] == "x <= 450"

    def test_quoted_content_with_escaped_quote_and_equals(self):
        op, err = parse_compact_line('remember t=fact "say \\"x=5\\" here"', 1)

        assert err is None
        assert op["content"] == 'say "x=5" here'
    
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
    async def test_label_and_unlabel_episode(self, engine, memory_store):
        episode = Episode(content="Label me")
        memory_store.add_episode(episode)

        labeled = await engine.apply([
            {"op": "label", "id": episode.id, "key": "topic", "value": "architecture"},
        ], expected_revisions=current_revisions(engine.store))
        assert labeled.success
        assert memory_store.get_labels("episode", episode.id) == {"topic": ["architecture"]}

        unlabeled = await engine.apply([
            {"op": "unlabel", "id": episode.id, "key": "topic", "value": "architecture"},
        ], expected_revisions=current_revisions(engine.store))
        assert unlabeled.success
        assert memory_store.get_labels("episode", episode.id) == {}
    
    @pytest.mark.asyncio
    async def test_label_via_fact_ref_labels_source_episode(self, engine, memory_store):
        """A fact-type remember exposes the fact id as its ref, so labelling
        that ref must fall through to the episode that asserted the fact."""
        result = await engine.apply([
            {"op": "remember", "as": "f1", "t": "fact", "content": "Cache TTL is 600s"},
            {"op": "label", "id": "$f1", "key": "release", "value": "0.13.1"},
        ], expected_revisions=current_revisions(engine.store))

        assert result.success, result.errors
        fact_id = result.results[0].id
        episode_id = memory_store.get_fact(fact_id).source_episode_id

        assert result.results[1].subject_type == "episode"
        assert result.results[1].id == episode_id
        assert memory_store.get_labels("episode", episode_id) == {"release": ["0.13.1"]}

        unlabeled = await engine.apply([
            {"op": "unlabel", "id": fact_id, "key": "release"},
        ], expected_revisions=current_revisions(engine.store))
        assert unlabeled.success, unlabeled.errors
        assert memory_store.get_labels("episode", episode_id) == {}

    @pytest.mark.asyncio
    async def test_failed_op_is_reported_with_its_own_index_and_type(self, engine, memory_store):
        """The failing op is appended to results before it raises, so the
        error must point at it rather than at the op that follows."""
        result = await engine.apply([
            {"op": "remember", "t": "observation", "content": "Fine"},
            {"op": "label", "id": "does-not-exist", "key": "k", "value": "v"},
            {"op": "remember", "t": "observation", "content": "Never runs"},
        ], expected_revisions=current_revisions(engine.store))

        assert not result.success
        assert len(result.errors) == 1
        assert result.errors[0].op_index == 1
        assert result.errors[0].op_type == "label"

    @pytest.mark.asyncio
    async def test_processed_marks_episodes(self, engine, memory_store):
        ep1 = Episode(content="Episode 1")
        ep2 = Episode(content="Episode 2")
        memory_store.add_episode(ep1)
        memory_store.add_episode(ep2)
        
        result = await engine.apply([
            {"op": "processed", "ids": [ep1.id, ep2.id]},
        ], expected_revisions=current_revisions(engine.store))
        
        assert result.success
        assert memory_store.get_episode(ep1.id).consolidated
        assert memory_store.get_episode(ep2.id).consolidated

    @pytest.mark.asyncio
    async def test_delete_and_restore_soft_deleted_episode(self, engine, memory_store):
        episode = Episode(content="Delete and restore")
        memory_store.add_episode(episode)

        deleted = await engine.apply([{"op": "delete", "id": episode.id}], expected_revisions=current_revisions(engine.store))
        assert deleted.success
        assert memory_store.get_episode(episode.id) is None

        restored = await engine.apply([{"op": "restore", "id": episode.id}], expected_revisions=current_revisions(engine.store))
        assert restored.success
        assert memory_store.get_episode(episode.id) is not None
    
    @pytest.mark.asyncio
    async def test_dry_run_validates_without_executing(self, engine, memory_store):
        result = await engine.apply(
            [{"op": "remember", "content": "Test"}],
            dry_run=True,
         expected_revisions=current_revisions(engine.store))
        
        assert result.success
        assert result.ops_executed == 1

    @pytest.mark.asyncio
    async def test_remember_emits_change_feed_event(self, engine, memory_store):
        result = await engine.apply([{"op": "remember", "content": "Test"}], expected_revisions=current_revisions(engine.store))
        assert result.success

        events = memory_store.get_events()
        assert len(events) == 1
        assert events[0]["kind"] == "remembered"
        assert events[0]["subject_type"] == "episode"
        assert events[0]["subject_id"] == result.results[0].id

    @pytest.mark.asyncio
    async def test_dry_run_does_not_emit_change_feed_event(self, engine, memory_store):
        await engine.apply([{"op": "remember", "content": "Test"}], dry_run=True, expected_revisions=current_revisions(engine.store))
        assert memory_store.get_events() == []

    @pytest.mark.asyncio
    async def test_label_emits_change_feed_event(self, engine, memory_store):
        episode = Episode(content="Label me")
        memory_store.add_episode(episode)

        await engine.apply([
            {"op": "label", "id": episode.id, "key": "topic", "value": "architecture"},
        ], expected_revisions=current_revisions(engine.store))

        events = memory_store.get_events(kind="labeled")
        assert len(events) == 1
        assert events[0]["subject_type"] == "episode"
        assert events[0]["subject_id"] == episode.id


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
        ], expected_revisions=current_revisions(engine.store))
        
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
        ], expected_revisions=current_revisions(engine.store))
        
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
        ], expected_revisions=current_revisions(engine.store))
        
        # Try to resolve again
        result = await engine.apply([
            {"op": "resolve", "id": conflict.id, "winner": fact_b.id},
        ], expected_revisions=current_revisions(engine.store))
        
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
        result = await engine.apply(changeset, dry_run=True, expected_revisions=current_revisions(engine.store))
        
        assert result.success
        assert result.ops_executed == 2

    @pytest.mark.asyncio
    async def test_quoted_operator_content_commits_batch(self, engine, memory_store):
        changeset = '''
remember t=observation "First observation"
remember t=observation "cabinet step from <=450mm to >=460mm"
'''
        result = await engine.apply(changeset, expected_revisions={})

        assert result.success
        assert result.ops_executed == 2
        assert [memory_store.get_episode(item.id).content for item in result.results] == [
            "First observation", "cabinet step from <=450mm to >=460mm",
        ]

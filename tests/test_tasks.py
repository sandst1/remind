"""Tests for task, spec, and plan episode types."""

import pytest
from datetime import datetime

from remind.interface import MemoryInterface
from remind.models import Episode, EpisodeType, TaskStatus


class TestTaskStatus:
    """Tests for TaskStatus enum."""

    def test_all_statuses_exist(self):
        expected = ["todo", "in_progress", "done", "blocked"]
        for name in expected:
            assert TaskStatus(name) is not None

    def test_invalid_status_raises(self):
        with pytest.raises(ValueError):
            TaskStatus("invalid")


class TestNewEpisodeTypes:
    """Tests for spec, plan, and task episode types."""

    def test_spec_type_exists(self):
        assert EpisodeType.SPEC.value == "spec"

    def test_plan_type_exists(self):
        assert EpisodeType.PLAN.value == "plan"

    def test_task_type_exists(self):
        assert EpisodeType.TASK.value == "task"

    def test_episode_roundtrip_with_new_types(self):
        for ep_type in [EpisodeType.SPEC, EpisodeType.PLAN, EpisodeType.TASK]:
            ep = Episode(content="test", episode_type=ep_type)
            d = ep.to_dict()
            restored = Episode.from_dict(d)
            assert restored.episode_type == ep_type

    def test_backwards_compat_unknown_type(self):
        """Unknown episode types should fall back to OBSERVATION."""
        d = {
            "id": "test",
            "content": "test",
            "episode_type": "unknown_future_type",
        }
        ep = Episode.from_dict(d)
        assert ep.episode_type == EpisodeType.OBSERVATION


class TestMemoryInterfaceTasks:
    """Tests for task operations on MemoryInterface."""

    @pytest.fixture
    def memory(self, mock_llm, mock_embedding, memory_store):
        return MemoryInterface(
            llm=mock_llm,
            embedding=mock_embedding,
            store=memory_store,
            auto_consolidate=False,
        )

    @pytest.mark.asyncio
    async def test_remember_spec(self, memory):
        ep_id = await memory.remember(
            "POST /auth/login must return JWT",
            episode_type=EpisodeType.SPEC,
            entities=["module:auth"],
        )
        episode = memory.store.get_episode(ep_id)
        assert episode.episode_type == EpisodeType.SPEC

    @pytest.mark.asyncio
    async def test_remember_plan(self, memory):
        ep_id = await memory.remember(
            "Auth plan: 1) bcrypt 2) login route 3) JWT",
            episode_type=EpisodeType.PLAN,
            entities=["module:auth"],
        )
        episode = memory.store.get_episode(ep_id)
        assert episode.episode_type == EpisodeType.PLAN

    @pytest.mark.asyncio
    async def test_remember_task(self, memory):
        ep_id = await memory.remember(
            "Implement bcrypt hashing",
            episode_type=EpisodeType.TASK,
            metadata={"status": "todo", "priority": "p0"},
            entities=["module:auth"],
        )
        episode = memory.store.get_episode(ep_id)
        assert episode.episode_type == EpisodeType.TASK
        assert episode.metadata["status"] == "todo"
        assert episode.metadata["priority"] == "p0"

    # =========================================================================
    # get_tasks() tests
    # =========================================================================

    def test_get_tasks_empty(self, memory):
        tasks = memory.get_tasks()
        assert tasks == []

    @pytest.mark.asyncio
    async def test_get_tasks_returns_only_tasks(self, memory):
        await memory.remember("Observation", episode_type=EpisodeType.OBSERVATION)
        await memory.remember("Decision", episode_type=EpisodeType.DECISION)
        await memory.remember(
            "A task",
            episode_type=EpisodeType.TASK,
            metadata={"status": "todo"},
        )
        tasks = memory.get_tasks()
        assert len(tasks) == 1
        assert tasks[0].episode_type == EpisodeType.TASK

    @pytest.mark.asyncio
    async def test_get_tasks_filter_by_status(self, memory):
        await memory.remember("Todo task", episode_type=EpisodeType.TASK,
                        metadata={"status": "todo"})
        await memory.remember("Done task", episode_type=EpisodeType.TASK,
                        metadata={"status": "done"})
        await memory.remember("In progress", episode_type=EpisodeType.TASK,
                        metadata={"status": "in_progress"})

        todo = memory.get_tasks(status="todo")
        assert len(todo) == 1
        assert todo[0].metadata["status"] == "todo"

        done = memory.get_tasks(status="done")
        assert len(done) == 1

    @pytest.mark.asyncio
    async def test_get_tasks_filter_by_entity(self, memory):
        await memory.remember("Auth task", episode_type=EpisodeType.TASK,
                        metadata={"status": "todo"}, entities=["module:auth"])
        await memory.remember("Billing task", episode_type=EpisodeType.TASK,
                        metadata={"status": "todo"}, entities=["module:billing"])

        auth_tasks = memory.get_tasks(entity_id="module:auth")
        assert len(auth_tasks) == 1
        assert "module:auth" in auth_tasks[0].entity_ids

    @pytest.mark.asyncio
    async def test_get_tasks_filter_by_plan(self, memory):
        plan_id = await memory.remember("The plan", episode_type=EpisodeType.PLAN)
        await memory.remember("Task for plan", episode_type=EpisodeType.TASK,
                        metadata={"status": "todo", "plan_id": plan_id})
        await memory.remember("Unrelated task", episode_type=EpisodeType.TASK,
                        metadata={"status": "todo"})

        plan_tasks = memory.get_tasks(plan_id=plan_id)
        assert len(plan_tasks) == 1
        assert plan_tasks[0].metadata["plan_id"] == plan_id

    @pytest.mark.asyncio
    async def test_get_tasks_respects_limit(self, memory):
        for i in range(10):
            await memory.remember(f"Task {i}", episode_type=EpisodeType.TASK,
                            metadata={"status": "todo"})

        tasks = memory.get_tasks(limit=3)
        assert len(tasks) == 3

    # =========================================================================
    # update_task_status() tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_update_task_status_todo_to_in_progress(self, memory):
        ep_id = await memory.remember("Task", episode_type=EpisodeType.TASK,
                                metadata={"status": "todo"})

        updated = memory.update_task_status(ep_id, "in_progress")

        assert updated is not None
        assert updated.metadata["status"] == "in_progress"
        assert "started_at" in updated.metadata

    @pytest.mark.asyncio
    async def test_update_task_status_to_done(self, memory):
        ep_id = await memory.remember("Task", episode_type=EpisodeType.TASK,
                                metadata={"status": "in_progress"})

        updated = memory.update_task_status(ep_id, "done")

        assert updated.metadata["status"] == "done"
        assert "completed_at" in updated.metadata

    @pytest.mark.asyncio
    async def test_update_task_status_to_blocked_with_reason(self, memory):
        ep_id = await memory.remember("Task", episode_type=EpisodeType.TASK,
                                metadata={"status": "todo"})

        updated = memory.update_task_status(ep_id, "blocked",
                                            reason="waiting on API key")

        assert updated.metadata["status"] == "blocked"
        assert updated.metadata["blocked_reason"] == "waiting on API key"

    @pytest.mark.asyncio
    async def test_update_task_status_unblock_clears_reason(self, memory):
        ep_id = await memory.remember("Task", episode_type=EpisodeType.TASK,
                                metadata={"status": "blocked",
                                          "blocked_reason": "some reason"})

        updated = memory.update_task_status(ep_id, "todo")

        assert updated.metadata["status"] == "todo"
        assert "blocked_reason" not in updated.metadata

    @pytest.mark.asyncio
    async def test_update_task_status_persists(self, memory):
        """Verify status change is persisted to store."""
        ep_id = await memory.remember("Task", episode_type=EpisodeType.TASK,
                                metadata={"status": "todo"})

        memory.update_task_status(ep_id, "in_progress")

        # Re-fetch from store
        episode = memory.store.get_episode(ep_id)
        assert episode.metadata["status"] == "in_progress"

    def test_update_task_status_nonexistent_returns_none(self, memory):
        result = memory.update_task_status("nonexistent", "done")
        assert result is None

    @pytest.mark.asyncio
    async def test_update_task_status_non_task_returns_none(self, memory):
        ep_id = await memory.remember("Not a task", episode_type=EpisodeType.OBSERVATION)
        result = memory.update_task_status(ep_id, "done")
        assert result is None

    @pytest.mark.asyncio
    async def test_update_task_status_invalid_status_returns_none(self, memory):
        ep_id = await memory.remember("Task", episode_type=EpisodeType.TASK,
                                metadata={"status": "todo"})
        result = memory.update_task_status(ep_id, "invalid_status")
        assert result is None

    @pytest.mark.asyncio
    async def test_update_task_status_done_to_todo_reopens(self, memory):
        ep_id = await memory.remember("Task", episode_type=EpisodeType.TASK,
                                metadata={"status": "done"})

        updated = memory.update_task_status(ep_id, "todo")

        assert updated.metadata["status"] == "todo"

    # =========================================================================
    # get_episodes_by_type() for new types
    # =========================================================================

    @pytest.mark.asyncio
    async def test_get_episodes_by_type_spec(self, memory):
        await memory.remember("Spec 1", episode_type=EpisodeType.SPEC)
        await memory.remember("Spec 2", episode_type=EpisodeType.SPEC)
        await memory.remember("Not a spec", episode_type=EpisodeType.OBSERVATION)

        specs = memory.get_episodes_by_type(EpisodeType.SPEC)
        assert len(specs) == 2

    @pytest.mark.asyncio
    async def test_get_episodes_by_type_plan(self, memory):
        await memory.remember("Plan 1", episode_type=EpisodeType.PLAN)
        await memory.remember("Not a plan", episode_type=EpisodeType.DECISION)

        plans = memory.get_episodes_by_type(EpisodeType.PLAN)
        assert len(plans) == 1

    @pytest.mark.asyncio
    async def test_get_episodes_by_type_task(self, memory):
        await memory.remember("Task 1", episode_type=EpisodeType.TASK,
                        metadata={"status": "todo"})
        await memory.remember("Task 2", episode_type=EpisodeType.TASK,
                        metadata={"status": "done"})

        tasks = memory.get_episodes_by_type(EpisodeType.TASK)
        assert len(tasks) == 2


class TestConsolidationTaskFilter:
    """Tests for task filtering during consolidation."""

    @pytest.fixture
    def memory(self, mock_llm, mock_embedding, memory_store):
        return MemoryInterface(
            llm=mock_llm,
            embedding=mock_embedding,
            store=memory_store,
            auto_consolidate=False,
        )

    @pytest.mark.asyncio
    async def test_active_tasks_excluded_from_consolidation(
        self, memory, mock_llm, mock_embedding
    ):
        """Active tasks (todo/in_progress/blocked) should not be consolidated."""
        # Add a regular episode (with entities so extraction is skipped)
        await memory.remember("Regular observation", entities=["subject:test"])

        # Add active tasks with entities so extraction doesn't reclassify them
        await memory.remember("Todo task", episode_type=EpisodeType.TASK,
                        metadata={"status": "todo"}, entities=["subject:tasks"])
        await memory.remember("In progress task", episode_type=EpisodeType.TASK,
                        metadata={"status": "in_progress"}, entities=["subject:tasks"])
        await memory.remember("Blocked task", episode_type=EpisodeType.TASK,
                        metadata={"status": "blocked"}, entities=["subject:tasks"])

        mock_llm.set_complete_json_response({
            "analysis": "Test",
            "updates": [],
            "new_concepts": [],
            "new_relations": [],
            "contradictions": [],
        })

        result = await memory.consolidate(force=True)

        # Only the regular observation should be processed
        assert result.episodes_processed == 1

    @pytest.mark.asyncio
    async def test_completed_tasks_included_in_consolidation(
        self, memory, mock_llm, mock_embedding
    ):
        """Completed tasks should be consolidated normally."""
        await memory.remember("Done task", episode_type=EpisodeType.TASK,
                        metadata={"status": "done"}, entities=["subject:tasks"])
        await memory.remember("Regular observation", entities=["subject:test"])

        mock_llm.set_complete_json_response({
            "analysis": "Test",
            "updates": [],
            "new_concepts": [],
            "new_relations": [],
            "contradictions": [],
        })

        result = await memory.consolidate(force=True)

        # Both the done task and observation should be processed
        assert result.episodes_processed == 2

    @pytest.mark.asyncio
    async def test_specs_and_plans_consolidate_normally(
        self, memory, mock_llm, mock_embedding
    ):
        """Specs and plans should consolidate normally (unlike active tasks)."""
        await memory.remember("A spec requirement", episode_type=EpisodeType.SPEC,
                        entities=["module:auth"])
        await memory.remember("A plan", episode_type=EpisodeType.PLAN,
                        entities=["module:auth"])
        await memory.remember("An observation", entities=["subject:test"])

        mock_llm.set_complete_json_response({
            "analysis": "Test",
            "updates": [],
            "new_concepts": [],
            "new_relations": [],
            "contradictions": [],
        })

        result = await memory.consolidate(force=True)

        assert result.episodes_processed == 3

    @pytest.mark.asyncio
    async def test_no_consolidation_when_only_active_tasks(
        self, memory, mock_llm, mock_embedding
    ):
        """If only active tasks exist, nothing should consolidate."""
        await memory.remember("Task 1", episode_type=EpisodeType.TASK,
                        metadata={"status": "todo"}, entities=["subject:tasks"])
        await memory.remember("Task 2", episode_type=EpisodeType.TASK,
                        metadata={"status": "in_progress"}, entities=["subject:tasks"])

        mock_llm.set_complete_json_response({
            "analysis": "Test",
            "updates": [],
            "new_concepts": [],
            "new_relations": [],
            "contradictions": [],
        })

        result = await memory.consolidate(force=True)

        assert result.episodes_processed == 0


class TestTaskMetadataIntegrity:
    """Tests for task metadata handling edge cases."""

    @pytest.fixture
    def memory(self, mock_llm, mock_embedding, memory_store):
        return MemoryInterface(
            llm=mock_llm,
            embedding=mock_embedding,
            store=memory_store,
            auto_consolidate=False,
        )

    @pytest.mark.asyncio
    async def test_task_with_full_metadata(self, memory):
        """Test task with all metadata fields."""
        ep_id = await memory.remember(
            "Complex task",
            episode_type=EpisodeType.TASK,
            metadata={
                "status": "todo",
                "priority": "p0",
                "plan_id": "plan-123",
                "spec_ids": ["spec-1", "spec-2"],
                "depends_on": ["task-a", "task-b"],
            },
            entities=["module:auth", "file:src/auth.ts"],
        )

        episode = memory.store.get_episode(ep_id)
        meta = episode.metadata
        assert meta["status"] == "todo"
        assert meta["priority"] == "p0"
        assert meta["plan_id"] == "plan-123"
        assert meta["spec_ids"] == ["spec-1", "spec-2"]
        assert meta["depends_on"] == ["task-a", "task-b"]

    @pytest.mark.asyncio
    async def test_task_without_explicit_status_defaults(self, memory):
        """Task created without status metadata gets default from get_tasks filter."""
        ep_id = await memory.remember(
            "Task with no status",
            episode_type=EpisodeType.TASK,
            metadata={},
        )

        # get_tasks with status=None should include it
        tasks = memory.get_tasks()
        assert len(tasks) == 1

        # get_tasks with status="todo" should include it (default)
        tasks = memory.get_tasks(status="todo")
        # It has no "status" key, so it won't match the filter
        assert len(tasks) == 0

    @pytest.mark.asyncio
    async def test_status_transition_preserves_other_metadata(self, memory):
        """Status transitions should preserve priority, plan_id, etc."""
        ep_id = await memory.remember(
            "Task",
            episode_type=EpisodeType.TASK,
            metadata={
                "status": "todo",
                "priority": "p0",
                "plan_id": "plan-123",
            },
        )

        updated = memory.update_task_status(ep_id, "in_progress")

        assert updated.metadata["priority"] == "p0"
        assert updated.metadata["plan_id"] == "plan-123"
        assert updated.metadata["status"] == "in_progress"
        assert "started_at" in updated.metadata

    @pytest.mark.asyncio
    async def test_multiple_status_transitions(self, memory):
        """Test full lifecycle: todo -> in_progress -> blocked -> todo -> in_progress -> done."""
        ep_id = await memory.remember(
            "Lifecycle task",
            episode_type=EpisodeType.TASK,
            metadata={"status": "todo"},
        )

        memory.update_task_status(ep_id, "in_progress")
        ep = memory.store.get_episode(ep_id)
        assert ep.metadata["status"] == "in_progress"
        assert "started_at" in ep.metadata

        memory.update_task_status(ep_id, "blocked", reason="API down")
        ep = memory.store.get_episode(ep_id)
        assert ep.metadata["status"] == "blocked"
        assert ep.metadata["blocked_reason"] == "API down"

        memory.update_task_status(ep_id, "todo")
        ep = memory.store.get_episode(ep_id)
        assert ep.metadata["status"] == "todo"
        assert "blocked_reason" not in ep.metadata

        memory.update_task_status(ep_id, "in_progress")
        memory.update_task_status(ep_id, "done")
        ep = memory.store.get_episode(ep_id)
        assert ep.metadata["status"] == "done"
        assert "completed_at" in ep.metadata

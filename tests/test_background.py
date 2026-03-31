"""Tests for background processing: ingest queue, worker loop, and locking."""

import json
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

from remind.background import (
    _db_hash,
    enqueue_ingest_chunk,
    get_ingest_queue_dir,
    get_ingest_lock_path,
    is_ingest_running,
    spawn_ingest_worker,
    get_consolidation_lock_path,
    is_consolidation_running,
    INGEST_WORKER_GRACE_SECONDS,
)
from remind.background_worker import _next_queued_chunk, run_ingest_worker


class TestDbHash:
    def test_deterministic(self):
        assert _db_hash("/foo/bar.db") == _db_hash("/foo/bar.db")

    def test_different_paths_differ(self):
        assert _db_hash("/foo/a.db") != _db_hash("/foo/b.db")

    def test_12_char_hex(self):
        h = _db_hash("/any/path.db")
        assert len(h) == 12
        int(h, 16)  # should not raise


class TestIngestQueueDir:
    def test_returns_path_under_remind_dir(self):
        path = get_ingest_queue_dir("/tmp/test.db")
        assert "ingest-queue" in str(path)
        assert path.name == _db_hash("/tmp/test.db")


class TestEnqueueIngestChunk:
    def test_creates_json_file(self, tmp_path):
        with patch("remind.background.REMIND_DIR", tmp_path):
            path = enqueue_ingest_chunk("/tmp/test.db", "hello world", "test")
            assert path.exists()
            data = json.loads(path.read_text())
            assert data["chunk"] == "hello world"
            assert data["source"] == "test"

    def test_fifo_ordering_by_filename(self, tmp_path):
        with patch("remind.background.REMIND_DIR", tmp_path):
            p1 = enqueue_ingest_chunk("/tmp/test.db", "first", "a")
            time.sleep(0.01)
            p2 = enqueue_ingest_chunk("/tmp/test.db", "second", "b")
            assert p1.name < p2.name

    def test_default_source(self, tmp_path):
        with patch("remind.background.REMIND_DIR", tmp_path):
            path = enqueue_ingest_chunk("/tmp/test.db", "data")
            data = json.loads(path.read_text())
            assert data["source"] == "conversation"

    def test_instructions_in_payload(self, tmp_path):
        with patch("remind.background.REMIND_DIR", tmp_path):
            path = enqueue_ingest_chunk(
                "/tmp/test.db", "data", instructions="focus on decisions",
            )
            data = json.loads(path.read_text())
            assert data["instructions"] == "focus on decisions"

    def test_instructions_absent_when_none(self, tmp_path):
        with patch("remind.background.REMIND_DIR", tmp_path):
            path = enqueue_ingest_chunk("/tmp/test.db", "data")
            data = json.loads(path.read_text())
            assert "instructions" not in data


class TestIngestLocking:
    def test_is_ingest_running_false_when_unlocked(self, tmp_path):
        with patch("remind.background.REMIND_DIR", tmp_path):
            assert not is_ingest_running("/tmp/test.db")

    def test_is_ingest_running_true_when_locked(self, tmp_path):
        from filelock import FileLock

        with patch("remind.background.REMIND_DIR", tmp_path):
            lock_path = get_ingest_lock_path("/tmp/test.db")
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            lock = FileLock(str(lock_path))
            lock.acquire()
            try:
                assert is_ingest_running("/tmp/test.db")
            finally:
                lock.release()

    def test_spawn_ingest_worker_returns_false_when_locked(self, tmp_path):
        from filelock import FileLock

        with patch("remind.background.REMIND_DIR", tmp_path):
            lock_path = get_ingest_lock_path("/tmp/test.db")
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            lock = FileLock(str(lock_path))
            lock.acquire()
            try:
                result = spawn_ingest_worker("/tmp/test.db", "anthropic", "openai")
                assert result is False
            finally:
                lock.release()


class TestNextQueuedChunk:
    def test_empty_dir(self, tmp_path):
        assert _next_queued_chunk(tmp_path) is None

    def test_nonexistent_dir(self, tmp_path):
        assert _next_queued_chunk(tmp_path / "nope") is None

    def test_picks_oldest_file(self, tmp_path):
        f1 = tmp_path / "0001-aaaa.json"
        f2 = tmp_path / "0002-bbbb.json"
        f1.write_text(json.dumps({"chunk": "first", "source": "a"}))
        f2.write_text(json.dumps({"chunk": "second", "source": "b"}))

        result = _next_queued_chunk(tmp_path)
        assert result is not None
        assert result.chunk == "first"
        assert result.source == "a"
        assert result.topic is None
        assert result.instructions is None
        # File should be deleted after reading
        assert not f1.exists()
        assert f2.exists()

    def test_malformed_json_cleaned_up(self, tmp_path):
        bad = tmp_path / "0001-bad.json"
        good = tmp_path / "0002-good.json"
        bad.write_text("not json")
        good.write_text(json.dumps({"chunk": "ok", "source": "x"}))

        # First call hits the bad file, deletes it, returns None
        result = _next_queued_chunk(tmp_path)
        assert result is None
        assert not bad.exists()

        # Second call picks up the good file
        result = _next_queued_chunk(tmp_path)
        assert result is not None
        assert result.chunk == "ok"

    def test_default_source(self, tmp_path):
        f = tmp_path / "0001-x.json"
        f.write_text(json.dumps({"chunk": "data"}))
        result = _next_queued_chunk(tmp_path)
        assert result.source == "conversation"

    def test_topic_preserved(self, tmp_path):
        f = tmp_path / "0001-x.json"
        f.write_text(json.dumps({"chunk": "data", "source": "s", "topic": "architecture"}))
        result = _next_queued_chunk(tmp_path)
        assert result.topic == "architecture"

    def test_instructions_preserved(self, tmp_path):
        f = tmp_path / "0001-x.json"
        f.write_text(json.dumps({
            "chunk": "data", "source": "s",
            "instructions": "focus on decisions",
        }))
        result = _next_queued_chunk(tmp_path)
        assert result.instructions == "focus on decisions"

    def test_instructions_none_when_absent(self, tmp_path):
        f = tmp_path / "0001-x.json"
        f.write_text(json.dumps({"chunk": "data", "source": "s"}))
        result = _next_queued_chunk(tmp_path)
        assert result.instructions is None


class TestRunIngestWorker:
    """Test the worker loop logic using a real queue dir but mocked memory."""

    def _make_args(self, db_path="/tmp/test.db"):
        args = MagicMock()
        args.db = db_path
        args.llm = "anthropic"
        args.embedding = "openai"
        return args

    def test_processes_all_queued_chunks(self, tmp_path):
        import asyncio

        with patch("remind.background_worker.get_ingest_lock_path") as mock_lock_path, \
             patch("remind.background_worker.get_ingest_queue_dir") as mock_queue_dir, \
             patch("remind.background_worker.INGEST_WORKER_GRACE_SECONDS", 0), \
             patch("remind.interface.create_memory") as mock_create:

            lock_file = tmp_path / "test.lock"
            mock_lock_path.return_value = lock_file

            queue_dir = tmp_path / "queue"
            queue_dir.mkdir()
            mock_queue_dir.return_value = queue_dir

            (queue_dir / "0001-aa.json").write_text(
                json.dumps({"chunk": "chunk one", "source": "s1"})
            )
            (queue_dir / "0002-bb.json").write_text(
                json.dumps({"chunk": "chunk two", "source": "s2"})
            )

            async def fake_process(chunk, source, topic=None, instructions=None):
                return [f"ep-{source}"]

            mock_memory = MagicMock()
            mock_memory._process_ingest_chunk = fake_process
            mock_memory.aclose = AsyncMock()
            mock_create.return_value = mock_memory

            logger = MagicMock()
            run_ingest_worker(self._make_args(), logger)

            # Both chunks should have been processed (check log output)
            info_messages = [str(c) for c in logger.info.call_args_list]
            assert any("chunk one" in m or "9 chars" in m for m in info_messages)
            assert any("2 chunks" in m for m in info_messages)

    def test_skips_when_locked(self, tmp_path):
        from filelock import FileLock

        with patch("remind.background_worker.get_ingest_lock_path") as mock_lock_path, \
             patch("remind.background_worker.get_ingest_queue_dir") as mock_queue_dir:

            lock_file = tmp_path / "test.lock"
            mock_lock_path.return_value = lock_file

            queue_dir = tmp_path / "queue"
            queue_dir.mkdir()
            mock_queue_dir.return_value = queue_dir

            (queue_dir / "0001-aa.json").write_text(
                json.dumps({"chunk": "data", "source": "s"})
            )

            lock = FileLock(str(lock_file))
            lock.acquire()

            logger = MagicMock()
            try:
                run_ingest_worker(self._make_args(), logger)
            finally:
                lock.release()

            logger.info.assert_any_call("Ingest worker already running for /tmp/test.db")
            assert (queue_dir / "0001-aa.json").exists()

    def test_empty_queue_exits_immediately(self, tmp_path):
        with patch("remind.background_worker.get_ingest_lock_path") as mock_lock_path, \
             patch("remind.background_worker.get_ingest_queue_dir") as mock_queue_dir, \
             patch("remind.background_worker.INGEST_WORKER_GRACE_SECONDS", 0), \
             patch("remind.interface.create_memory") as mock_create:

            lock_file = tmp_path / "test.lock"
            mock_lock_path.return_value = lock_file

            queue_dir = tmp_path / "queue"
            queue_dir.mkdir()
            mock_queue_dir.return_value = queue_dir

            mock_memory = MagicMock()
            mock_memory.aclose = AsyncMock()
            mock_create.return_value = mock_memory

            logger = MagicMock()
            run_ingest_worker(self._make_args(), logger)

            logger.info.assert_any_call(
                "Ingest worker finished for /tmp/test.db: 0 chunks, 0 episodes"
            )

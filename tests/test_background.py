"""Tests for background processing: recall worker and locking."""

import json
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

from remind.background import (
    _db_hash,
    build_recall_worker_key,
    get_recall_socket_path,
    get_recall_lock_path,
    is_recall_running,
    spawn_recall_worker,
    DEFAULT_RECALL_WORKER_IDLE_SECONDS,
)


class TestDbHash:
    def test_deterministic(self):
        assert _db_hash("/foo/bar.db") == _db_hash("/foo/bar.db")

    def test_different_paths_differ(self):
        assert _db_hash("/foo/a.db") != _db_hash("/foo/b.db")

    def test_12_char_hex(self):
        h = _db_hash("/any/path.db")
        assert len(h) == 12
        int(h, 16)  # should not raise


class TestRecallWorkerIdentity:
    def test_build_recall_worker_key_deterministic(self):
        key1 = build_recall_worker_key(
            "sqlite:////tmp/test.db",
            "openai",
            '{"reranking_enabled":true}',
        )
        key2 = build_recall_worker_key(
            "sqlite:////tmp/test.db",
            "openai",
            '{"reranking_enabled":true}',
        )
        assert key1 == key2
        assert len(key1) == 16

    def test_socket_and_lock_paths_include_worker_key(self, tmp_path):
        sock = get_recall_socket_path("/tmp/test.db", "abcd1234", remind_dir=tmp_path)
        lock = get_recall_lock_path("/tmp/test.db", "abcd1234", remind_dir=tmp_path)
        assert sock.name.endswith("abcd1234.sock")
        assert "sockets" in str(sock.parent)
        assert lock.name.endswith("abcd1234.lock")


class TestRecallLocking:
    def test_is_recall_running_false_when_unlocked(self, tmp_path):
        with patch("remind.background.REMIND_DIR", tmp_path):
            assert not is_recall_running("/tmp/test.db", "key1")

    def test_spawn_recall_worker_returns_false_when_locked(self, tmp_path):
        from filelock import FileLock

        with patch("remind.background.REMIND_DIR", tmp_path):
            lock_path = get_recall_lock_path("/tmp/test.db", "key1")
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            lock = FileLock(str(lock_path))
            lock.acquire()
            try:
                result = spawn_recall_worker(
                    "/tmp/test.db",
                    "openai",
                    worker_key="key1",
                    idle_seconds=DEFAULT_RECALL_WORKER_IDLE_SECONDS,
                )
                assert result is False
            finally:
                lock.release()

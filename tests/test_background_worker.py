"""Worker startup and IPC request contracts without a model download or sockets."""

from argparse import Namespace
import json
import logging
from types import SimpleNamespace

import pytest

from remind import background_worker as worker
from remind.models import Concept, Episode
from remind.retrieval import ActivatedConcept


def test_worker_logging_accepts_file_store_uri(tmp_path, monkeypatch):
    directory = tmp_path / "project with spaces" / ".remind"
    expected = directory / "runtime/logs"
    observed = []
    monkeypatch.setattr(worker.logging, "basicConfig", lambda **kwargs: observed.append(kwargs))
    monkeypatch.setattr(worker, "load_config", lambda **kwargs: SimpleNamespace(logging_enabled=True))
    monkeypatch.setattr(worker, "setup_file_logging", lambda *args, **kwargs: observed.append(kwargs))
    assert worker.setup_logging((directory / "memory").as_uri())
    assert observed[0]["filename"] == str(expected / "recall-worker.log")
    assert observed[1]["project_dir"] == directory.parent
    assert worker._log_dir_for_db("unused", directory) == expected
    assert worker._log_dir_for_db(f"sqlite:///{directory}/old.db") == directory / "logs"
    assert worker._log_dir_for_db(str(directory / "old.db")) == directory / "logs"


def test_worker_serializes_both_raw_result_types():
    episode = Episode(content="Entity raw")
    concept = ActivatedConcept(Concept(summary="Semantic raw"), .8, "embedding", 0)
    assert worker._serialize_recall_raw_result([episode], "person:alice")["result"] == [episode.to_dict()]
    payload = worker._serialize_recall_raw_result([concept], None)
    assert payload["result_type"] == "semantic_raw"
    assert payload["result"][0]["concept"] == concept.concept.to_dict()


@pytest.mark.parametrize("requests,expected", [
    ([b""], ["empty request"]),
    ([b"{broken\n"], ["invalid request"]),
    ([b'{"action":"unknown"}\n'], ["unknown action"]),
    ([b'{"action":"ping"}\n'], ["pong"]),
    ([b'{"action":"recall","query":"retry"}\n'], ["result"]),
    ([b'{"action":"recall","query":"retry","raw":true}\n'], ["semantic_raw"]),
    ([b'{"action":"recall","entity":"person:alice","raw":true}\n'], ["entity_raw"]),
    ([b'{"action":"recall","k":"invalid"}\n'], ["invalid literal"]),
])
def test_worker_ipc_and_idle_cleanup(tmp_path, monkeypatch, requests, expected):
    results, calls, closed = [], [], []
    class Memory:
        async def recall(self, **kwargs):
            calls.append(kwargs)
            if kwargs["raw"]:
                if kwargs["entity"]:
                    return [Episode(content="Entity result")]
                return [ActivatedConcept(Concept(summary="Result"), .9, "embedding")]
            return "Useful memory"
        async def aclose(self):
            closed.append("memory")
    import remind.interface
    monkeypatch.setattr(remind.interface, "create_memory", lambda **kwargs: Memory())
    class Writer:
        def write(self, data):
            results.append(json.loads(data))
        async def drain(self):
            pass
        def close(self):
            pass
        async def wait_closed(self):
            pass
    class Reader:
        def __init__(self, line):
            self.line = line
        async def readline(self):
            return self.line
    class Server:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        def close(self):
            closed.append("server")
        async def wait_closed(self):
            pass
    async def start(handler, **kwargs):
        for request in requests:
            await handler(Reader(request), Writer())
        return Server()
    elapsed = [0]
    async def sleep(_):
        elapsed[0] += 10
    monkeypatch.setattr(worker.asyncio, "start_unix_server", start)
    monkeypatch.setattr(worker.asyncio, "sleep", sleep)
    monkeypatch.setattr(worker, "time", SimpleNamespace(monotonic=lambda: elapsed[0]))
    args = Namespace(db=(tmp_path / "memory").as_uri(), embedding="deterministic",
                     remind_dir=str(tmp_path), recall_socket=str(tmp_path / "worker.sock"),
                     recall_worker_key="test-worker", recall_idle_seconds=5)
    worker.run_recall_worker(args, logging.getLogger("worker-test"))
    assert closed == ["server", "memory"]
    assert all(value in json.dumps(results) for value in expected)
    if calls:
        assert calls[0]["query"] == "retry" or calls[0]["entity"] == "person:alice"


@pytest.mark.parametrize("missing", ["recall_socket", "recall_worker_key"])
def test_worker_missing_required_settings_is_reported(missing, caplog):
    args = Namespace(recall_socket="socket", recall_worker_key="key")
    setattr(args, missing, None)
    worker.run_recall_worker(args, logging.getLogger("worker-test"))
    assert "requires" in caplog.text

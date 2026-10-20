"""Real Git/process boundaries, without touching the developer's repository."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import subprocess
import sys

import pytest

from remind.file_store import FileMemoryStore
from remind.interface import MemoryInterface
from remind.models import Episode
from remind.operations import record_revision, RevisionConflict
from remind.providers.deterministic import DeterministicEmbedding


def git(root, *args, check=True):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=check)


@pytest.mark.asyncio
async def test_checkout_merge_clone_and_conflicting_edit(tmp_path):
    git(tmp_path, "init", "-b", "main")
    git(tmp_path, "config", "user.name", "Memory tests")
    git(tmp_path, "config", "user.email", "tests@example.invalid")
    store = FileMemoryStore(tmp_path / ".remind" / "memory")
    memory = MemoryInterface(DeterministicEmbedding(), store=store)
    seed = await memory.remember("Initial shared knowledge")
    git(tmp_path, "add", ".remind")
    git(tmp_path, "commit", "-m", "Initial memory")
    git(tmp_path, "checkout", "-b", "feature")
    feature = await memory.remember("Feature branch knowledge")
    git(tmp_path, "add", ".remind/memory")
    git(tmp_path, "commit", "-m", "Feature memory")
    git(tmp_path, "checkout", "main")
    assert store.get_episode(feature.episode_id) is None
    main = await memory.remember("Main branch knowledge")
    git(tmp_path, "add", ".remind/memory")
    git(tmp_path, "commit", "-m", "Main memory")
    git(tmp_path, "merge", "feature", "--no-edit")
    assert store.get_episode(feature.episode_id)
    assert store.get_episode(main.episode_id)
    clone = tmp_path / "clone"
    git(tmp_path, "clone", "--no-hardlinks", str(tmp_path), str(clone))
    cloned = FileMemoryStore(clone / ".remind" / "memory")
    assert len(cloned.get_all_episodes()) == 3
    cloned.engine.dispose()
    git(tmp_path, "checkout", "feature")
    memory.update_episode(seed.episode_id, content="Feature edit", expected_revision=record_revision(store, seed.episode_id))
    git(tmp_path, "add", ".remind/memory")
    git(tmp_path, "commit", "-m", "Edit on feature")
    git(tmp_path, "checkout", "main")
    memory.update_episode(seed.episode_id, content="Main edit", expected_revision=record_revision(store, seed.episode_id))
    git(tmp_path, "add", ".remind/memory")
    git(tmp_path, "commit", "-m", "Edit on main")
    assert git(tmp_path, "merge", "feature", "--no-edit", check=False).returncode != 0
    with pytest.raises(ValueError):
        store.get_episode(seed.episode_id)
    from remind.doctor import diagnose_directory
    assert not diagnose_directory(store.directory)["ok"]
    store.engine.dispose()


def environment():
    return dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))


def test_parallel_process_captures_and_stale_revision(tmp_path):
    directory = tmp_path / "memory"
    # Initialize once; all subsequent operations still execute in separate processes.
    FileMemoryStore(directory).engine.dispose()
    script = """
import asyncio,sys
from remind.file_store import FileMemoryStore
from remind.interface import MemoryInterface
from remind.providers.deterministic import DeterministicEmbedding
async def run():
    store=FileMemoryStore(sys.argv[1])
    await MemoryInterface(DeterministicEmbedding(),store=store).remember(sys.argv[2])
    store.engine.dispose()
asyncio.run(run())
"""
    def worker(index):
        subprocess.run([sys.executable, "-c", script, str(directory), f"Worker {index}"],
                       check=True, capture_output=True, env=environment(), timeout=30)
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(worker, range(3)))
    first, second = FileMemoryStore(directory), FileMemoryStore(directory)
    assert len(first.get_all_episodes()) == 3
    episode = first.get_all_episodes()[0]
    old = record_revision(second, episode.id)
    MemoryInterface(DeterministicEmbedding(), store=first).update_episode(episode.id, content="Winner", expected_revision=old)
    with pytest.raises(RevisionConflict):
        MemoryInterface(DeterministicEmbedding(), store=second).update_episode(episode.id, content="Loser", expected_revision=old)
    first.engine.dispose()
    second.engine.dispose()


def test_process_death_after_commit_decision_recovers_receipt(tmp_path):
    script = """
import asyncio,os,sys
from remind.file_store import FileMemoryStore
from remind.interface import MemoryInterface
from remind.providers.deterministic import DeterministicEmbedding
store=FileMemoryStore(sys.argv[1])
original=store._recover
def crash():
    if (store.runtime/'journal.json').exists(): os._exit(23)
    original()
store._recover=crash
asyncio.run(MemoryInterface(DeterministicEmbedding(),store=store).remember('Committed before crash',embed=False,idempotency_key='crash'))
"""
    directory = tmp_path / "memory"
    result = subprocess.run([sys.executable, "-c", script, str(directory)], env=environment(), capture_output=True, timeout=30)
    assert result.returncode == 23, result.stderr
    store = FileMemoryStore(directory)
    memory = MemoryInterface(DeterministicEmbedding(), store=store)
    response = asyncio.run(memory.remember("Committed before crash", embed=False, idempotency_key="crash"))
    assert len(store.get_all_episodes()) == 1
    assert store.get_episode(response.episode_id)
    assert len(store.get_events()) == 1
    store.engine.dispose()


def test_export_has_no_episode_limit(tmp_path):
    from remind.store import SQLAlchemyMemoryStore
    store = SQLAlchemyMemoryStore(f"sqlite:///{tmp_path / 'many.db'}")
    store.add_episodes_batch([Episode(content=f"Episode {i}") for i in range(10001)])
    assert len(store.export_data()["episodes"]) == 10001
    store.engine.dispose()

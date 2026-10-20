"""Benchmark file-backed memory in disposable 1k/10k stores; no network."""

import argparse
import asyncio
import json
from pathlib import Path
import shutil
import tempfile
import time

from sqlalchemy import event

from remind.file_store import FileMemoryStore
from remind.interface import MemoryInterface
from remind.models import Episode
from remind.providers.deterministic import DeterministicEmbedding


async def benchmark(count):
    with tempfile.TemporaryDirectory(prefix="remind-benchmark-") as temporary:
        directory = Path(temporary) / "memory"
        store = FileMemoryStore(directory)
        timings = {"records": count}
        started = time.perf_counter()
        store.add_episodes_batch([Episode(content=f"Benchmark record_{i}") for i in range(count)])
        timings["bulk_write_seconds"] = time.perf_counter() - started
        cache = store.cache
        store.engine.dispose()
        shutil.rmtree(cache)
        started = time.perf_counter()
        store = FileMemoryStore(directory)
        timings["cold_rebuild_seconds"] = time.perf_counter() - started
        writes = []
        @event.listens_for(store.engine, "before_execute")
        def track(conn, clause, multiparams, params, execution_options):
            if getattr(clause, "is_dml", False):
                writes.append(str(clause))
        memory = MemoryInterface(DeterministicEmbedding(), store=store, hybrid_keyword_weight=.3)
        started = time.perf_counter()
        result = await memory.recall(f"record_{count-1}")
        timings["warm_recall_seconds"] = time.perf_counter() - started
        assert f"record_{count-1}" in result.text
        assert not writes, "Warm read unexpectedly rebuilt or mutated its projection"
        started = time.perf_counter()
        page, total = store.page_records("episodes", offset=20, limit=20)
        timings["pagination_seconds"] = time.perf_counter() - started
        assert len(page) == 20 and total == count
        started = time.perf_counter()
        await memory.remember("A newly captured benchmark episode")
        timings["capture_seconds"] = time.perf_counter() - started
        started = time.perf_counter()
        assert len(store.export_data()["episodes"]) == count + 1
        timings["export_seconds"] = time.perf_counter() - started
        store.engine.dispose()
        return timings


async def run(output):
    results = [await benchmark(count) for count in (1000, 10000)]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps(results))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".remind/runtime/evals/performance.json"))
    asyncio.run(run(parser.parse_args().output))

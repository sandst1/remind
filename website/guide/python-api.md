# Python API

Use Remind as a library in your own Python applications.

## Version 0.14 result and edit contracts

`await memory.recall(...)` returns `RecallResult`; pass `result.text` to an agent and inspect `result.to_dict()` for structured output. Ordinary recall is read-only. `remember_batch` returns `BatchRememberResult.results`, with one full capture result per item.

Snapshots include record revisions. Pass `expected_revision` for individual edits, or `expected_revisions={id: revision}` to `ApplyEngine.apply`. Capture/apply accept stable idempotency keys for safe retries. Full UUIDs replace generated eight-character IDs; existing IDs are preserved. Use `create_memory(store_url="file:///absolute/path/to/memory")` for a generic local store, or an explicit SQL URL for database storage.

## Basic usage

```python
import asyncio
from remind import create_memory, EpisodeType

async def main():
    # Uses local embeddings by default — no API keys needed
    memory = create_memory()

    # Log experiences — fast, no external calls
    await memory.remember("User mentioned they prefer Python for backend work")
    await memory.remember("User is building a distributed system")
    await memory.remember("User values type safety")

    # Typed episodes
    await memory.remember("Chose PostgreSQL over MySQL for persistence", episode_type=EpisodeType.DECISION)
    await memory.remember("User prefers dark mode in the IDE", episode_type=EpisodeType.PREFERENCE)

    # Label-scoped episodes
    await memory.remember("Use event sourcing for audit trail", labels={"topic": "architecture"})

    # Fact episodes — clustered automatically, collisions detected
    result = await memory.remember(
        "Redis TTL is 300s for auth tokens",
        episode_type=EpisodeType.FACT,
        entities=["tool:redis"],
        asserted_by="alice",
    )
    if result.collisions:
        print(f"Collision detected with: {result.collisions}")

    # Retrieve relevant concepts
    context = await memory.recall("What programming preferences?")
    print(context.text)

    # Label-scoped retrieval
    context = await memory.recall("database design", labels={"topic": "architecture"})
    print(context.text)

    # Time-travel: facts valid at a past point in time
    context = await memory.recall("cache configuration", as_of="2024-06-01")

    # Budget controls: cap output size, drop weak matches, bound latency
    context = await memory.recall("auth", max_chars=2000, min_score=0.3, timeout_ms=500)

asyncio.run(main())
```

## Fact episodes and collisions

Facts are handled deterministically:

```python
# Store a fact
result = await memory.remember(
    "Redis TTL is 600s",
    episode_type=EpisodeType.FACT,
    entities=["tool:redis"],
    asserted_by="alice",
    source_ref="https://github.com/org/repo/pull/42",
)

# Check what happened
print(f"Fact ID: {result.fact_id}")
print(f"Cluster ID: {result.cluster_id}")
print(f"New cluster: {result.cluster_created}")
print(f"Collisions: {result.collisions}")
```

## Atomic batch capture

`remember_batch()` embeds and commits all items atomically. Its ordered `results` correspond to the input items:

```python
batch = await memory.remember_batch([
    {"content": "Retries are limited to 4", "episode_type": "fact"},
    {"content": "Use exponential backoff", "episode_type": "decision"},
])
for capture in batch.results:
    print(capture.episode_id, capture.fact_id)
```

When a fact collides with existing facts (same entities, different statements), the collision is reported but NOT auto-resolved. Inspect it before handling it via `apply()`:

```python
from remind.snapshot import SnapshotEngine

# Get collisions that need resolution
snapshot = await SnapshotEngine(memory.store, memory.embedding).snapshot(["conflicts"])
for conflict in snapshot["conflicts"]:
    print(f"Conflict: {conflict['description']}")
    print(f"Facts: {conflict['fact_ids']}")
```

## Batch operations with apply

Use `apply()` for transactional curation:

```python
from remind.apply import ApplyEngine

engine = ApplyEngine(memory.store, memory.embedding)

# Compact format
result = await engine.apply("""
remember as=f1 t=fact e=tool:redis "Cache TTL is 600s"
supersede old=fact:abc123 new=$f1
concept from=ep:11,ep:12 title="Redis config" "TTL-based caching"
processed ids=ep:11,ep:12
""")

# JSON format
result = await engine.apply([
    {"op": "remember", "as": "f1", "t": "fact", "content": "Cache TTL is 600s", "e": ["tool:redis"]},
    {"op": "supersede", "old": "fact:abc123", "new": "$f1"},
])

# Check results
for op_result in result.results:
    print(f"{op_result.op}: {op_result.status}")
```

## Batch reads with snapshot

Use `snapshot()` to read current memory state:

```python
from remind.snapshot import SnapshotEngine

engine = SnapshotEngine(memory.store, memory.embedding)

# See what needs review
snapshot = await engine.snapshot(["pending", "conflicts"])
print(f"Pending episodes: {len(snapshot['pending'])}")
print(f"Open conflicts: {len(snapshot['conflicts'])}")

# Entity detail
snapshot = await engine.snapshot(["entity:tool:redis"])
print(f"Facts about Redis: {snapshot['entity']}")

# Semantic search
snapshot = await engine.snapshot(["query:cache configuration"])
print(f"Matching concepts: {snapshot['query_results']}")
```

## Conflict resolution

```python
# List open conflicts
conflicts = memory.list_conflicts(status="open")

# Resolve: winner stays, loser is superseded
await memory.resolve_conflict(
    conflict_id,
    winning_fact_id=fact_id,
    note="confirmed in prod config",
    resolved_by="alice",
)

# Dismiss: both valid in different contexts
memory.dismiss_conflict(
    conflict_id,
    note="both true: staging vs prod",
)
```

## Key design decisions

- **`remember()` and `remember_batch()` are async** — Embedding happens before the atomic write. Local embeddings require no remote API call.
- **`snapshot()` is async** — Batch read for current memory state.
- **`apply()` is async** — Transactional batch writes.
- **`recall()` is async** — Uses embeddings and spreading activation.

## Database and project config

```python
from pathlib import Path

# Default → nearest parent .remind/memory, or <cwd>/.remind/memory
memory = create_memory()

# Named Git-friendly file store under ~/.remind/
# Resolves to ~/.remind/my-project.memory
memory = create_memory(db_path="my-project")

# Explicit SQLite remains available through a SQLAlchemy URL
memory = create_memory(store_url="sqlite:////absolute/path/to/remind.db")

# Other SQLAlchemy URLs (PostgreSQL, MySQL, etc.)
memory = create_memory(db_url="postgresql+psycopg://user:pass@localhost:5432/remind")

# Load <project>/.remind/remind.config.json
memory = create_memory(project_dir=Path("/path/to/myproject"))
```

## Provider selection

Embeddings default to local (`all-MiniLM-L6-v2`). For remote embeddings:

```python
# OpenAI embeddings
memory = create_memory(embedding_provider="openai")

# From config file / env vars
memory = create_memory()  # Uses ~/.remind/remind.config.json
```

See [Configuration](/guide/configuration) and [Providers](/reference/providers) for all options.

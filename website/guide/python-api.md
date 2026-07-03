# Python API

Use Remind as a library in your own Python applications.

## Basic usage

```python
import asyncio
from remind import create_memory, EpisodeType

async def main():
    # Uses local embeddings by default — no API keys needed
    memory = create_memory()

    # Log experiences — fast, no external calls
    memory.remember("User mentioned they prefer Python for backend work")
    memory.remember("User is building a distributed system")
    memory.remember("User values type safety")

    # Typed episodes
    memory.remember("Chose PostgreSQL over MySQL for persistence", episode_type=EpisodeType.DECISION)
    memory.remember("User prefers dark mode in the IDE", episode_type=EpisodeType.PREFERENCE)

    # Topic-scoped episodes
    memory.remember("Use event sourcing for audit trail", topic="architecture")

    # Fact episodes — clustered automatically, collisions detected
    result = memory.remember(
        "Redis TTL is 300s for auth tokens",
        episode_type=EpisodeType.FACT,
        entities=["tool:redis"],
        asserted_by="alice",
    )
    if result.collisions:
        print(f"Collision detected with: {result.collisions}")

    # Retrieve relevant concepts
    context = await memory.recall("What programming preferences?")
    print(context)

    # Topic-scoped retrieval
    context = await memory.recall("database design", topic="architecture")

    # Time-travel: facts valid at a past point in time
    context = await memory.recall("cache configuration", as_of="2024-06-01")

asyncio.run(main())
```

## Fact episodes and collisions

Facts are handled deterministically:

```python
# Store a fact
result = memory.remember(
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

When a fact collides with existing facts (same entities, different statements), the collision is reported but NOT auto-resolved. Handle it via `apply()`:

```python
# Get collisions that need resolution
snapshot = await memory.snapshot(["conflicts"])
for conflict in snapshot["conflicts"]:
    print(f"Conflict: {conflict['description']}")
    print(f"Facts: {conflict['fact_ids']}")
```

## Batch operations with apply

Use `apply()` for transactional curation:

```python
# Compact format
result = await memory.apply("""
remember as=f1 t=fact e=tool:redis "Cache TTL is 600s"
supersede old=fact:abc123 new=$f1
concept from=ep:11,ep:12 title="Redis config" "TTL-based caching"
processed ids=ep:11,ep:12
""")

# JSON format
result = await memory.apply([
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
# See what needs review
snapshot = await memory.snapshot(["pending", "conflicts"])
print(f"Pending episodes: {len(snapshot['pending'])}")
print(f"Open conflicts: {len(snapshot['conflicts'])}")

# Entity detail
snapshot = await memory.snapshot(["entity:tool:redis"])
print(f"Facts about Redis: {snapshot['entity']}")

# Semantic search
snapshot = await memory.snapshot(["query:cache configuration"])
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
await memory.dismiss_conflict(
    conflict_id,
    note="both true: staging vs prod",
)
```

## Key design decisions

- **`remember()` is synchronous and fast** — No external calls (local embeddings), just stores the episode. For facts, returns collision info.
- **`snapshot()` is async** — Batch read for current memory state.
- **`apply()` is async** — Transactional batch writes.
- **`recall()` is async** — Uses embeddings and spreading activation.

## Database and project config

```python
from pathlib import Path

# Default db_path "memory" → ~/.remind/memory.db
memory = create_memory()

# Named SQLite under ~/.remind/
memory = create_memory(db_path="my-project")

# Any SQLAlchemy URL (PostgreSQL, MySQL, etc.)
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

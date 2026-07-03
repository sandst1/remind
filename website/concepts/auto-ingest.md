# Fact Pipeline

The fact pipeline handles `fact`-type episodes automatically, without LLM involvement. When you store a fact, Remind clusters it, detects collisions, and reports back for agent triage.

## How it works

### 1. Store and embed

```
remember(content="Cache TTL is 300s", episode_type="fact", entities="tool:redis")
```

The episode is stored and embedded immediately (local embeddings by default).

### 2. Cluster assignment

Facts are clustered by **entity overlap** using Jaccard similarity:

```
similarity = |shared entities| / |total entities|
```

If similarity ≥ threshold (default 0.5), the fact joins an existing cluster. Otherwise, a new cluster is created.

This prevents transitive explosion where unrelated facts get merged just because they share a common entity like "user" or "config".

### 3. Collision detection

Active facts in the assigned cluster with entity overlap are returned as **collisions**:

```python
result = await memory.remember(
    "Cache TTL is 600s",
    episode_type="fact",
    entities=["tool:redis"]
)

# result.collisions might contain:
# [Fact(statement="Cache TTL is 300s", ...)]
```

Collisions are NOT auto-resolved. The agent decides what to do.

### 4. Agent triage

Handle collisions via `apply`:

```
# Supersede: new fact replaces old
supersede old=fact:abc123 new=fact:def456

# Conflict: flag for later resolution
conflict fact_a=abc123 fact_b=def456 severity=medium

# Or just ignore if they're compatible
```

## `remember` vs `apply` for facts

| | `remember` | `apply` |
|---|---|---|
| **Creates fact** | Yes | Yes (via `remember` op) |
| **Clusters automatically** | Yes | Yes |
| **Detects collisions** | Yes (returns them) | Yes (returns them) |
| **Resolves collisions** | No | Yes (via `supersede`/`conflict`) |
| **Batched** | No | Yes |

Use `remember` for single facts during work. Use `apply` for batch operations and collision resolution.

## Fact clusters

Facts are grouped into `fact_cluster` concepts:

- **Title** — Generated from shared entities (e.g., "Redis configuration")
- **Active facts** — Facts with open validity windows
- **Superseded facts** — Facts that have been replaced

Each fact has:
- `statement` — The verbatim content
- `valid_from` — When it became true
- `valid_to` — When it was superseded (null if active)
- `superseded_by` — ID of the replacing fact
- `source_episode_id` — The episode it came from
- `asserted_by` — Who stated it (provenance)
- `source_ref` — Link to original artifact

## Viewing clusters

Use `snapshot` to inspect fact clusters:

```
snapshot(scopes="entity:tool:redis")   # Facts about Redis
snapshot(scopes="concept:cluster_id")  # Full cluster detail
```

Or `recall` with time-travel:

```
recall(query="redis config", as_of="2024-06-01")  # Facts valid at that date
```

## Configuration

| Option | Default | Description |
|--------|---------|-------------|
| `fact_cluster_jaccard_threshold` | `0.5` | Min Jaccard similarity for clustering |

Lower values create larger clusters (more facts grouped together).
Higher values create more focused clusters (facts need more entity overlap).

## Provenance

Track where facts come from:

```
remember(
    content="API rate limit is 100 req/s",
    episode_type="fact",
    entities="concept:api",
    asserted_by="alice",
    source_ref="https://github.com/org/repo/pull/42"
)
```

Provenance is shown in recall output and conflict details, helping agents decide which fact is authoritative.

# MCP Tools

Tools available when connecting to Remind via MCP.

## remember

Store an experience as an episode.

```
remember(content="User prefers TypeScript", episode_type="preference")
remember(content="Use Redis for caching", episode_type="decision", entities="tool:redis,subject:caching")
remember(content="Cache TTL is 300s", episode_type="fact", entities="tool:redis", asserted_by="alice", source_ref="https://github.com/org/repo/pull/42")
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `content` | string | Yes | The experience to store |
| `episode_type` | string | No | `observation` (default), `decision`, `question`, `preference`, `meta`, `outcome`, `fact` |
| `entities` | string | No | Comma-separated entity tags (`type:name`) |
| `topic` | string | No | Knowledge area (e.g., `"architecture"`, `"product"`) |
| `asserted_by` | string | No | Who asserted this information (provenance) |
| `source_ref` | string | No | Link back to the original artifact (URL/permalink) |

### Fact episodes

When `episode_type="fact"`, the episode is:
1. Stored and embedded
2. Clustered by entity overlap with existing facts
3. Checked for collisions with active facts in the cluster

The response includes:
- `fact_id` — the new fact's ID
- `cluster_id` — the fact cluster it was assigned to
- `cluster_created` — whether a new cluster was created
- `collisions` — existing active facts with entity overlap

Handle collisions via `apply` with `supersede` or `conflict` ops.

## recall

Retrieve relevant memories.

```
recall(query="authentication issues")
recall(query="auth", entity="file:src/auth.ts")
recall(entity="file:src/auth.ts")
recall(query="database design", topic="architecture")
recall(query="cache configuration", as_of="2024-06-01")
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | string | No | Search query (required for semantic search) |
| `k` | integer | No | Number of concepts to return (default: 3) |
| `context` | string | No | Additional context to improve retrieval |
| `entity` | string | No | Scope to entity (can be used alone) |
| `episode_k` | integer | No | Episodes via direct vector search (default: 5, 0 to disable) |
| `topic` | string | No | Filter to a knowledge area |
| `as_of` | string | No | ISO date/datetime for time-travel (facts valid at that point) |

At least one of `query` or `entity` must be provided.

If the output shows an `OPEN CONFLICTS` warning, triage with `snapshot` and `apply`.

## snapshot

Batch read returning current memory state as JSON. Combine scopes in a single call.

```
snapshot(scopes="pending")                    # Unprocessed episodes with entities
snapshot(scopes="conflicts")                  # Open conflicts with fact context
snapshot(scopes="pending,conflicts")          # Both at once
snapshot(scopes="entity:tool:redis")          # All data for an entity
snapshot(scopes="topic:architecture")         # All data for a topic
snapshot(scopes="concept:abc123")             # Concept detail with facts/history
snapshot(scopes="recent:20")                  # 20 most recent episodes
snapshot(scopes="stats")                      # Memory statistics
snapshot(scopes="query:cache config")         # Semantic search (concepts only)
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `scopes` | string | Yes | Comma-separated scope specifiers |

**Scopes**:
- `pending` — Episodes not yet processed, with their entities
- `conflicts` — Open conflicts with both facts and provenance
- `entity:<id>` — Entity detail with episodes and fact clusters
- `topic:<id>` — Topic detail with all episodes and concepts
- `concept:<id>` — Concept detail including superseded fact history
- `recent:<n>` — N most recent episodes
- `stats` — Memory statistics
- `query:<text>` — Semantic search for concepts

## apply

Batch write for transactional memory curation. All-or-nothing; returns per-op results.

### Compact format (preferred)

One op per line, shlex tokenization, `key=value` args, trailing quoted string = content/note:

```
remember as=f1 t=fact e=tool:redis by=alice "Cache TTL is 600 seconds"
supersede old=fact:a91c2 new=$f1
remember as=o1 t=outcome e=subject:auth "SameSite=Strict broke OAuth; Lax required"
concept as=c1 from=ep:11,ep:12 title="Retry with backoff" "Transient failures resolve with backoff"
resolve id=conflict:7 winner=fact:b3d01 "confirmed by bob"
processed ids=ep:11,ep:12
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `changeset` | string | Yes | Ops in compact or JSON format |
| `dry_run` | boolean | No | Validate without executing |

### Operations

| Op | Arguments | Description |
|----|-----------|-------------|
| `remember` | `as`, `t`, `e`, `by`, `ref`, content | Store episode (batched) |
| `supersede` | `old`, `new` | Replace old fact with new |
| `conflict` | `fact_a`, `fact_b`, `severity` | Open a conflict |
| `resolve` | `id`, `winner`, note | Resolve conflict (winner supersedes loser) |
| `dismiss` | `id`, note | Dismiss conflict (both stay active) |
| `concept` | `as`, `title`, `from`, `relations`, summary | Create concept from episodes |
| `update` | `id`, field=value... | Update episode/concept fields |
| `link` | `source`, `type`, `target` | Add concept relation |
| `topic` | `name`, description | Create topic |
| `set_topic` | `id`, `topic` | Assign topic to episode/concept |
| `delete` | `id` | Soft delete |
| `restore` | `id` | Restore deleted item |
| `processed` | `ids` | Mark episodes as reviewed |

**Local refs**: Use `as=name` to declare, `$name` to reference within the changeset.

### JSON format

```json
[
  {"op": "remember", "as": "f1", "t": "fact", "content": "Cache TTL is 600s",
   "e": ["tool:redis"], "by": "alice"},
  {"op": "supersede", "old": "fact:a91c2", "new": "$f1"},
  {"op": "resolve", "id": "conflict:7", "winner": "fact:b3d01", "note": "confirmed"}
]
```

## stats

Memory statistics.

```
stats()
```

## Topic tools

### create_topic

```
create_topic(name="Architecture", description="System design decisions")
```

### update_topic

```
update_topic(topic_id="architecture", description="Updated description")
```

### delete_topic

```
delete_topic(topic_id="old-topic")  # Only works if no episodes/concepts use it
```

### list_topics

```
list_topics()
```

### topic_overview

```
topic_overview(topic_id="architecture")
topic_overview(topic_id="product", k=10)
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `topic_id` | string | Yes | Topic ID (slug) |
| `k` | integer | No | Number of concepts (default: 5) |

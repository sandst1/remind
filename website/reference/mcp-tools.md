# MCP Tools

Tools available when connecting to Remind via MCP.

## remember

Store an experience as an episode.

```
remember(content="User prefers TypeScript", episode_type="preference")
remember(content="Use Redis for caching", episode_type="decision", entities="tool:redis,subject:caching")
remember(content="Cache TTL is 300s", episode_type="fact", entities="tool:redis", labels="topic=infra", asserted_by="alice", source_ref="https://github.com/org/repo/pull/42")
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `content` | string | Yes | The experience to store |
| `metadata` | string | No | Optional JSON string with additional metadata |
| `episode_type` | string | No | `observation` (default), `decision`, `question`, `preference`, `meta`, `outcome`, `fact` |
| `entities` | string | No | Comma-separated entity tags (`type:name`) |
| `labels` | string | No | Comma-separated `key=value` labels (e.g. `"topic=architecture"` or `"topic=architecture,team=infra"`) |
| `source_type` | string | No | Origin of this memory (e.g. `"agent"`, `"slack"`, `"github"`, `"manual"`) |
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
recall(query="database design", labels="topic=architecture")
recall(query="cache configuration", as_of="2024-06-01")
recall(query="auth", max_chars=2000)
recall(query="auth", min_score=0.3, timeout_ms=500)
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | string | No | Search query (required for semantic search) |
| `k` | integer | No | Number of concepts to return (default: 3) |
| `context` | string | No | Additional context to improve retrieval |
| `entity` | string | No | Scope to entity (can be used alone) |
| `episode_k` | integer | No | Episodes via direct vector search (default: 5, 0 to disable) |
| `labels` | string | No | Comma-separated `key=value` label filter (e.g. `"topic=architecture"`). Pre-filters candidates before vector search runs — spreading activation still follows the graph beyond the filtered set. |
| `as_of` | string | No | ISO date/datetime for time-travel (facts valid at that point) |
| `max_chars` | integer | No | Cap the formatted output length; drops lowest-ranked concepts/episodes whole (never mid-item) until it fits |
| `min_score` | float | No | Drop concepts/episodes below this activation score even if k/episode_k budget remains |
| `timeout_ms` | integer | No | Soft deadline; returns best-so-far instead of raising if exceeded |

At least one of `query` or `entity` must be provided.

If the output shows an `OPEN CONFLICTS` warning, triage with `list_conflicts` / `resolve_conflict` / `dismiss_conflict`.

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
| `conflict` | `fact_a`, `fact_b`, `severity`, description | Open a conflict |
| `resolve` | `id`, `winner`, note | Resolve conflict (winner supersedes loser) |
| `dismiss` | `id`, note | Dismiss conflict (both stay active) |
| `concept` | `as`, `title`, `from`, `type`, `relations`, summary | Create concept from episodes |
| `update` | `id`, field=value... | Update episode/concept fields |
| `link` | `from`, `to`, `type` | Add concept relation |
| `label` | `id`, `key`, `value` | Add a key=value label to episode/concept |
| `unlabel` | `id`, `key`, `value` | Remove a key=value label from episode/concept |
| `entity_relation` | `source`, `target`, `relation`, `strength`, `context` | Add a typed relation between entities |
| `evidence` | `concept`, `episode`, `type`, `strength`, note | Link an episode to a concept as supporting/contradicting/exemplifying/qualifying evidence |
| `unlink` | `concept`, `episode` | Remove an evidence link |
| `reshape` | `id`, `type`, reason | Change a concept's type (e.g. pattern → hypothesis) |
| `merge` | `from`, `into`, reason | Merge overlapping concepts (sources soft-deleted with lineage) |
| `split` | `id`, `into`, reason | Split a concept into multiple new concepts |
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

## snapshot

Batch read returning current memory state as JSON. Combine scopes in a single call.

```
snapshot(scopes="pending")                    # Unprocessed episodes with entities
snapshot(scopes="conflicts")                  # Open conflicts with fact context
snapshot(scopes="pending,conflicts")          # Both at once
snapshot(scopes="entity:tool:redis")          # All data for an entity
snapshot(scopes="labels")                     # All distinct labels with counts
snapshot(scopes="label:topic=architecture")   # All data for a label
snapshot(scopes="concept:abc123")             # Concept detail with facts/history
snapshot(scopes="recent:20")                  # 20 most recent episodes
snapshot(scopes="stats")                      # Memory statistics
snapshot(scopes="query:cache config")         # Semantic search (concepts only)
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `scopes` | string | Yes | Space or comma separated scope specifiers |

**Scopes**:
- `pending` — Episodes not yet processed, with their entities
- `conflicts` — Open conflicts with both facts and provenance
- `entity:<id>` — Entity detail with episodes and fact clusters
- `labels` — All distinct `key=value` labels in use, with counts
- `label:<key>=<value>` — All episodes and concepts carrying a label
- `concept:<id>` — Concept detail including superseded fact history
- `recent:<n>` — N most recent episodes
- `stats` — Memory statistics
- `query:<text>` — Semantic search for concepts
- `events[:<since_seq>]` — Change-feed events with `seq > since_seq` (default 0). Prefer the `events` tool below.
- `bootstrap[:<n>]` — Query-free stable context: top-n actionable concepts by confidence and instance count, plus open conflict count and stats (default 10). Needs no embedding call and is deterministic for a given memory state — cheap enough to call every session, or to place in a system prompt via an injection layer.

## events

Read the append-only change feed of writes. Poll with `since_seq` instead of re-scanning `snapshot(scopes="pending")` to detect new activity — useful for consolidation daemons and sync layers built on top of Remind.

```
events()                                       # All events from the start
events(since_seq=42)                           # Only events after seq 42
events(since_seq=42, kind="conflict_opened")   # Filter to one kind
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `since_seq` | integer | No | Only return events with `seq` greater than this (default: 0) |
| `limit` | integer | No | Maximum number of events to return (default: 200) |
| `kind` | string | No | Filter to a single event kind |

Returns `{since_seq, count, events, next_since_seq}`. Every successful `remember` and every successful `apply` op appends one row, atomically with the write it describes. `kind` is one of `remembered`, `superseded`, `conflict_opened`, `conflict_resolved`, `conflict_dismissed`, `concept_created`, `updated`, `labeled`, `unlabeled`, `deleted`, `restored`, `processed`. Each event has `seq`, `ts`, `kind`, `subject_type`, `subject_id`, and an optional `payload`. Save `next_since_seq` and pass it back as `since_seq` on the next poll.

## list_conflicts

List detected memory conflicts (contradictions) awaiting triage.

```
list_conflicts()
list_conflicts(status="all")
list_conflicts(status="open", kind="fact")
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `status` | string | No | `open` (default), `resolved`, `dismissed`, or `all` |
| `kind` | string | No | Filter by `fact` or `concept` |

## resolve_conflict

Resolve a conflict by declaring which fact is correct. The losing fact is structurally superseded (kept as history, hidden from recall).

```
resolve_conflict(conflict_id="conflict:7", winning_fact_id="fact:b3d01", note="confirmed in prod config")
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `conflict_id` | string | Yes | The conflict to resolve (from `list_conflicts`) |
| `winning_fact_id` | string | No | The correct fact's ID (required for fact conflicts) |
| `note` | string | No | Why this resolution is correct |
| `resolved_by` | string | No | Who decided |

## dismiss_conflict

Dismiss a conflict: both claims are valid (e.g. different contexts). Both facts stay active.

```
dismiss_conflict(conflict_id="conflict:7", note="staging vs prod, both true")
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `conflict_id` | string | Yes | The conflict to dismiss (from `list_conflicts`) |
| `note` | string | No | Why this isn't a real contradiction |
| `resolved_by` | string | No | Who decided |

## inspect

Inspect concepts or episodes in memory (list all, view one, or filter episodes by date range).

```
inspect()
inspect(concept_id="abc123")
inspect(show_episodes=True, start_date="2024-01-01", end_date="2024-01-31")
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `concept_id` | string | No | ID of a specific concept to inspect |
| `show_episodes` | boolean | No | Show episodes instead of concepts |
| `limit` | integer | No | Maximum number of items to show (default: 10) |
| `start_date` | string | No | ISO date/datetime, inclusive start (episodes only) |
| `end_date` | string | No | ISO date/datetime, inclusive end (episodes only) |

## stats

Memory statistics: concept/episode counts, consolidation status, relation type distribution.

```
stats()
```

## episode_types

List episode types configured for this project/environment (built-in and custom).

```
episode_types()
```

## entities

List entities (files, functions, people, etc.) mentioned in episodes.

```
entities()
entities(entity_type="tool", limit=20)
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `entity_type` | string | No | Filter by type: `file`, `function`, `class`, `module`, `concept`, `person`, `project`, `tool`, `other` |
| `limit` | integer | No | Maximum number of entities to show (default: 50) |

## inspect_entity

Inspect an entity and its relationships to other entities.

```
inspect_entity(entity_id="file:src/auth.ts")
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `entity_id` | string | Yes | Entity ID to inspect (e.g. `"file:src/auth.ts"`, `"person:alice"`) |
| `show_relations` | boolean | No | Whether to include relationships (default: True) |

## update_episode

Update an existing episode — correct mistakes, reclassify, or relabel. Only provided fields are updated.

```
update_episode(episode_id="ep:11", content="Corrected information")
update_episode(episode_id="ep:11", labels="topic=architecture,team=infra")
update_episode(episode_id="ep:11", labels="")  # clear all labels
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `episode_id` | string | Yes | ID of the episode to update |
| `content` | string | No | New content text (resets the episode for re-consolidation) |
| `episode_type` | string | No | New type |
| `entities` | string | No | New comma-separated entity IDs |
| `plan_id` | string | No | Plan episode ID to link this task to |
| `spec_ids` | string | No | Comma-separated spec episode IDs to link this task to |
| `depends_on` | string | No | Comma-separated task IDs this task depends on |
| `priority` | string | No | Priority level: `p0`, `p1`, or `p2` |
| `labels` | string | No | Comma-separated `key=value` labels; replaces all existing labels; empty string clears them |

## delete_episode / restore_episode

Soft delete or restore an episode.

```
delete_episode(episode_id="ep:11")
restore_episode(episode_id="ep:11")
```

## update_concept

Update an existing concept — refine or correct generalized knowledge. Only provided fields are updated.

```
update_concept(concept_id="c-123", summary="Refined summary")
update_concept(concept_id="c-123", labels="topic=architecture")
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `concept_id` | string | Yes | ID of the concept to update |
| `title` | string | No | New short title |
| `summary` | string | No | New summary text (clears the embedding; regenerates on next recall) |
| `confidence` | float | No | New confidence score (0.0-1.0) |
| `tags` | string | No | New comma-separated tags |
| `relations` | string | No | JSON array of relations, e.g. `[{"type":"implies","target_id":"abc","strength":0.7}]` |
| `labels` | string | No | Comma-separated `key=value` labels; replaces all existing labels; empty string clears them |

## delete_concept / restore_concept

Soft delete or restore a concept.

```
delete_concept(concept_id="c-123")
restore_concept(concept_id="c-123")
```

## list_deleted

List soft-deleted episodes and concepts.

```
list_deleted()
list_deleted(item_type="episodes", limit=50)
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `item_type` | string | No | `"episodes"`, `"concepts"`, or omit for both |
| `limit` | integer | No | Maximum number of items to show per type (default: 20) |

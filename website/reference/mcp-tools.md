# MCP Tools

Tools available when connecting to Remind via MCP.

## remember

Store an experience as an episode.

```
remember(content="User prefers TypeScript", episode_type="preference")
remember(content="Use Redis for caching", episode_type="decision", entities="tool:redis,concept:caching")
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `content` | string | Yes | The experience to store |
| `episode_type` | string | No | `observation` (default), `decision`, `question`, `preference`, `meta`, `spec`, `plan`, `task` |
| `entities` | string | No | Comma-separated entity tags (`type:name`) |

## recall

Retrieve relevant memories.

```
recall(query="authentication issues")
recall(query="auth", entity="file:src/auth.ts")
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | string | Yes | Search query |
| `entity` | string | No | Scope to entity |

## consolidate

Process episodes into concepts.

```
consolidate()
consolidate(force=True)
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `force` | boolean | No | Force consolidation even with few episodes |

## inspect

View concepts or episodes.

```
inspect()                              # List all concepts
inspect(concept_id="abc123")           # Concept details
inspect(show_episodes=True)            # Include episodes
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `concept_id` | string | No | Specific concept to inspect |
| `show_episodes` | boolean | No | Include episode details |

## entities

List entities with mention counts.

```
entities()
entities(entity_type="file", limit=20)
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `entity_type` | string | No | Filter by type |
| `limit` | integer | No | Max results |

## inspect_entity

View entity details and relationships.

```
inspect_entity(entity_id="file:src/auth.ts")
inspect_entity(entity_id="person:alice", show_relations=True)
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `entity_id` | string | Yes | Entity ID |
| `show_relations` | boolean | No | Include relationships |

## stats

Memory statistics.

```
stats()
```

## update_episode

Correct or modify an episode. Updating content resets it for re-consolidation.

```
update_episode(episode_id="abc123", content="Corrected information")
update_episode(episode_id="abc123", episode_type="decision")
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `episode_id` | string | Yes | Episode ID |
| `content` | string | No | New content |
| `episode_type` | string | No | New type |
| `entities` | string | No | New entity tags |

## delete_episode / restore_episode

Soft delete and restore episodes.

```
delete_episode(episode_id="abc123")
restore_episode(episode_id="abc123")
```

## update_concept

Refine a concept. Updating summary clears the embedding.

```
update_concept(concept_id="def456", summary="Refined understanding")
update_concept(concept_id="def456", confidence=0.9, tags="auth,security")
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `concept_id` | string | Yes | Concept ID |
| `title` | string | No | New title |
| `summary` | string | No | New summary |
| `confidence` | float | No | New confidence |
| `tags` | string | No | Comma-separated tags |

## delete_concept / restore_concept

Soft delete and restore concepts.

```
delete_concept(concept_id="def456")
restore_concept(concept_id="def456")
```

## list_deleted

List soft-deleted items.

```
list_deleted()
list_deleted(item_type="episode")
list_deleted(item_type="concept")
```

## task_add

Create a new task.

```
task_add(content="Implement JWT auth", entities="module:auth", priority="p0")
task_add(content="Write tests", depends_on="task-id-1", plan="plan-id")
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `content` | string | Yes | Task description |
| `entities` | string | No | Comma-separated entities |
| `priority` | string | No | `p0`, `p1`, `p2` |
| `plan` | string | No | Plan episode ID |
| `spec` | string | No | Spec episode ID |
| `depends_on` | string | No | Dependency task ID |

## task_update_status

Transition a task's status.

```
task_update_status(task_id="abc123", status="in_progress")
task_update_status(task_id="abc123", status="blocked", reason="Waiting on API key")
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `task_id` | string | Yes | Task ID |
| `status` | string | Yes | `todo`, `in_progress`, `done`, `blocked` |
| `reason` | string | No | Block reason (for `blocked` status) |

## list_tasks / list_specs / list_plans

List filtered episodes by type.

```
list_tasks(status="todo", entity="module:auth")
list_specs()
list_plans()
```

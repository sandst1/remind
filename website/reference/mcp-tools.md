# MCP Tools

Tools available when connecting to Remind via MCP.

## remember

Store an experience as an episode.

```
remember(content="User prefers TypeScript", episode_type="preference")
remember(content="Use Redis for caching", episode_type="decision", entities="tool:redis,concept:caching")
remember(content="Chose microservices", topic="architecture", source_type="agent")
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `content` | string | Yes | The experience to store |
| `episode_type` | string | No | `observation` (default), `decision`, `question`, `preference`, `meta`, `spec`, `plan`, `task`, `outcome`, `fact` |
| `entities` | string | No | Comma-separated entity tags (`type:name`) |
| `topic` | string | No | Knowledge area (e.g., `"architecture"`, `"product"`). Scopes consolidation and retrieval. |
| `source_type` | string | No | Origin of the memory (e.g., `"agent"`, `"slack"`, `"manual"`) |

## ingest

Stream raw text into the auto-ingest pipeline. Text buffers internally until a character threshold (~4000 chars) is reached, then gets scored for information density and distilled into episodes automatically.

```
ingest(content="User: Fix the auth bug\nAssistant: Looking at verify_credentials...")
ingest(content="<tool output>", source="tool_output")
ingest(content="Chose Redis for caching", topic="architecture")
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `content` | string | Yes | Raw text to ingest |
| `source` | string | No | Source label for metadata (default: `conversation`) |
| `topic` | string | No | Topic ID or name. When set, all extracted episodes go to this topic. When omitted, the triage LLM infers per-episode topics automatically. |

**Topic behavior**: With `topic`, all episodes are assigned to the given topic (no inference). Without `topic`, the triage LLM maps each episode to an existing topic or suggests a new one (auto-created).

**`ingest` vs `remember`**: Use `remember` when you've already decided what's worth storing. Use `ingest` when you want Remind to decide — it scores information density, filters low-value content, and distills memory-worthy episodes automatically. Episodes from `ingest` are immediately consolidated.

## flush_ingest

Force-flush the ingestion buffer, processing whatever text has accumulated regardless of the character threshold.

```
flush_ingest()
flush_ingest(topic="architecture")
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `topic` | string | No | Topic for extracted episodes. Same behavior as `ingest()` topic parameter. |

Use at session end or whenever you want to ensure all ingested text is processed.

## recall

Retrieve relevant memories.

```
recall(query="authentication issues")
recall(query="auth", entity="file:src/auth.ts")
recall(entity="file:src/auth.ts")
recall(query="database design", topic="architecture")
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | string | No | Search query (required for semantic search, not needed for entity-only lookup) |
| `k` | integer | No | Number of concepts to return (default: 3) |
| `context` | string | No | Additional context to improve retrieval |
| `entity` | string | No | Scope to entity (can be used alone without a query) |
| `episode_k` | integer | No | Number of episodes to retrieve via direct vector search (default: 5). Set to 0 to disable. |
| `topic` | string | No | Filter to a knowledge area. Cross-topic concepts may still surface via spreading activation but are penalized. |

At least one of `query` or `entity` must be provided.

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

## list_topics

List all topics with episode and concept counts.

```
list_topics()
```

Returns each topic's name, number of episodes, number of concepts, and when it was last active.

## topic_overview

Get top concepts for a specific topic — a quick way to see what Remind knows about a knowledge area without running a query.

```
topic_overview(topic="architecture")
topic_overview(topic="product", k=10)
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `topic` | string | Yes | Topic name |
| `k` | integer | No | Number of concepts to return (default: 5) |

## task_add / task_update_status / list_tasks / list_specs / list_plans

::: tip Conditional tools
These tools are only registered when the corresponding episode type (`task`, `spec`, `plan`) is enabled in your [configuration](/guide/configuration#episode-types). All types are enabled by default.
:::

### task_add

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

### task_update_status

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

### list_tasks / list_specs / list_plans

List filtered episodes by type.

```
list_tasks(status="todo", entity="module:auth")
list_specs()
list_plans()
```

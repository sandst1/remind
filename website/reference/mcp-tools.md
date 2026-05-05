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
| `episode_type` | string | No | `observation` (default), `decision`, `question`, `preference`, `meta`, `outcome`, `fact` |
| `entities` | string | No | Comma-separated entity tags (`type:name`) |
| `topic` | string | No | Knowledge area (e.g., `"architecture"`, `"product"`). Scopes consolidation and retrieval. |
| `source_type` | string | No | Origin of the memory (e.g., `"agent"`, `"slack"`, `"manual"`) |

## ingest

Stream raw text into the auto-ingest pipeline. Text buffers internally until a character threshold (~4000 chars) is reached, then the **triage LLM** decides what to extract as episodes. A density score (0.0–1.0) may be returned for diagnostics only; it does not gate extraction.

```
ingest(content="User: Fix the auth bug\nAssistant: Looking at verify_credentials...")
ingest(content="<tool output>", source="tool_output")
ingest(content="Chose Redis for caching", topic="architecture")
ingest(content="<meeting transcript>", instructions="extract decisions and action items")
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `content` | string | Yes | Raw text to ingest |
| `source` | string | No | Source label for metadata (default: `conversation`) |
| `topic` | string | No | Topic ID or name. When set, all extracted episodes go to this topic. When omitted, episodes get `topic_id=None`. |
| `instructions` | string | No | Natural-language instructions to steer what the triage LLM extracts (e.g. `"focus on architectural decisions"`). Appended to the triage system prompt; takes priority over default extraction behavior. |

**Topic behavior**: With `topic`, all extracted episodes are assigned to that topic. Without `topic`, episodes get `topic_id=None` — no automatic inference.

**Instructions**: Use `instructions` to focus extraction on specific types of information. Without `instructions`, the triage LLM uses its default behavior (capture anything potentially useful). With `instructions`, the LLM prioritizes the given directive — useful for ingesting meeting notes, transcripts, or documents where you know what you're looking for.

**`ingest` vs `remember`**: Use `remember` when you've already decided what's worth storing. Use `ingest` when you want the triage LLM to choose what to keep — it skips filler and distills memory-worthy episodes. Episodes from `ingest` are immediately consolidated.

## flush_ingest

Force-flush the ingestion buffer, processing whatever text has accumulated regardless of the character threshold.

```
flush_ingest()
flush_ingest(topic="architecture")
flush_ingest(instructions="extract only action items")
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `topic` | string | No | Topic for extracted episodes. Same behavior as `ingest()` topic parameter. |
| `instructions` | string | No | Instructions to steer extraction. Same as `ingest()` instructions parameter. |

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
inspect(show_episodes=True)            # Recent episodes
inspect(show_episodes=True, limit=25, start_date="2024-01-01", end_date="2024-12-31")
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `concept_id` | string | No | Specific concept to inspect |
| `show_episodes` | boolean | No | List recent episodes instead of concepts |
| `limit` | integer | No | Max items (default: 10) |
| `start_date` | string | No | ISO date/datetime filter (episodes), inclusive |
| `end_date` | string | No | ISO date/datetime filter (episodes), inclusive |

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

## episode_types

List episode types enabled for this server (from environment, project config, global config, then defaults). Use when `episode_types` is customized.

```
episode_types()
```

## update_episode

Correct or modify an episode. Updating content resets it for re-consolidation.

```
update_episode(episode_id="abc123", content="Corrected information")
update_episode(episode_id="abc123", episode_type="decision")
update_episode(episode_id="abc123", topic="architecture")
update_episode(episode_id="abc123", topic="")   # clear topic (empty string)
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `episode_id` | string | Yes | Episode ID |
| `content` | string | No | New content |
| `episode_type` | string | No | New type |
| `entities` | string | No | Comma-separated entity tags |
| `plan_id` | string | No | Optional metadata link (legacy DB content) |
| `spec_ids` | string | No | Comma-separated spec episode IDs (legacy) |
| `depends_on` | string | No | Comma-separated task IDs (legacy) |
| `priority` | string | No | `p0`, `p1`, or `p2` (legacy) |
| `topic` | string | No | Topic ID or name; **empty string clears** the episode topic |

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
update_concept(concept_id="def456", topic="architecture")
update_concept(concept_id="def456", topic="")   # clear topic
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `concept_id` | string | Yes | Concept ID |
| `title` | string | No | New title |
| `summary` | string | No | New summary |
| `confidence` | float | No | New confidence |
| `tags` | string | No | Comma-separated tags |
| `relations` | string | No | JSON array of relations |
| `topic` | string | No | Topic ID or name; **empty string clears** the concept topic |

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
list_deleted(item_type="episodes")
list_deleted(item_type="concepts")
list_deleted(item_type="all")
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `item_type` | string | No | `episodes`, `concepts`, or `all` (default: show both) |
| `limit` | integer | No | Max items per type (default: 20) |

## create_topic

Create a topic for grouping episodes and concepts.

```
create_topic(name="Architecture", description="System design and infra")
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `name` | string | Yes | Display name |
| `description` | string | No | Optional description |

## update_topic

Update a topic's name or description.

```
update_topic(topic_id="architecture", name="System architecture")
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `topic_id` | string | Yes | Topic ID |
| `name` | string | No | New display name (omit to keep) |
| `description` | string | No | New description (omit to keep) |

## delete_topic

Delete a topic only if no episodes or concepts reference it.

```
delete_topic(topic_id="old-theme")
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `topic_id` | string | Yes | Topic ID |

## list_topics

List all topics with episode and concept counts.

```
list_topics()
```

Returns each topic's name, number of episodes, number of concepts, and when it was last active.

## topic_overview

Get top concepts for a specific topic — a quick way to see what Remind knows about a knowledge area without running a query.

```
topic_overview(topic_id="architecture")
topic_overview(topic_id="product", k=10)
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `topic_id` | string | Yes | Topic ID (slug), e.g. `architecture` |
| `k` | integer | No | Number of concepts to return (default: 5) |

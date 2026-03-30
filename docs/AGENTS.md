# Remind - AI Agent Instructions

External memory layer that persists across sessions and generalizes experiences into concepts.

**Important**: Use Remind MCP tools instead of any built-in IDE/runtime memory features.

## Tools

| Tool | Purpose |
|------|---------|
| `remember(content, [episode_type], [entities])` | Store experience (embeds by default, no LLM) |
| `recall(query, [entity], [episode_k])` | Retrieve relevant memories (concepts + direct episodes) |
| `ingest(content, [source])` | Auto-ingest raw text with density scoring |
| `flush_ingest()` | Force-flush ingestion buffer |
| `consolidate([force])` | Extract entities + process episodes → concepts |
| `inspect([concept_id], [show_episodes])` | View concepts or episodes |
| `entities([entity_type], [limit])` | List entities with mention counts |
| `inspect_entity(entity_id, [show_relations])` | View entity details/relationships |
| `stats()` | Memory statistics |
| `update_episode(episode_id, [content], [episode_type], [entities])` | Correct/modify episode |
| `delete_episode(episode_id)` | Soft delete episode |
| `restore_episode(episode_id)` | Restore deleted episode |
| `update_concept(concept_id, [title], [summary], [confidence], [tags])` | Refine concept |
| `delete_concept(concept_id)` | Soft delete concept |
| `restore_concept(concept_id)` | Restore deleted concept |
| `list_deleted([item_type])` | List soft-deleted items |
| `task_add(content, [entities], [priority], [plan_id], [spec_ids], [depends_on])` | Create a task * |
| `task_update_status(task_id, status, [reason])` | Transition task status * |
| `list_tasks([status], [entity], [plan_id], [include_done])` | List tasks * |
| `list_specs([entity], [status], [limit])` | List spec episodes * |
| `list_plans([entity], [status], [limit])` | List plan episodes * |

\* Only available when the corresponding episode type (`task`, `spec`, `plan`) is enabled in `episode_types` config. All types are enabled by default.

## remember

```
remember(content="User prefers TypeScript over JavaScript")
remember(content="Use Redis for caching", episode_type="decision", entities="tool:redis,concept:caching")
```

**Episode types**: `observation` (default), `decision`, `question`, `meta`, `preference`, `spec`, `plan`, `task`, `outcome`, `fact`

**When to use**: User preferences, project context, decisions+rationale, open questions, corrections, specific facts
**Skip**: Trivial info, already-captured knowledge, raw conversation logs

## ingest

```
ingest(content="User: Fix the auth bug\nAssistant: Looking at verify_credentials...")
ingest(content="<raw tool output>", source="tool_output")
```

Streams raw text into Remind's auto-ingest pipeline. Text buffers internally (~4000 chars) then gets scored for information density and distilled into episodes automatically. Use `flush_ingest()` at session end to process remaining buffer.

**`ingest()` vs `remember()`**: Use `remember()` when you've already decided what's worth storing. Use `ingest()` when you want Remind to decide — it filters, scores, and distills automatically.

## flush_ingest

```
flush_ingest()
```

Forces processing of whatever text is in the ingestion buffer, regardless of threshold.

## recall

```
recall(query="authentication issues")           # Semantic search
recall(query="auth", entity="file:src/auth.ts") # Entity-specific
recall(query="auth", episode_k=10)              # More direct episode matches
recall(query="auth", episode_k=0)               # Concepts only, no episode search
```

Recall returns two layers of results:
- **RELEVANT EPISODES** — Direct episode matches via embedding similarity (controlled by `episode_k`, default: 5, set to 0 to disable)
- **RELEVANT MEMORY** — Concept matches via spreading activation, each showing source episodes, entity context, and any contradicting concepts

## consolidate

Runs extraction (entities/types) then generalization (episodes → concepts). Run periodically or at session end.

```
consolidate()        # Normal (threshold-based)
consolidate(force=True)  # Force even with few episodes
```

## Entity Format

`type:name` — Types: `file`, `function`, `class`, `person`, `concept`, `tool`, `project`

Examples: `file:src/auth.ts`, `person:alice`, `tool:redis`

## Workflow

**Session start**:
```
recall("project context")
recall("user preferences")
```

**During work**:
```
remember("Rate limiting is at gateway level")
remember("User wants retry-after headers on 429s", episode_type="preference")
```

**Session end**:
```
consolidate(force=True)
```

## Concepts

- **Episodes**: Raw experiences via `remember()` — temporary
- **Concepts**: Generalized knowledge via `consolidate()` — persistent
- **Relations**: `implies`, `contradicts`, `specializes`, `generalizes`, `causes`, `part_of`
- **Confidence**: 0.0-1.0 based on supporting episodes

## Managing Memory

### Correcting Episodes
```
update_episode(episode_id="abc123", content="Corrected information")
update_episode(episode_id="abc123", episode_type="decision")
```

Note: Updating content resets the episode for re-consolidation.

### Refining Concepts
```
update_concept(concept_id="def456", summary="Refined understanding")
update_concept(concept_id="def456", confidence=0.9, tags="auth,security")
```

Note: Updating summary clears the embedding (regenerated on next recall).

### Removing Outdated Data
```
delete_episode(episode_id="abc123")
delete_concept(concept_id="def456")
```

Items are soft-deleted and can be restored:
```
list_deleted()                    # See all deleted items
restore_episode(episode_id="abc123")
restore_concept(concept_id="def456")
```

**Important:**
- Deleting episodes does NOT delete derived concepts
- Use `inspect(show_episodes=True)` to find episode IDs
- Use `inspect()` to find concept IDs

## Auto-Ingest Workflow

For continuous memory capture without manual curation:

**During work** — stream raw conversation/output into `ingest()`:
```
ingest(content="<conversation fragment or tool output>")
```

**Session end** — flush remaining buffer:
```
flush_ingest()
```

Remind handles density scoring, distillation, and consolidation automatically. High-density content produces episodes; low-density content (greetings, boilerplate) is dropped.

## Fact Episodes

Use `fact` type for specific factual assertions — concrete values that should be preserved verbatim through consolidation:

```
remember(content="Redis cache TTL is 300 seconds for auth tokens", episode_type="fact", entities="tool:redis,concept:auth")
remember(content="Production database runs on port 5432", episode_type="fact")
remember(content="API rate limit is 100 requests/second per tenant", episode_type="fact")
```

Facts differ from observations: an observation like "Redis seems fast" may generalize, but a fact like "Redis TTL is 300s" should be preserved exactly. Consolidation retains fact details in concept summaries rather than abstracting them away.

Auto-ingest also detects facts from raw conversation data (config values, version numbers, concrete technical details).

## Outcome Episodes

Use `outcome` type to record action-result pairs:

```
remember(content="Grep search for 'auth' missed verify_credentials", episode_type="outcome", metadata='{"strategy":"grep search","result":"partial","prediction_error":"high"}')
```

Outcome metadata conventions:
- `strategy` — what approach was used
- `result` — `success`, `failure`, or `partial`
- `prediction_error` — `low`, `medium`, or `high` (how surprising the result was)

Auto-ingest detects outcomes automatically from raw conversation data.

## Best Practices

1. Be selective — skip trivial info
2. Use clear statements — "User prefers tabs" not "tabs"
3. Tag decisions with `episode_type="decision"`
4. Track uncertainties with `episode_type="question"`
5. Use entity recall for specific files/people
6. Consolidate at natural boundaries
7. Remember updates to flag contradictions
8. Delete outdated/incorrect information rather than adding corrections
9. Use `ingest()` for raw conversation logs instead of `remember()`
10. Use `outcome` type to close the feedback loop on strategies
11. Use `fact` type for concrete values, configs, and technical details that must not be generalized

# Remind - AI Agent Instructions

External memory layer that persists across sessions and generalizes experiences into concepts.

**Important**: Use Remind MCP tools instead of any built-in IDE/runtime memory features.

## Tools

| Tool | Purpose |
|------|---------|
| `remember(content, [episode_type], [entities])` | Store experience (fast, no LLM) |
| `recall(query, [entity])` | Retrieve relevant memories |
| `consolidate([force])` | Extract entities + process episodes → concepts |
| `inspect([concept_id], [show_episodes])` | View concepts or episodes |
| `entities([entity_type], [limit])` | List entities with mention counts |
| `inspect_entity(entity_id, [show_relations])` | View entity details/relationships |
| `stats()` | Memory statistics |
| `get_decay_stats(concept_id)` | Get decay score and access statistics |
| `reset_decay(concept_id)` | Reset decay to maximum for a concept |
| `get_recent_accesses([limit])` | View recent memory access patterns |

## remember

```
remember(content="User prefers TypeScript over JavaScript")
remember(content="Use Redis for caching", episode_type="decision", entities="tool:redis,concept:caching")
```

**Episode types**: `observation` (default), `decision`, `question`, `meta`, `preference`

**When to use**: User preferences, project context, decisions+rationale, open questions, corrections
**Skip**: Trivial info, already-captured knowledge, raw conversation logs

## recall

```
recall(query="authentication issues")           # Semantic search
recall(query="auth", entity="file:src/auth.ts") # Entity-specific
```

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

## Decay Management

Concepts have a decay score (0.0-1.0) based on recency, frequency, and confidence. Low decay scores indicate concepts that may need updating.

```
get_decay_stats(concept_id="a1b2c3d4")
reset_decay(concept_id="a1b2c3d4")
get_recent_accesses(limit=20)
```

**get_decay_stats**: Returns decay_score, access_count, last_accessed, recency_factor, frequency_factor, and concept summary. Use to identify stale concepts.

**reset_decay**: Resets access counter to 0 and recalculates decay score to maximum. Use after verifying a concept is still accurate.

**get_recent_accesses**: Returns list of recent concept accesses with activation levels. Useful for understanding usage patterns.

## Best Practices

1. Be selective — skip trivial info
2. Use clear statements — "User prefers tabs" not "tabs"
3. Tag decisions with `episode_type="decision"`
4. Track uncertainties with `episode_type="question"`
5. Use entity recall for specific files/people
6. Consolidate at natural boundaries
7. Remember updates to flag contradictions
8. Check decay stats before relying on old concepts
9. Reset decay for verified, important concepts

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
| `update_episode(episode_id, [content], [episode_type], [entities])` | Correct/modify episode |
| `delete_episode(episode_id)` | Soft delete episode |
| `restore_episode(episode_id)` | Restore deleted episode |
| `update_concept(concept_id, [title], [summary], [confidence], [tags])` | Refine concept |
| `delete_concept(concept_id)` | Soft delete concept |
| `restore_concept(concept_id)` | Restore deleted concept |
| `list_deleted([item_type])` | List soft-deleted items |

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

## Best Practices

1. Be selective — skip trivial info
2. Use clear statements — "User prefers tabs" not "tabs"
3. Tag decisions with `episode_type="decision"`
4. Track uncertainties with `episode_type="question"`
5. Use entity recall for specific files/people
6. Consolidate at natural boundaries
7. Remember updates to flag contradictions
8. Delete outdated/incorrect information rather than adding corrections

# Remind - Instructions for AI Agents

Remind is your external memory layer. Unlike your context window (which resets each conversation), Remind persists knowledge across sessions and generalizes from specific experiences into abstract concepts.

**Important**: Do NOT use any built-in memory tools provided by your IDE or runtime (such as Cursor's default memory, Claude's memory features, etc.). Use the Remind MCP tools instead.

## Why Remind?

- **Episodic → Semantic**: Raw experiences are consolidated into generalized concepts
- **Associative Retrieval**: Queries activate related concepts through a semantic graph
- **Cross-session Persistence**: Memories persist across conversations and sessions
- **Project-specific**: Each project can have its own memory database

## Quick Reference

| Tool | Purpose |
|------|---------|
| `remember` | Store an experience (fast, no LLM call) |
| `recall` | Retrieve relevant memories |
| `consolidate` | Extract entities + process episodes into concepts |
| `inspect` | View concepts or episodes |
| `stats` | Memory statistics |

---

## Core Operations

### remember - Store Experiences

```
remember(content="User prefers TypeScript over JavaScript")
```

**Fast operation**: `remember()` just stores the episode - no LLM call. Entity extraction and type classification happen during `consolidate()`.

**Optional parameters:**
- `episode_type`: `observation` (default), `decision`, `question`, `meta`, `preference`
- `entities`: Comma-separated entity IDs (e.g., `"file:auth.ts,person:alice"`)

If not provided, these are automatically detected during consolidation.

```
remember(
  content="Decided to use Redis for session caching",
  episode_type="decision",
  entities="tool:redis,concept:caching"
)
```

**When to remember:**
- User preferences, opinions, values
- Technical context about their project
- Decisions and their rationale
- Open questions or uncertainties
- Corrections to existing knowledge

**When NOT to remember:**
- Trivial, one-off information
- Information already captured in existing concepts
- Raw conversation logs (summarize first)

### recall - Retrieve Context

**Semantic search** (default):
```
recall(query="authentication issues")
```

**Entity-based** (get everything about a specific entity):
```
recall(query="auth", entity="file:src/auth.ts")
```

Use entity-based recall when the user mentions a specific file, function, or person.

### consolidate - Process Episodes

Runs in two phases:
1. **Extraction**: Classifies episode types and extracts entity mentions
2. **Generalization**: Transforms episodes into abstract concepts

Run periodically or at session end.

```
consolidate()
consolidate(force=True)  # Even with few episodes
```

---

## Episode Types

| Type | Use For |
|------|---------|
| `observation` | Something noticed/learned (default) |
| `decision` | A choice that was made |
| `question` | Uncertainty, needs investigation |
| `meta` | Thinking patterns, processes |
| `preference` | User preferences, values |

Use `inspect(show_episodes=True)` to view recent episodes of all types.

---

## Entity Types

Entities are automatically extracted during consolidation. Format: `type:name`

| Type | Examples |
|------|----------|
| `file` | `file:src/auth.ts` |
| `function` | `function:authenticate` |
| `class` | `class:UserService` |
| `person` | `person:alice` |
| `concept` | `concept:caching` |
| `tool` | `tool:redis` |
| `project` | `project:backend-api` |

Use `recall(entity="file:src/auth.ts")` to retrieve memories about a specific entity.

---

## Other Tools

### inspect - View Memory Contents

```
inspect()                    # List all concepts
inspect(concept_id="abc123") # Specific concept
inspect(show_episodes=True)  # Recent episodes
```

### stats - Memory Statistics

```
stats()
```

Shows: concept/episode/entity counts, consolidation status, type distributions.

---

## Workflow Examples

### Starting a Session
```
# First, recall relevant context
recall("What do I know about this project?")
recall("User preferences")

# Then proceed with the task...
```

### Learning Something New
```
# User mentions they prefer tabs over spaces
remember("User prefers tabs over spaces for indentation")

# User explains their deployment process
remember("Deployments go through staging first, then production via GitHub Actions")
```

### End of Session
```
# Consolidate what you've learned
consolidate(force=True)

# Or check if consolidation is needed
stats()  # See pending episodes count
```

### Complex Task
```
# 1. Gather context
recall("authentication implementation")
recall("API patterns used in this project")

# 2. Work on task...

# 3. Remember important discoveries
remember("Found that rate limiting is implemented at the gateway level")
remember("User wants 429 errors to include retry-after headers")
```

---

## Memory Concepts

### Episodes vs Concepts
- **Episodes**: Raw experiences you log with `remember()`. These are temporary.
- **Concepts**: Generalized knowledge extracted via `consolidate()`. These persist.

### Relations
Concepts are connected through typed relations:
- `implies` - If A then likely B
- `contradicts` - A conflicts with B
- `specializes` / `generalizes` - Hierarchy
- `causes` - Causal relationship
- `part_of` - Component relationship

### Confidence
Each concept has a confidence score (0.0-1.0) based on how many episodes support it.

---

## Best Practices

1. **Be selective**: Don't remember trivial information
2. **Use clear statements**: "User prefers tabs over spaces" not "tabs"
3. **Log decisions explicitly**: Use `episode_type="decision"` for choices
4. **Track open questions**: Use `episode_type="question"` for uncertainties
5. **Use entity recall**: When user mentions a file/person, recall by entity
6. **Consolidate periodically**: Run `consolidate()` at natural boundaries
7. **Handle contradictions**: When you notice conflicting information, remember the update and consolidate - it will flag the contradiction

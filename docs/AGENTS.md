# RealMem - External Memory for AI Agents

This project uses **RealMem** as its persistent memory system. Do NOT use any built-in memory tools provided by your IDE or runtime (such as Cursor's default memory, Claude's memory features, etc.). Use the RealMem MCP tools instead.

## Why RealMem?

RealMem provides **generalization-capable memory** that goes beyond simple storage:

- **Episodic → Semantic**: Raw experiences are consolidated into generalized concepts
- **Associative Retrieval**: Queries activate related concepts through a semantic graph
- **Cross-session Persistence**: Memories persist across conversations and sessions
- **Project-specific**: This database is specific to this project, not shared globally

## Available Tools

### `remember` - Store Important Information
Use this to log experiences and observations that should persist:

```
remember("User prefers functional programming patterns")
remember("The API uses OAuth2 with JWT tokens")
remember("User wants verbose error messages during development")
```

**Fast operation**: `remember()` just stores the episode - no LLM call. Entity extraction and type classification happen during `consolidate()`.

**When to remember:**
- User preferences, opinions, or values
- Technical decisions and constraints
- Project-specific context
- Corrections to previous understanding
- Patterns you observe

**When NOT to remember:**
- Trivial, one-off information
- Information already captured in existing concepts
- Raw conversation logs (summarize first)

### `recall` - Retrieve Relevant Context
Query memory before responding to get relevant context:

```
recall("What are the user's coding preferences?")
recall("What authentication method does this project use?")
recall("What do I know about the database schema?", k=10)
```

**Best practices:**
- Recall before starting complex tasks
- Use specific queries for better results
- Add context parameter when helpful: `recall("languages", context="choosing for new microservice")`

### `consolidate` - Process Episodes into Concepts
Run periodically to transform raw episodes into generalized knowledge.

Consolidation runs in two phases:
1. **Extraction**: Classifies episode types and extracts entity mentions
2. **Generalization**: Creates/updates concepts from patterns across episodes

```
consolidate()           # Normal consolidation (needs 3+ episodes)
consolidate(force=True) # Force with fewer episodes
```

**When to consolidate:**
- After several `remember` calls (5-10)
- At end of conversation/session
- Before reflecting on memory

### `inspect` - Examine Memory Contents
View what's stored in memory:

```
inspect()                          # List all concepts
inspect(concept_id="abc123")       # View specific concept
inspect(show_episodes=True)        # View recent episodes
inspect(limit=20)                  # Show more items
```

### `stats` - Memory Statistics
Get overview of memory state:

```
stats()
```

Shows concept/episode counts, consolidation status, relation distribution.

### `reflect` - Meta-cognitive Analysis
Ask questions about your own memory:

```
reflect("What do I know about this user's preferences?")
reflect("What are the main themes in my memory?")
reflect("Are there any contradictions in what I know?")
reflect("What gaps exist in my understanding?")
```

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

## Memory Concepts

### Episodes vs Concepts
- **Episodes**: Raw experiences you log with `remember()`. These are temporary.
- **Concepts**: Generalized knowledge extracted via `consolidate()`. These persist.

### Relations
Concepts are connected through relations:
- `implies` - If A then likely B
- `contradicts` - A conflicts with B
- `specializes` / `generalizes` - Hierarchy
- `causes` - Causal relationship
- `part_of` - Component relationship

### Confidence
Each concept has a confidence score (0.0-1.0) based on how many episodes support it.

## Important Notes

1. **Be selective**: Don't remember everything. Focus on information that will be useful in future sessions.

2. **Use clear statements**: Write episodes as standalone, clear statements:
   - ✅ "User prefers TypeScript over JavaScript for all new code"
   - ❌ "typescript"

3. **Consolidate regularly**: Run consolidation to transform episodes into searchable concepts.

4. **Handle contradictions**: When you notice conflicting information:
   ```
   remember("User now prefers spaces over tabs (changed from previous preference)")
   consolidate()  # Will flag the contradiction
   ```

5. **Periodic reflection**: Occasionally reflect on memory state:
   ```
   reflect("What important things might I be missing?")
   ```


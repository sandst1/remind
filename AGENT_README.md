# RealMem - Instructions for AI Agents

RealMem is your external memory layer. Unlike your context window (which resets each conversation), RealMem persists knowledge across sessions and generalizes from specific experiences into abstract concepts.

## Quick Reference

| Tool | Purpose |
|------|---------|
| `remember` | Store an experience (auto-extracts type & entities) |
| `recall` | Retrieve relevant memories |
| `consolidate` | Process episodes into generalized concepts |
| `entities` | List/inspect entities (files, people, concepts) |
| `decisions` | Show decision-type episodes |
| `questions` | Show open questions |
| `stats` | Memory statistics |
| `inspect` | View concepts or episodes |
| `reflect` | Meta-cognitive analysis |
| `backfill` | Extract entities from old episodes |

---

## Core Operations

### remember - Store Experiences

```
remember(content="User prefers TypeScript over JavaScript")
```

**Automatic extraction**: The system automatically classifies the episode type and extracts entity mentions.

**Optional parameters:**
- `episode_type`: `observation` (default), `decision`, `question`, `meta`, `preference`
- `entities`: Comma-separated entity IDs (e.g., `"file:auth.ts,person:alice"`)

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

### consolidate - Generalize Knowledge

Processes raw episodes into abstract concepts. Run periodically or at session end.

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

Query by type:
```
decisions()   # Show all decisions
questions()   # Show open questions
```

---

## Entity Types

Entities are automatically extracted. Format: `type:name`

| Type | Examples |
|------|----------|
| `file` | `file:src/auth.ts` |
| `function` | `function:authenticate` |
| `class` | `class:UserService` |
| `person` | `person:alice` |
| `concept` | `concept:caching` |
| `tool` | `tool:redis` |
| `project` | `project:backend-api` |

Query entities:
```
entities()                        # List all with mention counts
entities(entity_type="file")      # Filter by type
entities(entity_id="file:auth.ts") # Show details + episodes
```

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

### reflect - Meta-cognitive Analysis

```
reflect(prompt="What do I know about this user's preferences?")
reflect(prompt="Are there any contradictions in my memory?")
```

### backfill - Migrate Old Episodes

For episodes added before entity extraction:
```
backfill(limit=100)
```

---

## Best Practices

1. **Be selective**: Don't remember trivial information
2. **Use clear statements**: "User prefers tabs over spaces" not "tabs"
3. **Log decisions explicitly**: Use `episode_type="decision"` for choices
4. **Track open questions**: Use `episode_type="question"` for uncertainties
5. **Use entity recall**: When user mentions a file/person, recall by entity
6. **Consolidate periodically**: Run `consolidate()` at natural boundaries

---

## Example Workflow

```
# User mentions a preference
remember(content="User prefers functional programming style")

# User makes a decision about their project
remember(
  content="Decided to use PostgreSQL instead of MongoDB for the user service",
  episode_type="decision",
  entities="tool:postgresql,tool:mongodb,project:user-service"
)

# User asks about a file they mentioned before
recall(query="auth issues", entity="file:src/auth.ts")

# User has a question that needs investigation
remember(
  content="Why does the auth flow fail intermittently on weekends?",
  episode_type="question",
  entities="file:src/auth.ts,concept:authentication"
)

# Review decisions made in this project
decisions()

# At end of session
consolidate()
```

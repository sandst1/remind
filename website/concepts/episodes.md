# Episodes

Episodes are raw experiences — specific interactions, observations, or decisions that your agent stores. They're the input to Remind's memory system.

## Episode types

| Type | Purpose | Example |
|------|---------|---------|
| `observation` | Something noticed or learned (default) | "This project uses a monorepo structure" |
| `decision` | A choice that was made, with rationale | "Chose PostgreSQL: team experience, JSONB support" |
| `question` | An open question or uncertainty | "Should we support offline mode?" |
| `preference` | An opinion, value, or constraint | "User prefers tabs over spaces" |
| `meta` | Reflection about process or thinking | "Auth spec was ambiguous about token refresh" |
| `spec` | A prescriptive requirement | "POST /auth/login must return JWT with 1h expiry" |
| `plan` | A sequenced intention | "Auth plan: 1) bcrypt 2) login route 3) JWT middleware" |
| `task` | A discrete unit of work with status tracking | "Implement bcrypt password hashing utility" |

## Lifecycle

Episodes are **temporary by design**. The lifecycle:

1. **Created** via `remember()` — fast, no LLM calls
2. **Entity extraction** — during consolidation, entities and types are extracted
3. **Consolidated** — episodes are generalized into concepts
4. **Marked consolidated** — the episode is flagged so it isn't processed again

The episode still exists in the database after consolidation, but it's been "digested" into generalized knowledge. You can always inspect the original episodes that contributed to a concept.

### Task lifecycle

Task episodes are special — they have a status lifecycle:

```
todo → in_progress → done
  ↓         ↓
  └──► blocked ──► todo (unblock)
```

Active tasks (todo, in_progress, blocked) are **excluded from consolidation**. They remain as live operational data. Only completed tasks contribute to the generalized knowledge graph.

## Storing episodes

::: code-group

```bash [CLI]
remind remember "User likes Python and Rust"
remind remember "Chose PostgreSQL for the user store" -t decision
remind remember "All API routes need authentication" -t spec -e module:auth
```

```python [Python]
memory.remember("User likes Python and Rust")
memory.remember("Chose PostgreSQL", episode_type=EpisodeType.DECISION)
memory.remember("All API routes need auth", episode_type=EpisodeType.SPEC, entities=["module:auth"])
```

```text [MCP]
remember(content="User likes Python and Rust")
remember(content="Chose PostgreSQL", episode_type="decision")
```

:::

## Entities

Episodes can be tagged with entities to build a navigable knowledge graph. Entities use the format `type:name`:

| Type | Examples |
|------|---------|
| `file` | `file:src/auth.ts`, `file:README.md` |
| `function` | `function:handleLogin` |
| `class` | `class:UserService` |
| `person` | `person:alice` |
| `concept` | `concept:caching` |
| `tool` | `tool:redis`, `tool:postgres` |
| `project` | `project:backend-api` |
| `module` | `module:auth`, `module:billing` |
| `subject` | `subject:login-flow` |

Entities are also extracted automatically during consolidation — you don't always need to tag them manually.

## Managing episodes

```bash
# Update content (resets for re-consolidation)
remind update-episode <id> -c "Corrected information"

# Soft delete (recoverable)
remind delete-episode <id>

# Restore
remind restore-episode <id>

# View deleted items
remind deleted
```

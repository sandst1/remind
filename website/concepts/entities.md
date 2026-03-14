# Entities

Entities are the external referents in Remind's knowledge graph — the files, people, tools, and concepts that episodes mention. They're the nouns that connect everything together.

## Entity ID format

Entities use the format `type:name`:

```
file:src/auth.ts
person:alice
tool:redis
module:auth
concept:caching
```

## Entity types

| Type | Use for | Examples |
|------|---------|---------|
| `file` | Source files | `file:src/routes/auth.ts` |
| `function` | Functions/methods | `function:handleLogin` |
| `class` | Classes | `class:UserService` |
| `person` | People | `person:alice` |
| `concept` | Abstract ideas | `concept:caching`, `concept:rate-limiting` |
| `tool` | Technologies | `tool:redis`, `tool:postgres` |
| `project` | Projects | `project:backend-api` |
| `module` | Architectural boundaries | `module:auth`, `module:billing` |
| `subject` | Functional areas | `subject:login-flow`, `subject:performance` |

## How entities are created

Entities come from two sources:

1. **Manual tagging** — When you store an episode with `-e` flags:
   ```bash
   remind remember "Chose Redis for session storage" -t decision -e tool:redis -e module:auth
   ```

2. **Automatic extraction** — During consolidation, the LLM extracts entity mentions from episode text. "We discussed Alice's auth module using Redis" would extract `person:alice`, `module:auth`, `tool:redis`.

## Entity relationships

When multiple entities appear in the same episode, their relationships are automatically inferred. For example:

> "Alice manages the auth module which uses Redis for sessions"

Produces:
- `person:alice → manages → module:auth`
- `module:auth → uses → tool:redis`

## Querying entities

```bash
# List all entities with mention counts
remind entities

# Details for a specific entity
remind entities file:src/auth.ts

# Episodes mentioning an entity
remind mentions file:src/auth.ts

# Entity relationships
remind entity-relations file:src/auth.ts

# Recall scoped to an entity
remind recall "auth issues" --entity file:src/auth.ts
```

## Entity naming conventions

For building a navigable knowledge graph, consistency matters:

- Use `module:` for architectural boundaries (`module:auth`, not `concept:auth-system`)
- Use `subject:` for cross-cutting concerns (`subject:performance`, `subject:security`)
- Use `tool:` for specific technologies (`tool:redis`, not `concept:redis`)
- Use `file:` with real paths (`file:src/auth.ts`, not `file:auth`)
- Keep names lowercase and kebab-case when possible

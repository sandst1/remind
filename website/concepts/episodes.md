# Episodes

Episodes are raw experiences — specific interactions, observations, or decisions that your agent stores. They're the input to Remind's memory system.

## Episode types

| Type | Purpose | Example |
|------|---------|---------|
| `observation` | Something noticed or learned (default) | "This project uses a monorepo structure" |
| `decision` | A choice that was made, with rationale | "Chose PostgreSQL: team experience, JSONB support" |
| `question` | An open question or uncertainty | "Should we support offline mode?" |
| `preference` | An opinion, value, or constraint | "User prefers tabs over spaces" |
| `meta` | Reflection about process or thinking | "Auth specification was ambiguous about token refresh" |
| `outcome` | Result of an action or strategy | "Grep search for 'auth' missed verify_credentials due to naming" |
| `fact` | Specific factual assertion to preserve verbatim | "Redis cache TTL is 300 seconds for auth tokens" |

You can configure which types are available via the `episode_types` setting. See [Configuration](/guide/configuration#episode-types).

## Lifecycle

Episodes go through these stages:

1. **Created** via `remember()` — fast, with local embeddings by default
2. **Pending** — awaiting agent review
3. **Processed** — agent has either created a concept from it or marked it as reviewed

The agent decides what to do with episodes via `snapshot` (read pending state) and `apply` (create concepts, mark processed).

## Labels

Episodes can be tagged with **labels** — freeform `key=value` pairs that group related memories (e.g., `topic=architecture`, `topic=product`). Labels can be pushed down as a pre-filter into retrieval, reducing noise in large memory graphs. See [Labels](/concepts/labels).

## Provenance

Episodes carry optional provenance: **who** asserted the information and **where** it came from.

| Field | Example | Purpose |
|-------|---------|---------|
| `asserted_by` | `alice`, `agent:cursor` | Who made the assertion |
| `source_ref` | Slack permalink, PR URL | Link back to the original artifact |

```bash
remind remember "Cache TTL is 600 seconds" -t fact \
  --asserted-by alice --source-ref "https://team.slack.com/archives/..."
```

Provenance flows through to fact rows and shows up in recall output. It's what makes [conflict resolution](/concepts/facts-and-conflicts#conflict-lifecycle) decidable — competing claims can be weighed by who said them and when.

## Storing episodes

::: code-group

```bash [CLI]
remind remember "User likes Python and Rust"
remind remember "Chose PostgreSQL for the user store" -t decision
remind remember "All API routes need authentication" -t fact -e module:auth
remind remember "Use event sourcing for audit trail" -l topic=architecture
```

```python [Python]
await memory.remember("User likes Python and Rust")
await memory.remember("Chose PostgreSQL", episode_type=EpisodeType.DECISION)
await memory.remember("All API routes need auth", episode_type=EpisodeType.FACT, entities=["module:auth"])
await memory.remember("Use event sourcing", labels={"topic": "architecture"})
```

```text [MCP]
remember(content="User likes Python and Rust")
remember(content="Chose PostgreSQL", episode_type="decision")
remember(content="Use event sourcing", labels="topic=architecture")
```

:::

For atomic bulk capture, pass a list of item dictionaries to `await memory.remember_batch(items)`. The returned `BatchRememberResult.results` list preserves input order.

## Entities

Episodes can be tagged with entities to build a navigable knowledge graph. Entities use the format `type:name`:

| Type | Examples |
|------|---------|
| `file` | `file:src/auth.ts`, `file:README.md` |
| `function` | `function:handleLogin` |
| `class` | `class:UserService` |
| `person` | `person:alice` |
| `subject` | `subject:caching`, `subject:login-flow` |
| `tool` | `tool:redis`, `tool:postgres` |
| `project` | `project:backend-api` |
| `module` | `module:auth`, `module:billing` |

## Fact episodes

Fact episodes capture specific factual assertions — concrete values, configuration details, names, dates, and technical specifics.

```bash
remind remember "Redis cache TTL is 300 seconds" -t fact -e tool:redis
remind remember "Production database runs on port 5432" -t fact
remind remember "API rate limit is 100 requests/second" -t fact
```

When you store a fact, Remind:
1. Clusters it by entity overlap with existing facts
2. Detects collisions with active facts in the cluster
3. Returns collision info for the agent to handle

See [Fact Pipeline](/concepts/auto-ingest) for details.

## Outcome episodes

Outcome episodes record the result of an action or strategy. They use structured metadata:

| Metadata field | Values | Purpose |
|----------------|--------|---------|
| `strategy` | Free text | What approach was used |
| `result` | `success`, `failure`, `partial` | What happened |
| `prediction_error` | `low`, `medium`, `high` | How surprising the result was |

```bash
remind remember "Grep search missed auth function due to naming" -t outcome \
  -m '{"strategy":"grep search for auth","result":"partial","prediction_error":"high"}'
```

## Managing episodes

```bash
# View pending episodes
remind snapshot pending

# Mark as processed (via apply)
remind apply << 'EOF'
processed ids=ep:11,ep:12
EOF

# Update content
remind update-episode <id> -c "Corrected information"

# Change labels
remind update-episode <id> -l topic=architecture
remind update-episode <id> --clear-labels

# Soft delete (recoverable)
remind delete-episode <id>

# Restore
remind restore-episode <id>

# View deleted items
remind deleted
```

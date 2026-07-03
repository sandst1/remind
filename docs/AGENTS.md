# Remind - AI Agent Instructions

External memory layer that persists across sessions. Agent-driven memory curation via batch tools.

**Important**: Use Remind MCP tools instead of any built-in IDE/runtime memory features.

## Tools

| Tool | Purpose |
|------|---------|
| `remember(content, [episode_type], [entities], [topic], [asserted_by], [source_ref])` | Store experience (embeds immediately, no LLM) |
| `recall(query, [entity], [episode_k], [topic], [as_of])` | Retrieve relevant memories (concepts + direct episodes) |
| `snapshot(scopes)` | Batch read: get current memory state as JSON |
| `apply(changeset, [dry_run])` | Batch write: transactional memory curation |
| `create_topic(name, [description])` | Create a new topic |
| `update_topic(topic_id, [name], [description])` | Update topic name/description |
| `delete_topic(topic_id)` | Delete unused topic |
| `list_topics()` | List all topics with stats |
| `topic_overview(topic, [k])` | Top concepts for a topic (no query needed) |
| `stats()` | Memory statistics |

## remember

```
remember(content="User prefers TypeScript over JavaScript")
remember(content="Use Redis for caching", episode_type="decision", entities="tool:redis,subject:caching")
remember(content="Chose SQLite for zero-dep deploys", topic="architecture")
remember(content="Cache TTL is 300s", episode_type="fact", entities="tool:redis", asserted_by="alice", source_ref="https://github.com/org/repo/pull/42")
```

**Episode types**: `observation` (default), `decision`, `question`, `meta`, `preference`, `outcome`, `fact`

**Topics**: Knowledge areas that group related memories (e.g., `"architecture"`, `"product"`, `"infra"`). Use `list_topics()` to see what exists.

**Provenance**: Use `asserted_by` and `source_ref` to track who stated a fact and where it came from.

**When to use**: User preferences, project context, decisions+rationale, open questions, corrections, specific facts
**Skip**: Trivial info, already-captured knowledge, raw conversation logs

### Fact Episodes

Use `fact` type for specific factual assertions — concrete values that should be preserved verbatim:

```
remember(content="Redis cache TTL is 300 seconds", episode_type="fact", entities="tool:redis")
remember(content="Production database runs on port 5432", episode_type="fact")
remember(content="API rate limit is 100 requests/second", episode_type="fact")
```

Facts are automatically clustered by entity overlap and stored as first-class rows with validity windows. When a new fact overlaps with existing facts, `remember` returns collision information for you to handle via `apply`.

### Collision Handling

When you store a fact that might conflict with existing facts, `remember` returns:
- `fact_id` — the new fact's ID
- `cluster_id` — the fact cluster it was assigned to
- `collisions` — existing active facts with entity overlap

You decide how to handle collisions:
- **Supersede**: Use `apply` with `supersede` op if the new fact replaces an old one
- **Conflict**: Use `apply` with `conflict` op if both facts are valid but contradictory
- **Ignore**: Do nothing if the facts are compatible

## recall

```
recall(query="authentication issues")           # Semantic search
recall(query="auth", entity="file:src/auth.ts") # Entity-specific
recall(query="auth", episode_k=10)              # More direct episode matches
recall(query="auth", episode_k=0)               # Concepts only, no episode search
recall(query="database design", topic="architecture")  # Topic-scoped
recall(query="cache config", as_of="2024-06-01")  # Time-travel: facts as of date
```

Recall returns two layers of results:
- **RELEVANT EPISODES** — Direct episode matches via embedding similarity (controlled by `episode_k`, default: 5, set to 0 to disable)
- **RELEVANT MEMORY** — Concept matches via spreading activation, each showing source episodes, entity context, and conflicts

When `topic` is set, initial matches are filtered to that topic. Cross-topic results can still surface via spreading activation but are penalized.

**Time-travel**: Use `as_of` (ISO date or datetime) to see fact_cluster concepts with the facts that were valid at that point in time, instead of current ones.

## snapshot

Batch read returning current memory state as JSON. Combine scopes in a single call:

```
snapshot(scopes="pending")                    # Unprocessed episodes with entities
snapshot(scopes="conflicts")                  # Open conflicts with fact context
snapshot(scopes="pending,conflicts")          # Both at once
snapshot(scopes="entity:tool:redis")          # All data for an entity
snapshot(scopes="topic:architecture")         # All data for a topic
snapshot(scopes="concept:abc123")             # Concept detail with facts/history
snapshot(scopes="recent:20")                  # 20 most recent episodes
snapshot(scopes="stats")                      # Memory statistics
snapshot(scopes="query:cache config")         # Semantic search (concepts only)
```

**Scopes**:
- `pending` — Episodes not yet processed, with their entities
- `conflicts` — Open conflicts with both facts and provenance
- `entity:<id>` — Entity detail with episodes and fact clusters
- `topic:<id>` — Topic detail with all episodes and concepts
- `concept:<id>` — Concept detail including superseded fact history
- `recent:<n>` — N most recent episodes
- `stats` — Memory statistics
- `query:<text>` — Semantic search for concepts

Use `snapshot` to inspect memory state before curating with `apply`.

## apply

Batch write for transactional memory curation. All-or-nothing; returns per-op results.

### Compact Format (preferred for agents)

One op per line, shlex tokenization, `key=value` args, trailing quoted string = content/note:

```
remember as=f1 t=fact e=tool:redis by=alice "Cache TTL is 600 seconds"
supersede old=fact:a91c2 new=$f1
remember as=o1 t=outcome e=subject:auth "SameSite=Strict broke OAuth; Lax required"
concept as=c1 from=ep:11,ep:12 title="Retry with backoff" "Transient failures resolve with backoff"
resolve id=conflict:7 winner=fact:b3d01 "confirmed by bob"
processed ids=ep:11,ep:12
```

**Ops**:
- `remember` — Store episode (same as tool, but batched)
- `supersede old=<fact_id> new=<fact_id>` — Replace old fact with new
- `conflict fact_a=<id> fact_b=<id> [severity=<high|medium|low>]` — Open a conflict
- `resolve id=<conflict_id> winner=<fact_id> [note]` — Resolve conflict (winner supersedes loser)
- `dismiss id=<conflict_id> [note]` — Dismiss conflict (both facts stay active)
- `concept title=<title> from=<ep_ids> [relations]` — Create concept from episodes
- `update id=<id> [field=value...]` — Update episode/concept fields
- `link source=<concept_id> type=<relation> target=<concept_id>` — Add concept relation
- `topic name=<name> [description]` — Create topic
- `set_topic id=<id> topic=<topic_id>` — Assign topic to episode/concept
- `delete id=<id>` — Soft delete
- `restore id=<id>` — Restore deleted item
- `processed ids=<ep_id,ep_id,...>` — Mark episodes as reviewed

**Local refs**: Use `as=name` to declare, `$name` to reference within the changeset.

**Dry run**: Pass `dry_run=true` to validate without executing.

### JSON Format (programmatic)

```json
[
  {"op": "remember", "as": "f1", "t": "fact", "content": "Cache TTL is 600s",
   "e": ["tool:redis"], "by": "alice"},
  {"op": "supersede", "old": "fact:a91c2", "new": "$f1"},
  {"op": "resolve", "id": "conflict:7", "winner": "fact:b3d01", "note": "confirmed"}
]
```

## Curation Workflow

Memory curation is agent-driven. The typical flow:

**1. Capture during work**:
```
remember(content="Rate limiting is at gateway level", topic="architecture")
remember(content="Max connections is 100", episode_type="fact", entities="tool:postgres")
```

**2. Review pending state**:
```
snapshot(scopes="pending,conflicts")
```

**3. Curate with apply**:
```
apply(changeset="""
concept from=ep:11,ep:12 title="Gateway handles rate limits" "All rate limiting at gateway"
resolve id=conflict:3 winner=fact:abc "newer config value"
processed ids=ep:11,ep:12
""")
```

This replaces the old LLM-based consolidation with explicit agent judgment.

## Topics

Topics are first-class managed entities that group related memories.

```
create_topic(name="Architecture", description="System design decisions")
update_topic(topic_id="architecture", description="Updated description")
delete_topic(topic_id="old-topic")  # Only works if no episodes/concepts use it
list_topics()                       # See all topics with stats
topic_overview(topic="architecture") # Top concepts for a topic
```

Use topics to organize knowledge by domain. Good workflow: `list_topics()` → `topic_overview(topic)` → `recall(query, topic=topic)`

## Entity Format

`type:name` — Types: `file`, `function`, `class`, `person`, `subject`, `tool`, `project`

Examples: `file:src/auth.ts`, `person:alice`, `tool:redis`, `subject:caching`

## Concepts

- **Episodes**: Raw experiences via `remember()` — pending until processed
- **Concepts**: Curated knowledge created via `apply` — persistent
- **Fact clusters**: Groups of related facts (auto-created for `fact` episodes)
- **Relations**: `implies`, `contradicts`, `supersedes`, `specializes`, `generalizes`, `causes`, `part_of`

### Fact Conflicts

When facts contradict (e.g., two different TTL values), conflicts are flagged:

```
snapshot(scopes="conflicts")  # See open conflicts
```

Then resolve via `apply`:
```
resolve id=conflict:7 winner=fact:newer "confirmed in latest config"
```

Or dismiss if both are valid in different contexts:
```
dismiss id=conflict:7 "different environments"
```

## Configuration

### Embedding Provider

Default is local embeddings via `fastembed` (all-MiniLM-L6-v2, 384 dimensions). No API key needed.

For remote embeddings:
- **OpenAI**: Set `OPENAI_API_KEY` and `embedding_provider: "openai"` in config
- **Azure OpenAI**: Set credentials and `embedding_provider: "azure_openai"`
- **Ollama**: Set `embedding_provider: "ollama"` for local Ollama

### Vector Search

Remind uses native vector indexes when available:
- **SQLite**: `sqlite-vec` is included and used automatically
- **PostgreSQL**: Install with `pip install "remind-mcp[postgres]"` for `pgvector`

Fallback: brute-force cosine similarity in Python.

## Best Practices

1. Be selective — skip trivial info
2. Use clear statements — "User prefers tabs" not "tabs"
3. Tag decisions with `episode_type="decision"`
4. Use `fact` type for concrete values that must not be generalized
5. Track provenance with `asserted_by` and `source_ref`
6. Handle collisions from `remember` — don't ignore them
7. Use `snapshot` to inspect before curating
8. Use `apply` for batch curation — it's transactional
9. Mark episodes as `processed` after review
10. Resolve or dismiss conflicts explicitly
11. Assign `topic` to organize knowledge by domain
12. Use time-travel `as_of` to see historical fact states

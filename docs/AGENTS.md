# Remind - AI Agent Instructions

External memory layer that persists across sessions. Agent-driven memory curation via batch tools.

**Important**: Use Remind MCP tools instead of any built-in IDE/runtime memory features.

## Durable workflow contract (0.14)

Local stores use reviewable JSON under `.remind/memory/`; SQLite, embeddings, logs, and usage statistics are disposable local state. Memory follows Git branches and merges with the code. Users control Git; never stage or commit automatically. Explicit SQL URLs still select shared database stores. Stores and labels have no built-in personal/project/topic taxonomy.

Capture and apply are atomic. Use a stable `idempotency_key` when retrying the same logical request; never reuse it for different input. `remember` returns structured IDs, collisions, warnings, and revisions. `remember_batch` returns ordered `results` with the same fact and label semantics.

Before changing an existing record, read its `revision` through `snapshot`. Pass an `expected_revisions` ID-to-revision map to MCP/Python apply, or `--revisions "$REVISIONS"` to CLI apply. In the examples below, set `REVISIONS` to a JSON map from your latest snapshot, such as `'{"<existing-id>":"<revision>"}'`. Individual edit/delete/restore commands require `--expected-revision`. New records referenced within the same changeset need no prior revision. A revision conflict means re-read and reconsider; do not automatically overwrite.

Recall is read-only by default. Python returns `RecallResult` (`.text`, `.concepts`, `.episodes`, `.warnings`, `.explanation`); MCP returns its JSON representation, and CLI uses human-readable text unless `--json` is supplied. Explicit label filters constrain the complete response, including graph expansion, facts, evidence, and conflict context. Separate stores provide isolation; labels remain descriptive tags.

Use `recall --explain --json` to inspect ranking and `doctor` to diagnose integrity, embedding compatibility, and changed sources. Changed/missing sources are annotated, not silently invalidated. Scores are relative ranking signals, not calibrated probabilities or confidence. An empty recall is a valid result.

Use `poll_events(cursor=...)` for reliable change polling. On `reset_required`, restart from the returned cursor. Legacy numeric sequence cursors are local to one projection and are unsafe across checkout or rebuild.


## Tools

| Tool | Purpose |
|------|---------|
| `remember(content, [episode_type], [entities], [labels], [asserted_by], [source_ref])` | Store experience (embeds immediately, no LLM) |
| `recall(query, [entity], [episode_k], [labels], [as_of], [max_chars], [min_score], [timeout_ms])` | Retrieve relevant memories (concepts + direct episodes) |
| `snapshot(scopes)` | Batch read: get current memory state as JSON |
| `apply(changeset, [dry_run], expected_revisions, [idempotency_key])` | Batch write: transactional memory curation |
| `events([since_seq], [limit], [kind])` | Poll the append-only change feed of writes |
| `stats()` | Memory statistics |

## remember

```
remember(content="User prefers TypeScript over JavaScript")
remember(content="Use Redis for caching", episode_type="decision", entities="tool:redis,subject:caching")
remember(content="Chose SQLite for zero-dep deploys", labels="topic=architecture")
remember(content="Cache TTL is 300s", episode_type="fact", entities="tool:redis", asserted_by="alice", source_ref="https://github.com/org/repo/pull/42")
```

**Episode types**: `observation` (default), `decision`, `question`, `meta`, `preference`, `outcome`, `fact`

**Labels**: Freeform `key=value` tags on episodes/concepts, comma-separated (e.g. `"topic=architecture"` or `"topic=architecture,team=infra"`). There's no built-in "topic" concept — `topic` is just a label key you choose to use. Use `snapshot(scopes="labels")` to see what's in use.

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
recall(query="database design", labels="topic=architecture")  # Label-scoped
recall(query="cache config", as_of="2024-06-01")  # Time-travel: facts as of date
recall(query="auth", max_chars=2000)              # Cap output size
recall(query="auth", min_score=0.3, timeout_ms=500)  # Budget controls
```

Recall returns two layers of results:
- **RELEVANT EPISODES** — Direct episode matches via embedding similarity (controlled by `episode_k`, default: 5, set to 0 to disable)
- **RELEVANT MEMORY** — Concept matches via spreading activation, each showing source episodes, entity context, and conflicts

When `labels` is set, initial matches are pre-filtered to items matching ALL given key=value labels before vector search runs. The same constraints apply to graph traversal and rendered facts, evidence, and conflict details.

**Budget controls** (all optional, no-op unless set): `max_chars` caps the formatted output length by dropping the lowest-ranked concepts/episodes whole; `min_score` drops results below an activation floor even if the k/episode_k budget has room left; `timeout_ms` returns the best results gathered so far instead of raising if the deadline is exceeded.

**Time-travel**: Use `as_of` (ISO date or datetime) to see fact_cluster concepts with the facts that were valid at that point in time, instead of current ones.

## snapshot

Batch read returning current memory state as JSON. Combine scopes in a single call:

```
snapshot(scopes="pending")                    # Unprocessed episodes with entities
snapshot(scopes="conflicts")                  # Open conflicts with fact context
snapshot(scopes="pending,conflicts")          # Both at once
snapshot(scopes="health")                     # Actionable issues summary
snapshot(scopes="entity:tool:redis")          # All data for an entity
snapshot(scopes="labels")                     # All distinct labels with counts
snapshot(scopes="label:topic=architecture")   # All data for a label
snapshot(scopes="concept:abc123")             # Concept detail with facts/history
snapshot(scopes="recent:20")                  # 20 most recent episodes
snapshot(scopes="stats")                      # Memory statistics
snapshot(scopes="query:cache config")         # Semantic search (concepts only)
snapshot(scopes="concepts")                   # All concepts (up to 50)
snapshot(scopes="episodes:20")                # Recent 20 episodes
snapshot(scopes="entities")                   # All entities with mention counts
snapshot(scopes="entities:person")            # Filter entities by type
snapshot(scopes="decisions:10")               # Recent 10 decision episodes
snapshot(scopes="questions")                  # Open question episodes
snapshot(scopes="events:42")                  # Change-feed events after seq 42
snapshot(scopes="bootstrap")                  # Query-free stable context (top concepts + conflicts + stats)
```

**Scopes**:
- `pending` — Episodes not yet processed, with their entities
- `conflicts` — Open conflicts with both facts and provenance
- `health` — Actionable memory issues (pending episodes, conflicts, orphans)
- `entity:<id>` — Entity detail with episodes and fact clusters
- `labels` — All distinct key/value labels in use, with counts
- `label:<key>=<value>` — Episodes and concepts carrying this label
- `concept:<id>` — Concept detail including superseded fact history
- `recent:<n>` — N most recent episodes
- `stats` — Memory statistics
- `query:<text>` — Semantic search for concepts
- `concepts[:<n>]` — All concepts (default 50)
- `episodes[:<n>]` — Recent episodes (default 20)
- `entities[:<type>]` — All entities with mention counts, optionally filtered by type
- `decisions[:<n>]` — Recent decision episodes (default 20)
- `questions[:<n>]` — Recent question episodes (default 20)
- `events[:<since_seq>]` — Change-feed events with `seq > since_seq` (default 0). Prefer the dedicated `events` tool below.
- `bootstrap[:<n>]` — Query-free stable context: top-n actionable concepts by confidence and instance count, plus open conflict count and stats (default 10)

Use `snapshot` to inspect memory state before curating with `apply`.

**`bootstrap` at session start**: Unlike `query:<text>`, `bootstrap` needs no embedding call and returns the same result for the same memory state, so it's cheap enough to call at the start of every session (or have an injection layer place it in the system prompt) to ground yourself in what's already known before you `recall` anything specific.

## events

Poll the append-only change feed instead of re-scanning `snapshot(scopes="pending")` on every tick:

```
events()                                       # All events from the start
events(since_seq=42)                           # Only events after seq 42
events(since_seq=42, kind="conflict_opened")   # Filter to one kind
```

Returns `{since_seq, count, events, next_since_seq}`. Every successful `remember` and every successful `apply` op appends a row atomically with the write it describes — `kind` is one of `remembered`, `superseded`, `conflict_opened`, `conflict_resolved`, `conflict_dismissed`, `concept_created`, `updated`, `labeled`, `unlabeled`, `deleted`, `restored`, `processed`. Save `next_since_seq` and pass it as `since_seq` on the next poll.

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
- `label id=<id> key=<key> value=<value>` — Add a key=value label to episode/concept
- `unlabel id=<id> key=<key> value=<value>` — Remove a key=value label from episode/concept
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
remember(content="Rate limiting is at gateway level", labels="topic=architecture")
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

## Labels

Labels are freeform `key=value` tags on episodes and concepts — there's no built-in "topic"
entity to manage. Use whatever keys make sense (`topic`, `team`, `project`, ...) and apply
them consistently.

```
remember(content="...", labels="topic=architecture")     # Set on write
apply(changeset='label id=concept:abc key=topic value=architecture')  # Set after the fact
apply(changeset='unlabel id=concept:abc key=topic value=architecture')  # Remove
snapshot(scopes="labels")                                 # See all labels with counts
snapshot(scopes="label:topic=architecture")               # Browse everything under one
```

Good workflow: `snapshot(scopes="labels")` → `snapshot(scopes="label:topic=architecture")` →
`recall(query, labels="topic=architecture")`. Because labels are pre-filters into vector
search (not post-filters), scoped recall stays precise even as memory grows.

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
11. Apply consistent `labels` (e.g. `topic=...`) to organize knowledge by domain
12. Use time-travel `as_of` to see historical fact states
13. Call `snapshot(scopes="bootstrap")` at session start for cheap, stable grounding before running targeted `recall` queries

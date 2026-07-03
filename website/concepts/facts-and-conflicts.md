# Facts & Conflicts

Facts change over time: the cache TTL gets bumped, a person changes teams, a service moves regions. A memory layer that only appends would either surface stale values or silently lose history. Remind treats facts as **first-class temporal assertions** and disagreements as **explicit conflicts with a lifecycle**.

## Temporal facts

Every `fact` episode that joins a fact cluster becomes a **fact row** with:

| Field | Purpose |
|-------|---------|
| `statement` | The assertion, preserved verbatim |
| `valid_from` / `valid_to` | Validity window. Open-ended (`valid_to = null`) while current. |
| `superseded_by` | Link to the fact that replaced this one |
| `asserted_by` | Who asserted it (e.g. `alice`, `agent:cursor`) |
| `source_ref` | Permalink to the original artifact (Slack message, PR, doc) |
| `source_episode_id` | The episode this fact came from |

Active facts are what recall shows. Superseded facts stay in the database as queryable history — nothing is deleted when knowledge updates.

## Automatic fact clustering

When you store a fact episode, Remind:

1. **Clusters by entity overlap** — Facts are grouped using Jaccard similarity on entity sets. If `|shared entities| / |total entities|` ≥ threshold (default 0.5), the fact joins an existing cluster.
2. **Detects collisions** — Active facts in the cluster with overlapping entities are reported back.
3. **Returns result** — Collision info is returned for the agent to handle.

This is deterministic — no LLM involvement. The agent decides what to do with collisions.

## Handling collisions

When `remember()` returns collisions, the agent decides:

| Action | When to use | `apply` syntax |
|--------|-------------|----------------|
| **Supersede** | New fact replaces old | `supersede old=fact:abc new=$f1` |
| **Conflict** | Genuine contradiction | `conflict fact_a=abc fact_b=def` |
| **Ignore** | Facts are compatible | (no action needed) |

```bash
# Supersede: old fact's validity window closes, links to replacement
remind apply << 'EOF'
supersede old=fact:abc123 new=fact:def456
EOF

# Open a conflict for later triage
remind apply << 'EOF'
conflict fact_a=abc123 fact_b=def456 severity=medium
EOF
```

## As-of recall (time travel)

Ask what was believed at a past point in time:

::: code-group

```bash [CLI]
remind recall --as-of 2024-06-01 "cache configuration"
```

```python [Python]
context = await memory.recall("cache configuration", as_of="2024-06-01")
```

```text [MCP]
recall(query="cache configuration", as_of="2024-06-01")
```

:::

For fact clusters, the output shows the facts whose validity window contained that moment, instead of the current ones. Useful for auditing ("what did we believe when we made that decision?") and debugging stale assumptions.

## Provenance

Facts and episodes carry provenance: **who** asserted the information (`asserted_by`) and **where** it came from (`source_ref`). Recall output includes it inline:

```
- Cache TTL is 600 seconds (alice, since 2024-03-01)
```

Provenance is what makes conflict resolution possible — "alice said X on March 1, the CI config says Y" is decidable; two bare statements are not. Set `--asserted-by` and `--source-ref` whenever information comes from someone or somewhere specific.

## Conflict lifecycle

Conflicts are opened when:
- The agent creates one via `apply` with `conflict` op
- The agent uses `resolve` or `dismiss` via `apply`

Conflicts have a status lifecycle:

```
open ──→ resolved   (one claim wins, the loser is superseded)
    └──→ dismissed  (both claims valid, e.g. different contexts)
```

Conflicts are **flagged, not auto-resolved** — deciding which claim is true is a judgment call that belongs to a human or an agent with context.

### Where conflicts surface

- **Recall output** — an `OPEN CONFLICTS` warning appears when retrieved memory is contested
- **Snapshot** — `snapshot(scopes="conflicts")` returns open conflicts with context
- **Web UI** — a Conflicts inbox with an open-count badge
- **CLI** — `remind conflicts`
- **Stats** — `open_conflicts` count

### Resolving via apply

```bash
remind apply << 'EOF'
resolve id=conflict:7 winner=fact:abc123 "confirmed in prod config"
EOF

remind apply << 'EOF'
dismiss id=conflict:7 "both true: staging vs prod"
EOF
```

### Resolving via CLI

```bash
remind conflicts                          # List open conflicts
remind conflicts resolve <id> <winning_fact_id> \
  --note "confirmed in prod config" --by alice
remind conflicts dismiss <id> --note "both true: staging vs prod"
```

**Resolve** declares a winner: the losing fact is structurally superseded (kept as history, hidden from recall), and the resolution is recorded as a `decision` episode. **Dismiss** keeps both facts active and clears the warning — for cases where both claims are valid in different contexts.

The same operations are available as MCP tools (`resolve_conflict`, `dismiss_conflict`) and REST endpoints.

## Facts vs pattern concepts

Facts and patterns are managed differently:

- **Pattern concepts** ("the team prefers explicit error handling") are created by the agent via `apply`, with confidence scores and relations.
- **Fact clusters** ("TTL is 600s") are created automatically when facts are stored, with verbatim preservation, validity windows, and collision detection.

This is why facts get rows and supersession machinery while patterns get confidence scores and relations.

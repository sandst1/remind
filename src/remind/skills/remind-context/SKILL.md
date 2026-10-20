---
name: remind-context
description: Retrieve context from Remind memory before acting. Use at session start, before answering questions about prior decisions, preferences, or project history, when starting work on a familiar file/area, or when asked "what do we know about X" or "what did we believe at time T".
---

# Remind - Retrieving Context

Query the external memory layer before relying on assumptions. Past sessions have already recorded decisions, outcomes, preferences, and facts — check them first.

**Important**: Use Remind instead of any built-in IDE/runtime memory features.

## Durable workflow contract (0.14)

Local stores use reviewable JSON under `.remind/memory/`; SQLite, embeddings, logs, and usage statistics are disposable local state. Memory follows Git branches and merges with the code. Users control Git; never stage or commit automatically. Explicit SQL URLs still select shared database stores. Stores and labels have no built-in personal/project/topic taxonomy.

Capture and apply are atomic. Use a stable `idempotency_key` when retrying the same logical request; never reuse it for different input. `remember` returns structured IDs, collisions, warnings, and revisions. `remember_batch` returns ordered `results` with the same fact and label semantics.

Before changing an existing record, read its `revision` through `snapshot`. Pass an `expected_revisions` ID-to-revision map to MCP/Python apply, or `--revisions "$REVISIONS"` to CLI apply. In the examples below, set `REVISIONS` to a JSON map from your latest snapshot, such as `'{"<existing-id>":"<revision>"}'`. Individual edit/delete/restore commands require `--expected-revision`. New records referenced within the same changeset need no prior revision. A revision conflict means re-read and reconsider; do not automatically overwrite.

Recall is read-only by default. Python returns `RecallResult` (`.text`, `.concepts`, `.episodes`, `.warnings`, `.explanation`); MCP returns its JSON representation, and CLI uses human-readable text unless `--json` is supplied. Explicit label filters constrain the complete response, including graph expansion, facts, evidence, and conflict context. Separate stores provide isolation; labels remain descriptive tags.

Use `recall --explain --json` to inspect ranking and `doctor` to diagnose integrity, embedding compatibility, and changed sources. Changed/missing sources are annotated, not silently invalidated. Scores are relative ranking signals, not calibrated probabilities or confidence. An empty recall is a valid result.

Use `poll_events(cursor=...)` for reliable change polling. On `reset_required`, restart from the returned cursor. Legacy numeric sequence cursors are local to one projection and are unsafe across checkout or rebuild.

## Session start

```bash
remind recall "project overview" -k 5
remind snapshot stats pending
```

## recall

```bash
remind recall "authentication issues"                  # Semantic search
remind recall "auth" --entity file:src/auth.ts         # Everything about a specific entity
remind recall "database design" -l topic=architecture  # Label-scoped
remind recall "caching" -k 10                          # More results
remind recall --as-of 2026-01-15 "cache configuration" # What we believed then
```

- `--entity type:name` retrieves all memories linked to a file/person/tool — use it when working on a specific file or asking about a specific person.
- `-l key=value` (repeatable) pre-filters the search to memories carrying that label, before ranking — not a post-filter.
- `--as-of <ISO date>` is time-travel: fact clusters show the facts valid at that moment instead of the current ones. Use for "what did we believe / what was the config back then" questions.
- `-k` / `--episode-k` control how many concepts / direct episode matches return.

## Reading recall output

- **RELEVANT EPISODES** — direct episode matches (embedding similarity), with type, date, and provenance (who asserted it).
- **RELEVANT MEMORY** — concept matches via spreading activation. Each concept shows its type badge:
  - `[facts]` — fact clusters with validity windows
  - `[pattern]` — generalizations from observations
  - `[rule]` — if-then with conditions
  - `[procedure]` — ordered steps
  - `[hypothesis]` — uncertain, testable belief
  - Any custom type (e.g., `[strategy]`, `[constraint]`)
- **OPEN CONFLICTS** warning — memory holds contradicting claims about what you retrieved. Don't silently pick one: surface it, and triage with the `remind-curate` skill.

**Evidence-weighted ranking**: Concepts with more supporting evidence rank higher in recall; concepts with contradicting evidence are penalized. A concept's activation score factors in its net evidence strength.

**Semantic collision warnings**: When a new fact is remembered with high semantic similarity to existing facts (not just entity overlap), recall may surface both as potential conflicts.

Trust currently-valid facts over your assumptions; they carry provenance and supersession history.

## Understanding recall output

### RELEVANT EPISODES (similarity score 0.0-1.0)
- Higher score = closer embedding match to your query
- Episodes are raw captures — may contain noise or duplicates
- **Use for**: recent context, exact quotes, provenance checking
- Inspect raw similarity and lexical signals with `--explain`; normalized ranking scores do not have universal relevance thresholds.

### RELEVANT MEMORY (activation score 0.0-1.0)
- Higher score = more relevant via spreading activation through the concept graph
- Concepts are curated knowledge — higher signal than raw episodes
- **Use for**: established patterns, decisions, generalizations

### Concept type badges
- `[facts]` — Fact cluster with temporal validity; check valid_from/valid_to
- `[pattern]` — Generalized observation from multiple episodes
- `[rule]` — If-then relationship with conditions
- `[hypothesis]` — Uncertain belief, testable
- Any other badge — Custom concept type

### When you see OPEN CONFLICTS
Memory contains contradicting claims about the retrieved subject. **Do not silently pick one.**
1. Surface the conflict to the user, OR
2. Run the curation workflow to resolve it:
   - `remind snapshot conflicts` to see details
   - `remind apply --revisions "$REVISIONS" 'resolve id=<conflict_id> winner=<fact_id> note="reason"'`

## snapshot (structured reads)

For machine-readable memory state, use `snapshot` with combinable scopes:

```bash
# Core scopes
remind snapshot stats                         # Memory statistics
remind snapshot pending conflicts             # Pending episodes + open conflicts
remind snapshot health                        # Actionable issues summary

# Browsing scopes (for exploring memory)
remind snapshot concepts                      # All concepts
remind snapshot episodes:20                   # Recent 20 episodes
remind snapshot entities                      # All entities with mention counts
remind snapshot entities:person               # Filter entities by type
remind snapshot labels                        # All distinct labels with counts
remind snapshot decisions:10                  # Recent 10 decision episodes
remind snapshot questions                     # Open question episodes

# Detail scopes
remind snapshot entity:concept:caching        # All data for an entity
remind snapshot label:topic=architecture      # All data for a label
remind snapshot concept:abc123                # Concept detail with facts, history
remind snapshot "query:authentication issues" # Semantic search as JSON
```

`snapshot` returns JSON — ideal for feeding into `apply` changesets or automated processing.

## Browsing (no query yet)

```bash
remind snapshot stats                        # Memory size/health overview
remind snapshot health                       # Actionable issues needing attention
remind snapshot concepts                     # List all concepts
remind snapshot entities                     # Entities available for --entity recall
```

**Explore workflow**: `snapshot stats health` → `recall "<query>"` → `snapshot concept:<id>` for details.

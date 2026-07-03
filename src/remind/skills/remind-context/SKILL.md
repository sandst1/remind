---
name: remind-context
description: Retrieve context from Remind memory before acting. Use at session start, before answering questions about prior decisions, preferences, or project history, when starting work on a familiar file/area, or when asked "what do we know about X" or "what did we believe at time T".
---

# Remind - Retrieving Context

Query the external memory layer before relying on assumptions. Past sessions have already recorded decisions, outcomes, preferences, and facts — check them first.

**Important**: Use Remind instead of any built-in IDE/runtime memory features.

## Session start

```bash
remind recall "project overview" -k 5
remind snapshot stats pending
```

## recall

```bash
remind recall "authentication issues"                  # Semantic search (grouped by topic)
remind recall "auth" --entity file:src/auth.ts         # Everything about a specific entity
remind recall "database design" --topic architecture   # Topic-scoped
remind recall "caching" -k 10                          # More results
remind recall --as-of 2026-01-15 "cache configuration" # What we believed then
```

- `--entity type:name` retrieves all memories linked to a file/person/tool — use it when working on a specific file or asking about a specific person.
- `--topic` restricts to a knowledge area (cross-topic results are penalized, not excluded). Without it, results are grouped by topic.
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

## snapshot (structured reads)

For machine-readable memory state, use `snapshot` with combinable scopes:

```bash
remind snapshot stats                         # Memory statistics
remind snapshot pending conflicts             # Pending episodes + open conflicts
remind snapshot entity:concept:caching        # All data for an entity
remind snapshot topic:architecture            # All data for a topic
remind snapshot concept:abc123                # Concept detail with facts, history
remind snapshot recent:20                     # Recent episodes
remind snapshot "query:authentication issues" # Semantic search as JSON
```

`snapshot` returns JSON — ideal for feeding into `apply` changesets or automated processing.

## Browsing (no query yet)

```bash
remind snapshot stats                        # Memory size/health overview
remind inspect                               # List all concepts
remind inspect <concept_id>                  # Concept detail: facts, history, sources
remind entities                              # Entities available for --entity recall
```

**Explore workflow**: `snapshot stats` → `recall "<query>"` → `snapshot concept:<id>` for details.

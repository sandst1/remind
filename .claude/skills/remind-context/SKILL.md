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
remind topics list
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
- **RELEVANT MEMORY** — concept matches via spreading activation. Fact clusters list currently-valid facts with provenance and since-dates; superseded values are hidden (retrieve history with `--as-of` or `remind inspect <concept_id>`).
- **OPEN CONFLICTS** warning — memory holds contradicting claims about what you retrieved. Don't silently pick one: surface it, and triage with the `remind-curate` skill (`remind conflicts`).

Trust currently-valid facts over your assumptions; they carry provenance and supersession history.

## Browsing (no query yet)

```bash
remind topics list                    # Knowledge areas with counts
remind topics overview architecture   # Top concepts for a topic
remind stats                          # Memory size/health overview
remind inspect                        # List all concepts
remind inspect <concept_id>           # Concept detail: facts, history, sources
remind entities                       # Entities available for --entity recall
remind decisions                      # Decision episodes
remind questions                      # Open questions
```

**Explore workflow**: `topics list` → `topics overview <id>` → `recall "<query>" --topic <id>`.

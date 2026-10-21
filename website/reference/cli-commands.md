# CLI Commands

## Version 0.14 contract

The default store is Git-friendly JSON under the nearest project root's `.remind/memory/`; embeddings and indexes are disposable ignored caches. Use `--store file:///absolute/path` for another directory. Explicit SQL URLs continue to select SQL backends. See [Storage and migration](/concepts/storage).

Reads return full opaque IDs and revision tokens. Existing-record writes require the inspected revision: `--expected-revision` for individual CLI edits, `--revisions '{"full-id":"revision"}'` for CLI apply, `expected_revision`/`expected_revisions` in MCP and Python, and `If-Match` on individual REST edits. Stale edits fail instead of overwriting newer memory. `snapshot deleted` supplies revisions for restore or bulk purge; bulk purge takes an `expected_revisions` map.

Recall is read-only by default. Explicit label filters constrain candidates, graph traversal, facts, and rendered context. Labels are generic tags; separate stores provide isolation. Structured recall includes `text`, `concepts`, `episodes`, `warnings`, and optional `explanation`. Source freshness warnings annotate changed/missing files without changing the remembered claim.

New workflow tools include `remember_batch`, generation-aware `poll_events`, and `doctor`. CLI equivalents are `remember-batch`, `events --cursor`, and `doctor`. REST exposes `POST /api/v1/workflow/{operation}` for `remember`, `remember_batch`, `recall`, `apply`, `snapshot`, `events`, and `doctor`. Use idempotency keys for capture/apply retries. Portable export includes facts, conflicts, evidence, labels, events, and retry receipts; `--mode backup` also includes derived vectors.


The `remind` CLI discovers the nearest project memory directory by default.

## Core commands

### remember

Store an episode.

```bash
remind remember "content"
remind remember "content" -t decision          # Typed
remind remember "content" -e tool:redis        # With entity
remind remember "content" -l topic=architecture
remind remember "Cache TTL is 300s" -t fact -e tool:redis --asserted-by alice
```

| Flag | Description |
|------|-------------|
| `-t, --type` | Episode type: `observation`, `decision`, `question`, `preference`, `meta`, `outcome`, `fact` |
| `-e, --entity` | Entity tag(s) in `type:name` format. Repeat for multiple. |
| `-m, --metadata` | JSON metadata string |
| `-l, --label` | Label(s) as `key=value`. Repeat for multiple. |
| `--asserted-by` | Who asserted this information (provenance) |
| `--source-ref` | Link to the original artifact (URL/permalink) |
| `--no-embed` | Skip embedding (faster). Useful for bulk imports. |

For `fact` episodes, the output includes collision information if there are existing facts with overlapping entities.

### recall

Retrieve relevant memories via spreading activation.

```bash
remind recall "query"
remind recall "query" --entity file:src/auth.ts    # Entity-scoped
remind recall --entity file:src/auth.ts            # Entity-only (no query needed)
remind recall "query" -k 10                        # More results
remind recall "query" --episode-k 10               # More direct episode matches
remind recall "query" --episode-k 0                # Concepts only, no episode search
remind recall "database design" -l topic=architecture # Label-scoped
remind recall --as-of 2024-06-01 "cache configuration" # Time-travel
remind recall "query" --max-chars 2000                 # Cap output size
remind recall "query" --min-score 0.3 --timeout-ms 500 # Budget controls
```

| Flag | Description |
|------|-------------|
| `--entity` | Scope retrieval to an entity (can be used without a query) |
| `-k` | Number of concepts to return (default: 3) |
| `--episode-k, -ek` | Number of episodes via direct vector search (default: 5, 0 to disable) |
| `-l, --label` | Pre-filter to a label as `key=value`. Repeat for multiple. |
| `--as-of` | ISO date/datetime for time-travel (facts valid at that point) |
| `--max-chars` | Cap the formatted output length; drops lowest-ranked items whole to fit |
| `--min-score` | Drop concepts/episodes below this activation score even if k budget remains |
| `--timeout-ms` | Soft deadline; returns best-so-far instead of raising if exceeded |

### snapshot

Batch read returning current memory state as JSON.

```bash
remind snapshot pending                  # Unprocessed episodes
remind snapshot conflicts                # Open conflicts
remind snapshot pending,conflicts        # Both at once
remind snapshot entity:tool:redis        # Entity detail
remind snapshot labels                   # All distinct labels with counts
remind snapshot label:topic=architecture # Label detail
remind snapshot concept:abc123           # Concept detail
remind snapshot recent:20                # Recent episodes
remind snapshot stats                    # Statistics
remind snapshot query:cache              # Semantic search
remind snapshot events:42                # Change-feed events after seq 42
remind snapshot bootstrap                # Query-free stable context
```

`bootstrap[:<n>]` needs no embedding call and returns the same result for the same memory state, so it's cheap enough to call at the start of every session — a good default for grounding before running targeted queries.

| Scope | Description |
|-------|-------------|
| `pending` | Unprocessed episodes with entities |
| `conflicts` | Open conflicts with fact context |
| `entity:<id>` | Entity detail with episodes and fact clusters |
| `labels` | All distinct `key=value` labels in use, with counts |
| `label:<key>=<value>` | All episodes and concepts carrying a label |
| `concept:<id>` | Concept detail with facts and history |
| `recent:<n>` | N most recent episodes |
| `stats` | Memory statistics |
| `query:<text>` | Semantic search for concepts |
| `events[:<since_seq>]` | Change-feed events with `seq > since_seq` (default 0). Prefer `remind events`. |
| `bootstrap[:<n>]` | Query-free stable context: top-n actionable concepts by confidence + open conflicts + stats (default 10) |

### events

Poll the append-only change feed of writes. Use this instead of re-scanning `snapshot pending` to detect new activity.

```bash
remind events                                  # All events from the start
remind events --since 42                       # Only events after seq 42
remind events --kind conflict_opened --since 42 # Filter to one kind
remind events --limit 50 --pretty
```

| Flag | Description |
|------|-------------|
| `--since` | Only return events with `seq` greater than this (default: 0) |
| `--limit` | Maximum number of events to return (default: 200) |
| `--kind` | Filter to a single event kind, e.g. `remembered`, `conflict_opened` |
| `-p, --pretty` | Pretty-print JSON output |

Returns `{since_seq, count, events, next_since_seq}`. `kind` is one of `remembered`, `superseded`, `conflict_opened`, `conflict_resolved`, `conflict_dismissed`, `concept_created`, `updated`, `labeled`, `unlabeled`, `deleted`, `restored`, `processed`. Save `next_since_seq` and pass it as `--since` on the next poll.

### apply

Batch write for transactional memory curation.

```bash
# From stdin
remind apply << 'EOF'
remember as=f1 t=fact e=tool:redis "Cache TTL is 600s"
supersede old=fact:abc123 new=$f1
concept from=ep:11,ep:12 title="Redis config" "TTL-based caching"
processed ids=ep:11,ep:12
EOF

# From file
remind apply -f changeset.txt

# Dry run (validate without executing)
remind apply --dry-run << 'EOF'
remember t=fact "Test fact"
EOF
```

| Flag | Description |
|------|-------------|
| `-f, --file` | Read changeset from file instead of stdin |
| `--dry-run` | Validate without executing |
| `--json` | Output results as JSON |

See [MCP Tools — apply](/reference/mcp-tools#apply) for the full op vocabulary.

## Inspection

### stats

Summary counts, decay settings, embedding provider, and database path.

```bash
remind stats
```

### types

Show which episode types are enabled.

```bash
remind types
```

### status

Show processing status and worker states.

```bash
remind status
```

### search

Search concepts by keyword.

```bash
remind search "keyword"
```

## Conflicts

Triage detected memory conflicts.

```bash
remind conflicts                          # List open conflicts
remind conflicts list --status all        # Include resolved/dismissed
remind conflicts list --kind fact         # Filter by kind

# Resolve: winning fact stays, loser is superseded
remind conflicts resolve <id> <winning_fact_id> --note "confirmed" --by alice

# Dismiss: both valid in different contexts
remind conflicts dismiss <id> --note "staging vs prod"
```

| Subcommand | Flags |
|------------|-------|
| `list` | `--status open\|resolved\|dismissed\|all`, `--kind fact\|concept` |
| `resolve <id> <winning_fact_id>` | `--note`, `--by` |
| `dismiss <id>` | `--note`, `--by` |

## Episode filters

```bash
remind decisions                  # Decision-type episodes
remind questions                  # Question-type episodes
```

## Entity management

```bash
remind entities                           # List all entities
remind entities file:src/auth.ts          # Entity details
remind mentions file:src/auth.ts          # Episodes mentioning entity
remind entity-relations file:src/auth.ts  # Entity relationships
```

## Memory management

```bash
# Update
remind update-episode <id> -c "Corrected content"
remind update-episode <id> -l topic=architecture
remind update-episode <id> --clear-labels
remind update-concept <id> -s "Refined summary" --confidence 0.9
remind update-concept <id> -l topic=product
remind update-concept <id> --clear-labels

# Soft delete (recoverable)
remind delete-episode <id>
remind delete-concept <id>

# View deleted
remind deleted

# Restore
remind restore-episode <id>
remind restore-concept <id>

# Permanent delete
remind purge-episode <id>
remind purge-concept <id>
remind purge-all                      # All soft-deleted items
```

## Embeddings

### re-embed

Re-embed all concepts, episodes, entities, and facts. Useful when switching
embedding providers or dimensions. `--all` is the default and is required when
the embedding dimension changes, so no record type retains vectors from the old
embedding space.

```bash
remind re-embed --all                   # Re-embed every record type
remind re-embed --facts                 # Re-embed facts only (same dimensions only)
remind re-embed --batch-size 100        # Larger batches
```

### clear-embeddings

Clear all embeddings, including fact embeddings (requires re-embed after).

```bash
remind clear-embeddings --yes
```

## Export / Import

```bash
remind export backup.json
remind import backup.json
```

## Web UI

```bash
remind ui                    # Open with project database
remind ui --port 9000        # Custom port
remind ui --no-open          # Start server only
```

## Skills

```bash
remind skill-install                                  # All skills to .agents/skills/
remind skill-install remind-capture                   # Install a specific skill
remind skill-install --agent claude                   # Use .claude/skills/
remind skill-install --agent cursor --dir /my/project # Choose a project folder
remind skill-install --agent codex --dir ~            # Install to ~/.agents/skills/
remind skill-install --agent opencode --dir ~         # Install to ~/.config/opencode/skills/
```

Installs `remind-capture`, `remind-context`, and `remind-curate`. `--agent` accepts
`agents` (default), `claude`, `cursor`, `codex`, and `opencode`. `--dir` (aliases:
`--directory`, `-d`) selects the base folder and defaults to the current working
directory. Existing skill files are overwritten. See [Skills + CLI](/guide/skills).

## Global flags

| Flag | Description |
|------|-------------|
| `--db NAME` | Use `~/.remind/NAME.db` instead of project-local |
| `--embedding PROVIDER` | Override embedding provider |
| `--version` | Show version |

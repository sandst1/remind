# CLI Commands

The `remind` CLI is project-aware by default. Without `--db`, it uses `<cwd>/.remind/remind.db`.

## Core commands

### remember

Store an episode.

```bash
remind remember "content"
remind remember "content" -t decision          # Typed
remind remember "content" -e tool:redis        # With entity
remind remember "content" --topic architecture
remind remember "Cache TTL is 300s" -t fact -e tool:redis --asserted-by alice
```

| Flag | Description |
|------|-------------|
| `-t, --type` | Episode type: `observation`, `decision`, `question`, `preference`, `meta`, `outcome`, `fact` |
| `-e, --entity` | Entity tag(s) in `type:name` format. Repeat for multiple. |
| `-m, --metadata` | JSON metadata string |
| `--topic` | Knowledge area (e.g., `architecture`, `product`) |
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
remind recall "database design" --topic architecture  # Topic-scoped
remind recall --as-of 2024-06-01 "cache configuration" # Time-travel
```

| Flag | Description |
|------|-------------|
| `--entity` | Scope retrieval to an entity (can be used without a query) |
| `-k` | Number of concepts to return (default: 3) |
| `--episode-k, -ek` | Number of episodes via direct vector search (default: 5, 0 to disable) |
| `--topic` | Filter to a knowledge area |
| `--as-of` | ISO date/datetime for time-travel (facts valid at that point) |

### snapshot

Batch read returning current memory state as JSON.

```bash
remind snapshot pending                  # Unprocessed episodes
remind snapshot conflicts                # Open conflicts
remind snapshot pending,conflicts        # Both at once
remind snapshot entity:tool:redis        # Entity detail
remind snapshot topic:architecture       # Topic detail
remind snapshot concept:abc123           # Concept detail
remind snapshot recent:20                # Recent episodes
remind snapshot stats                    # Statistics
remind snapshot query:cache              # Semantic search
```

| Scope | Description |
|-------|-------------|
| `pending` | Unprocessed episodes with entities |
| `conflicts` | Open conflicts with fact context |
| `entity:<id>` | Entity detail with episodes and fact clusters |
| `topic:<id>` | Topic detail with episodes and concepts |
| `concept:<id>` | Concept detail with facts and history |
| `recent:<n>` | N most recent episodes |
| `stats` | Memory statistics |
| `query:<text>` | Semantic search for concepts |

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

## Topic management

```bash
remind topics list               # List all topics with stats
remind topics overview <name>    # Top concepts for a topic
remind topics overview <name> -k 10   # More results
```

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
remind update-episode <id> --topic architecture
remind update-episode <id> --clear-topic
remind update-concept <id> -s "Refined summary" --confidence 0.9
remind update-concept <id> --topic product
remind update-concept <id> --clear-topic

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

Re-embed all concepts, episodes, and entities. Useful when switching embedding providers or dimensions.

```bash
remind re-embed --all                   # Re-embed everything
remind re-embed --batch-size 100        # Larger batches
```

### clear-embeddings

Clear all embeddings (requires re-embed after).

```bash
remind clear-embeddings
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
remind skill-install                 # Install all bundled skills to .claude/skills/
remind skill-install remind-capture  # Install a specific skill
```

Installs `remind-capture`, `remind-context`, and `remind-curate`. See [Skills + CLI](/guide/skills).

## Global flags

| Flag | Description |
|------|-------------|
| `--db NAME` | Use `~/.remind/NAME.db` instead of project-local |
| `--embedding PROVIDER` | Override embedding provider |
| `--version` | Show version |

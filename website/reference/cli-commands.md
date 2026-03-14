# CLI Commands

The `remind` CLI is project-aware by default. Without `--db`, it uses `<cwd>/.remind/remind.db`.

## Core commands

### remember

Store an episode.

```bash
remind remember "content"
remind remember "content" -t decision          # Typed
remind remember "content" -e tool:redis        # With entity
remind remember "content" -t spec -e module:auth -m '{"status":"approved"}'
```

| Flag | Description |
|------|-------------|
| `-t, --type` | Episode type: `observation`, `decision`, `question`, `preference`, `meta`, `spec`, `plan`, `task` |
| `-e, --entity` | Entity tag(s) in `type:name` format. Repeat for multiple. |
| `-m, --metadata` | JSON metadata string |

### recall

Retrieve relevant memories via spreading activation.

```bash
remind recall "query"
remind recall "query" --entity file:src/auth.ts    # Entity-scoped
remind recall "query" -k 10                        # More results
```

| Flag | Description |
|------|-------------|
| `--entity` | Scope retrieval to an entity |
| `-k` | Number of results (default: 5) |

### consolidate

Process episodes into concepts.

```bash
remind consolidate            # Threshold-based
remind consolidate --force    # Force even with few episodes
```

### end-session

Consolidate pending episodes and clean up. Recommended at the end of every session.

```bash
remind end-session
```

## Inspection

### inspect

View concepts or episodes.

```bash
remind inspect                    # List all concepts
remind inspect <concept-id>       # Concept details
```

### stats

Memory statistics: episode count, concept count, entity count, decay status.

```bash
remind stats
```

### search

Search concepts by keyword.

```bash
remind search "keyword"
```

## Episode filters

```bash
remind decisions                  # Decision-type episodes
remind questions                  # Question-type episodes
remind specs                      # Spec episodes
remind plans                      # Plan episodes
```

## Entity management

```bash
remind entities                           # List all entities
remind entities file:src/auth.ts          # Entity details
remind mentions file:src/auth.ts          # Episodes mentioning entity
remind entity-relations file:src/auth.ts  # Entity relationships
remind extract-relations                  # Extract from unprocessed episodes
remind extract-relations --force          # Re-extract all
```

## Task management

```bash
remind tasks                          # Active tasks
remind tasks --status todo            # Filter by status
remind tasks --entity module:auth     # Filter by entity
remind tasks --all                    # Include completed

remind task add "description" -e module:auth --priority p0
remind task add "description" --depends-on <id> --plan <id> --spec <id>
remind task start <id>                # → in_progress
remind task done <id>                 # → done
remind task block <id> "reason"       # → blocked
remind task unblock <id>              # → todo
```

## Memory management

```bash
# Update
remind update-episode <id> -c "Corrected content"
remind update-concept <id> -s "Refined summary" --confidence 0.9

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

## Skill installation

```bash
remind skill-install          # Install base skill to .claude/skills/remind/
```

## Global flags

| Flag | Description |
|------|-------------|
| `--db NAME` | Use `~/.remind/NAME.db` instead of project-local |
| `--llm PROVIDER` | Override LLM provider |
| `--embedding PROVIDER` | Override embedding provider |
| `--version` | Show version |

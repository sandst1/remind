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
remind remember "content" --topic architecture --source-type agent
```

| Flag | Description |
|------|-------------|
| `-t, --type` | Episode type: `observation`, `decision`, `question`, `preference`, `meta`, `spec`, `plan`, `task`, `outcome`, `fact` |
| `-e, --entity` | Entity tag(s) in `type:name` format. Repeat for multiple. |
| `-m, --metadata` | JSON metadata string |
| `--topic` | Knowledge area (e.g., `architecture`, `product`). Scopes consolidation and retrieval. |
| `--source-type` | Origin of the memory (e.g., `agent`, `slack`, `manual`). |
| `--no-embed` | Skip embedding the episode (faster, no API call). Useful for bulk imports. |

### ingest

Auto-ingest raw text: the triage LLM extracts memory-worthy episodes (and may assign topics). Text buffers internally until the character threshold is reached, then flushes to triage.

```bash
remind ingest "User said they prefer dark mode and Vim keybindings"
remind ingest "Rate limiting at gateway" --topic architecture
echo "conversation log" | remind ingest
cat transcript.txt | remind ingest --source transcript
cat meeting.txt | remind ingest -i "extract decisions and action items"
```

| Flag | Description |
|------|-------------|
| `-s, --source` | Source label for metadata (default: `conversation`) |
| `--topic` | Topic ID or name. When set, all extracted episodes go to this topic. When omitted, topics are inferred by the triage LLM. |
| `-i, --instructions` | Natural-language instructions to steer what gets extracted (e.g. `"focus on decisions"`). Appended to the triage system prompt. |
| `-f, --foreground` | Run triage and consolidation in foreground (blocking). By default, processing is spawned in a background worker. |

Accepts text as an argument or via stdin (for piping).

### flush-ingest

Force-flush the ingestion buffer, processing whatever has accumulated.

```bash
remind flush-ingest
```

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
```

| Flag | Description |
|------|-------------|
| `--entity` | Scope retrieval to an entity (can be used without a query) |
| `-k` | Number of concepts to return (default: 3) |
| `--episode-k, -ek` | Number of episodes to retrieve via direct vector search (default: 5). Set to 0 to disable. |
| `--topic` | Filter to a knowledge area. Cross-topic concepts may still surface via spreading activation but are penalized. |

### consolidate

Process episodes into concepts.

```bash
remind consolidate            # Threshold-based
remind consolidate --force    # Force even with few episodes
```

### end-session

Flush the ingestion buffer, then consolidate pending episodes in the background. Recommended at the end of every session.

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

Summary counts (concepts, episodes, relations, entities, mentions), consolidation status (pending and unextracted episodes, threshold, auto-consolidate, last run), **episode types** and **entity types** (per-type counts), **relation distribution**, configured LLM and embedding providers, decay settings and stats, and the **database** path in use.

```bash
remind stats
```

### types

Show which episode types are enabled for this environment (from env vars, project config, global config, or defaults). Useful when you have restricted `episode_types` and want to confirm what the CLI and consolidation will accept.

```bash
remind types
```

### status

Show processing status: running workers, pending episodes, queued ingest chunks.

```bash
remind status
```

### search

Search concepts by keyword.

```bash
remind search "keyword"
```

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
remind specs                      # Spec episodes
remind plans                      # Plan episodes
```

::: tip Conditional commands
`specs` and `plans` only appear when the `spec` and `plan` episode types are enabled in your [configuration](/guide/configuration#episode-types). All types are enabled by default.
:::

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

::: tip Conditional commands
Task commands only appear when the `task` episode type is enabled in your [configuration](/guide/configuration#episode-types). All types are enabled by default.
:::

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

## Embeddings

### embed-episodes

Backfill embeddings for episodes that don't have them yet. Useful after upgrading from a version that didn't embed episodes, or after bulk-importing with `--no-embed`.

```bash
remind embed-episodes                    # Default batch size (50)
remind embed-episodes --batch-size 100   # Larger batches
```

| Flag | Description |
|------|-------------|
| `--batch-size` | Number of episodes to embed per batch (default: 50) |

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

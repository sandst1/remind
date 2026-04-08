# Remind - External Memory

External memory layer that persists across sessions and generalizes experiences into concepts.

**Important**: Use Remind as your default memory layer instead of any built-in IDE/runtime memory features.

## Commands

| Command | Purpose |
|---------|---------|
| `remind remember "<content>"` | Store experience (fast, no LLM) |
| `remind recall "<query>"` | Retrieve relevant memories |
| `remind end-session` | Consolidate pending episodes |
| `remind stats` | Memory statistics |
| `remind types` | Show configured episode types |
| `remind topics list` | List all topics with stats |
| `remind topics create <name>` | Create a new topic |
| `remind topics update <id>` | Update topic name/description |
| `remind topics delete <id>` | Delete unused topic |
| `remind topics overview <id>` | Top concepts for a topic |
| `remind decisions` | Show decision episodes |
| `remind questions` | Show open questions |
| `remind update-episode <id> ...` | Correct episode (`-c`, `--topic`, `--clear-topic`, etc.) |
| `remind update-concept <id> ...` | Refine concept (`-s`, `--topic`, `--clear-topic`, etc.) |
| `remind delete-episode <id>` | Soft delete episode |
| `remind delete-concept <id>` | Soft delete concept |
| `remind restore-episode <id>` | Restore deleted episode |
| `remind restore-concept <id>` | Restore deleted concept |
| `remind deleted` | List soft-deleted items |

## remember

```bash
remind remember "User prefers TypeScript over JavaScript"
remind remember "Use Redis for caching" -t decision -e tool:redis -e concept:caching
remind remember "Rate limiting is at gateway level" --topic architecture
remind remember "User wants retry-after headers on 429s" -t preference --topic product
remind remember "Slack message: deploy failed on prod" --source-type slack --topic infra
```

**Episode types** (`-t`): Configurable via config. Run `remind types` to see active types. Defaults: `observation`, `decision`, `question`, `meta`, `preference`, `outcome`, `fact`, `spec`, `plan`, `task`
**Entities** (`-e`): Format `type:name` (file, function, class, person, concept, tool, project)
**Topics** (`--topic`): Topic ID or name. Resolved to an existing topic; falls back to "general" default.
**Source types** (`--source-type`): Origin of the memory (e.g., `agent`, `slack`, `github`, `manual`)

**When to use**: User preferences, project context, decisions+rationale, open questions, corrections, facts
**Skip**: Trivial info, already-captured knowledge, raw conversation logs

## recall

```bash
remind recall "authentication issues"              # Semantic search (grouped by topic)
remind recall "auth" --entity file:src/auth.ts     # Entity-specific
remind recall "caching" -k 10                      # More results
remind recall "database design" --topic architecture  # Topic-scoped
```

Recall returns two layers:
- **RELEVANT EPISODES** — Direct episode matches via embedding similarity
- **RELEVANT MEMORY** — Concept matches via spreading activation, with entity context and contradicting/superseding concepts

Without `--topic`, results are grouped by topic showing top N per topic. With `--topic`, results are filtered to that topic only (cross-topic results can still surface via spreading activation but are penalized).

## Topics

Topics are first-class managed entities that group related memories. Each topic has an ID (slug), display name, and description.

```bash
remind topics create "Architecture" -d "System design decisions and patterns"
remind topics create "Product"
remind topics update architecture -n "System Architecture" -d "Updated description"
remind topics delete old-topic          # Only works if no episodes/concepts use it
remind topics list                      # See all topics with stats
remind topics overview architecture     # Top concepts for a topic
remind topics overview product -k 10    # More results
```

When using `--topic` with `remember`, the topic is resolved by ID or name. If no match, the memory goes to the "general" default topic.

**Workflow**: `remind topics list` → `remind topics overview <id>` → `remind recall "<query>" --topic <id>`

To **move** an existing episode or concept to another topic (or remove its topic), use `remind update-episode <id> --topic <id-or-name>` or `remind update-concept <id> --topic <id-or-name>`. Use `--clear-topic` to unset `topic_id` on that record.

## Workflow

**Session start**: Recall project context and user preferences
```bash
remind recall "project overview" -k 5
remind topics list
```

**During work**: Remember important observations, decisions, preferences — tag with topic when relevant
```bash
remind remember "Chose Postgres over MySQL: team familiarity + JSONB support" -t decision --topic architecture -e tool:postgres
remind remember "Should we shard the DB early or wait for scale?" -t question --topic architecture
```

**Session end**: Run `remind end-session`

## Additional Commands

```bash
remind stats                    # Memory statistics
remind types                    # Show configured episode types
remind inspect                  # List all concepts
remind inspect <concept_id>     # Concept details
remind entities                 # List entities
remind decisions                # Show decision episodes
remind questions                # Show open questions
```

## Managing Memory

### Correcting Content
```bash
remind update-episode <id> -c "Corrected information"
remind update-concept <id> -s "Refined summary" --confidence 0.9
remind update-episode <id> --topic architecture
remind update-concept <id> --topic product
remind update-episode <id> --clear-topic
```

**Note**: Updating episode content resets it for re-consolidation.

### Deleting Outdated Data
```bash
remind delete-episode <id>        # Soft delete (recoverable)
remind delete-concept <id>        # Soft delete (recoverable)
remind deleted                    # View deleted items
remind restore-episode <id>       # Restore if needed
remind restore-concept <id>       # Restore if needed
```

**When to delete**: Outdated info, incorrect memories, superseded decisions
**Tip**: Delete rather than adding corrections — cleaner than contradictions

## Best Practices

1. Be selective — skip trivial info
2. Use clear statements — "User prefers tabs" not "tabs"
3. Tag decisions with `-t decision`
4. Track uncertainties with `-t question`
5. Create topics with `topics create` to organize knowledge by domain
6. Use entity recall (`--entity`) for specific files/people/modules
7. Run `remind end-session` at natural boundaries
8. Delete outdated info rather than adding corrections
9. Use `topics list` + `topics overview` to explore before targeted recall
10. Use `--source-type` when origin matters (slack, github, manual)
11. Reclassify misplaced items with `update-episode` / `update-concept` and `--topic` (or `--clear-topic`)

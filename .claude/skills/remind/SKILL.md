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
| `remind topics list` | List all topics with stats |
| `remind topics overview <name>` | Top concepts for a topic |
| `remind decisions` | Show decision episodes |
| `remind questions` | Show open questions |
| `remind update-episode <id> -c "<content>"` | Correct episode content |
| `remind update-concept <id> -s "<summary>"` | Refine concept |
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

**Episode types** (`-t`): `observation` (default), `decision`, `question`, `meta`, `preference`, `outcome`, `fact`
**Entities** (`-e`): Format `type:name` (file, function, class, person, concept, tool, project)
**Topics** (`--topic`): Knowledge area grouping (e.g., `architecture`, `product`, `infra`, `security`)
**Source types** (`--source-type`): Origin of the memory (e.g., `agent`, `slack`, `github`, `manual`)

**When to use**: User preferences, project context, decisions+rationale, open questions, corrections, facts
**Skip**: Trivial info, already-captured knowledge, raw conversation logs

## recall

```bash
remind recall "authentication issues"              # Semantic search
remind recall "auth" --entity file:src/auth.ts     # Entity-specific
remind recall "caching" -k 10                      # More results
remind recall "database design" --topic architecture  # Topic-scoped
```

Recall returns two layers:
- **RELEVANT EPISODES** — Direct episode matches via embedding similarity
- **RELEVANT MEMORY** — Concept matches via spreading activation, with entity context and contradicting/superseding concepts

When `--topic` is set, initial matches are filtered to that topic. Cross-topic results can still surface via spreading activation but are penalized.

## Topics

Topics organize memory into knowledge areas. Use them to scope retrieval and reduce noise.

```bash
remind topics list                        # See all topics with stats
remind topics overview architecture       # Top concepts for a topic
remind topics overview product -k 10      # More results
```

**Workflow**: `remind topics list` → `remind topics overview <name>` → `remind recall "<query>" --topic <name>`

Good topics: `architecture`, `product`, `infra`, `security`, `testing`, `ux`, `data`

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
5. Use `--topic` to group knowledge by domain
6. Use entity recall (`--entity`) for specific files/people/modules
7. Run `remind end-session` at natural boundaries
8. Delete outdated info rather than adding corrections
9. Use `topics list` + `topics overview` to explore before targeted recall
10. Use `--source-type` when origin matters (slack, github, manual)

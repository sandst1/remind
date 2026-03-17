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
| `remind tasks` | List active tasks |
| `remind specs` | List specs |
| `remind plans` | List plans |
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
remind remember "POST /auth/login must return JWT with 1h expiry" -t spec -e module:auth
remind remember "Auth plan: 1) bcrypt 2) login route 3) JWT middleware" -t plan -e module:auth
```

**Episode types** (`-t`): observation (default), decision, question, meta, preference, spec, plan, task
**Entities** (`-e`): Format `type:name` (file, function, class, person, concept, tool, project)

**When to use**: User preferences, project context, decisions+rationale, open questions, corrections, specs, plans
**Skip**: Trivial info, already-captured knowledge, raw conversation logs

## recall

```bash
remind recall "authentication issues"              # Semantic search
remind recall "auth" --entity file:src/auth.ts     # Entity-specific
remind recall "caching" -k 10                      # More results
```

## Tasks

Tasks are work items with status tracking. Use `remind task` subcommands to manage:

```bash
remind task add "Implement bcrypt hashing" -e module:auth --priority p0
remind task add "Write auth tests" --depends-on <task-id>
remind task update <id> --plan <plan-id> --spec <spec-id>   # Link to plan/spec after creation
remind task update <id> --priority p0 --depends-on <task-id>
remind task start <id>              # todo -> in_progress
remind task done <id>               # -> done
remind task block <id> "reason"     # -> blocked
remind task unblock <id>            # blocked -> todo
remind tasks                        # List active tasks
remind tasks --status todo          # Filter by status
remind tasks --entity module:auth   # Filter by entity
remind tasks --all                  # Include completed
```

Active tasks are excluded from consolidation. Completed tasks consolidate normally.

## Workflow

**Session start**: Recall project context and user preferences
**During work**: Remember important observations, decisions, preferences
**Session end**: Run `remind end-session`

## Additional Commands

```bash
remind stats                    # Memory statistics
remind inspect                  # List all concepts
remind inspect <concept_id>     # Concept details
remind entities                 # List entities
remind decisions                # Show decision episodes
remind questions                # Show open questions
remind specs                    # Show spec episodes
remind plans                    # Show plan episodes
```

## Managing Memory

### Correcting Content
```bash
remind update-episode <id> -c "Corrected information"
remind update-concept <id> -s "Refined summary" --confidence 0.9
```

**Note**: Updating episode content resets it for re-consolidation.

### Linking Tasks to Plans and Specs
```bash
remind task update <id> --plan <plan-id>
remind task update <id> --spec <spec-id> --spec <spec-id-2>
remind task update <id> --plan <plan-id> --spec <spec-id> --priority p0

# update-episode works too (for any episode type)
remind update-episode <id> --plan <plan-id> --spec <spec-id>
remind update-episode <id> --depends-on <task-id> --priority p1
```

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
5. Use `-t spec` for prescriptive requirements
6. Use `-t plan` for implementation plans
7. Use entity recall for specific files/people
8. Run `remind end-session` at natural boundaries
9. Delete outdated info rather than adding corrections

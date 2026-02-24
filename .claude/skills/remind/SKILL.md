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

## remember

```bash
remind remember "User prefers TypeScript over JavaScript"
remind remember "Use Redis for caching" -t decision -e tool:redis -e concept:caching
```

**Episode types** (`-t`): observation (default), decision, question, meta, preference
**Entities** (`-e`): Format `type:name` (file, function, class, person, concept, tool, project)

**When to use**: User preferences, project context, decisions+rationale, open questions, corrections
**Skip**: Trivial info, already-captured knowledge, raw conversation logs

## recall

```bash
remind recall "authentication issues"              # Semantic search
remind recall "auth" --entity file:src/auth.ts     # Entity-specific
remind recall "caching" -k 10                      # More results
```

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
```

## Best Practices

1. Be selective — skip trivial info
2. Use clear statements — "User prefers tabs" not "tabs"
3. Tag decisions with `-t decision`
4. Track uncertainties with `-t question`
5. Use entity recall for specific files/people
6. Run `remind end-session` at natural boundaries

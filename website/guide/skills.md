# Skills + CLI

Skills are the recommended way to integrate Remind into your workflow. A skill is just a markdown file with instructions that tell an AI agent how to use Remind via the CLI. Any agent that can run shell commands can use them — Claude Code, Cursor, Windsurf, or your own custom setup.

## Why Skills?

Skills + CLI give you:

- **Project-local memory** — The database lives at `.remind/remind.db` in your project. Each project has its own isolated memory. You can gitignore it or commit it.
- **No server needed** — No MCP server to run. The CLI is self-contained.
- **Composable** — Skills are just markdown. Extend the bundled skills, write your own, or fork them for custom workflows.
- **Agent-agnostic** — Any agent that can run shell commands can use Remind skills.

## Installing the bundled skills

```bash
remind skill-install
```

This creates `.claude/skills/<name>/SKILL.md` files in your project. You can also install a subset: `remind skill-install remind-capture`.

## The bundled skills

Remind ships three skills, each with its own behavioral trigger:

| Skill | Triggers when... | Teaches |
|-------|------------------|---------|
| **`remind-capture`** | A decision is made, an approach succeeds/fails, the user states a preference or corrects the agent, a concrete fact surfaces | What to remember: episode types (outcomes are highest-value), entities, topics, provenance, handling fact collisions |
| **`remind-context`** | Session start, questions about prior decisions/preferences/history, starting work on a familiar area | How to recall: semantic, entity, topic-scoped, and `--as-of` time-travel queries; reading output including `OPEN CONFLICTS` warning |
| **`remind-curate`** | Recall warns about conflicts, stored info is corrected or outdated, topics need reorganizing | Using `snapshot` and `apply` for batch curation: conflict resolution, supersession, concept creation |

Example workflow:

```bash
# Capture a decision with entities
remind remember "Chose WebSocket over polling: lower latency" \
  -t decision -e module:notifications -e tool:websocket

# Capture a fact with provenance
remind remember "WS endpoint at /ws/notifications: JWT auth" \
  -t fact -e module:notifications --asserted-by alice

# Recall what we know
remind recall "notifications WebSocket" -k 10

# Review pending state
remind snapshot pending,conflicts

# Curate with apply
remind apply << 'EOF'
concept from=ep:11,ep:12 title="WebSocket notifications" "Real-time via WS"
processed ids=ep:11,ep:12
EOF
```

## Writing your own skills

A skill is a markdown file that instructs an agent how to use Remind for a specific workflow.

### Skill structure

A minimal skill file (save as `.claude/skills/<name>/SKILL.md`):

```markdown
# My Custom Skill

> **Important**: The `remind` CLI tool is available in this environment.

## When to use
Describe when this skill should be activated.

## Workflow

### Phase 1: Load context
(Recall relevant memories)

### Phase 2: Do the work
(Your workflow-specific instructions)

### Phase 3: Capture results
(Remember outcomes, curate if needed)
```

**Phase 1 — load context**

```bash
remind recall "<relevant topic>" -k 10
remind snapshot pending  # See what needs review
```

**Phase 3 — capture and curate**

```bash
remind remember "What was learned" -t observation -e concept:topic
remind apply << 'EOF'
processed ids=ep:11,ep:12
EOF
```

### Example: Code review skill

**Before reviewing**

```bash
remind recall "code patterns and conventions" -k 10
remind recall "review" --entity module:<module-name>
```

**After reviewing**

```bash
remind remember "Found repeated error handling in auth — extract to middleware" \
  -t observation -e module:auth

remind remember "Team convention: use Result types for DB operations" \
  -t preference -e project:backend
```

### Ideas for custom skills

- **Onboarding** — Systematically explore and remember architecture decisions
- **Research** — Capture findings, create concepts for themes
- **Debugging** — Remember what you've tried, what worked, outcomes
- **Architecture Decision Records** — Structured decision capture

## Skills vs MCP

| | Skills + CLI | MCP Server |
|---|---|---|
| Database location | `.remind/remind.db` in project | `~/.remind/{name}.db` centralized |
| Requires server | No | Yes |
| Agent requirement | Can run shell commands | MCP client support |
| Best for | Project-scoped memory, custom workflows | Cross-project memory, IDE integration |
| Composability | Write any skill | Fixed tool set |

Both use the same underlying Remind system. You can use both — Skills for project-local work, MCP for cross-project knowledge.

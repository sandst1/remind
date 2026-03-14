# Skills + CLI

Skills are the recommended way to integrate Remind into your workflow. A skill is just a markdown file with instructions that tell an AI agent how to use Remind via the CLI. Any agent that can run shell commands can use them — Claude Code, Cursor, Windsurf, or your own custom setup.

## Why Skills?

Skills + CLI give you:

- **Project-local memory** — The database lives at `.remind/remind.db` in your project. Each project has its own isolated memory. You can gitignore it or commit it.
- **No server needed** — No MCP server to run. The CLI is a self-contained binary.
- **Composable** — Skills are just markdown. Mix and match them, write your own, fork the built-in ones.
- **Agent-agnostic** — Any agent that can run shell commands can use Remind skills. Not locked to any IDE or platform.

## Installing the base skill

```bash
remind skill-install
```

This creates `.claude/skills/remind/SKILL.md` in your project. The base skill teaches your agent the core workflow:

- `remind remember` — Store experiences
- `remind recall` — Retrieve memories
- `remind end-session` — Consolidate at session end
- `remind tasks` — Manage work items

## Built-in workflow skills

Remind ships with four skills that compose into a full development workflow:

| Skill | Purpose |
|-------|---------|
| `remind` | Base memory operations — remember, recall, consolidate |
| `remind-plan` | Interactive planning — spar on trade-offs, crystallize into specs and tasks |
| `remind-spec` | Spec capture — decompose requirements, manage spec lifecycle |
| `remind-implement` | Task execution — pick from backlog, build, verify, complete |

These compose together: **plan → spec → implement**. But each stands alone — you don't need to use the full cycle.

### The planning skill

The planning skill makes your agent an opinionated sparring partner. Instead of passively asking "what do you think?", it:

1. Proposes a concrete approach
2. Asks pointed trade-off questions
3. Pushes back on vague requirements
4. Captures decisions and open questions in Remind as you go
5. Crystallizes the outcome into specs, plans, and tasks

```bash
# During a planning session, the agent captures artifacts:
remind remember "Chose WebSocket over polling: lower latency, simpler client" \
  -t decision -e module:notifications -e tool:websocket

remind remember "WebSocket endpoint at /ws/notifications: JWT auth, JSON events" \
  -t spec -e module:notifications

remind task add "Set up WebSocket server with JWT auth" \
  -e module:notifications --priority p0 --plan <plan-id>
```

### The implementation skill

The implementation skill drives a disciplined build cycle:

**pick → context → build → verify → complete → next**

```bash
remind tasks                          # What's next?
remind task start <id>                # Start working
remind specs --entity module:auth     # Load relevant specs
# ... write code ...
remind task done <id>                 # Mark complete
remind tasks                          # What's next?
```

Active tasks are excluded from consolidation — they stay as live operational data. When a task is marked done, it becomes eligible for consolidation, so the system learns from completed work.

## Writing your own skills

A skill is a markdown file that instructs an agent how to use Remind for a specific workflow. The built-in plan/spec/implement cycle is one opinionated workflow, but Remind is a primitive — you can build anything on top.

### Skill structure

```markdown
# My Custom Skill

> **Important**: The `remind` CLI tool is available in this environment.

## When to use
Describe when this skill should be activated.

## Workflow

### Phase 1: Load context
```bash
remind recall "<relevant topic>" -k 10
remind decisions
```

### Phase 2: Do the thing
(Your workflow-specific instructions here)

### Phase 3: Capture results
```bash
remind remember "What was learned" -t observation -e concept:topic
remind end-session
```
```

### Example: Code review skill

```markdown
# Code Review with Memory

## Workflow
1. Recall prior decisions and patterns for the module under review
2. Review the code against known specs and conventions
3. Remember any new patterns, anti-patterns, or decisions discovered
4. If the review surfaces a question, capture it

### Before reviewing
```bash
remind recall "code patterns and conventions" -k 10
remind recall "review" --entity module:<module-name>
remind specs --entity module:<module-name>
```

### After reviewing
```bash
remind remember "Found repeated error handling pattern in auth module — \
  should extract to middleware" -t observation -e module:auth
remind remember "Team convention: always use Result types for DB operations" \
  -t preference -e project:backend
```
```

### Ideas for custom skills

- **Onboarding** — New to a codebase? A skill that systematically explores and remembers architecture decisions.
- **Research** — Ingest papers or articles, capture key findings, consolidate themes.
- **Journaling** — Daily standup-style summaries that consolidate into project knowledge.
- **Debugging** — Remember what you've tried, what worked, and what didn't.
- **Architecture Decision Records** — Structured decision capture that builds a knowledge graph.

## Skills vs MCP

| | Skills + CLI | MCP Server |
|---|---|---|
| Database location | `.remind/remind.db` in project | `~/.remind/{name}.db` centralized |
| Requires server | No | Yes |
| Agent requirement | Can run shell commands | MCP client support |
| Best for | Project-scoped memory, custom workflows | Cross-project memory, IDE integration |
| Composability | Write any skill, mix and match | Fixed tool set |

Both use the same underlying Remind system. You can even use both — Skills for project-local work, MCP for cross-project knowledge.

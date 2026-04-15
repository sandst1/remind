# Skills + CLI

Skills are the recommended way to integrate Remind into your workflow. A skill is just a markdown file with instructions that tell an AI agent how to use Remind via the CLI. Any agent that can run shell commands can use them — Claude Code, Cursor, Windsurf, or your own custom setup.

## Why Skills?

Skills + CLI give you:

- **Project-local memory** — The database lives at `.remind/remind.db` in your project. Each project has its own isolated memory. You can gitignore it or commit it.
- **No server needed** — No MCP server to run. The CLI is a self-contained binary.
- **Composable** — Skills are just markdown. Extend the bundled skill, write your own, or fork it for a custom workflow.
- **Agent-agnostic** — Any agent that can run shell commands can use Remind skills. Not locked to any IDE or platform.

## Installing the base skill

```bash
remind skill-install
```

This creates `.claude/skills/remind/SKILL.md` in your project. The bundled skill teaches your agent the core workflow:

- `remind remember` — Store experiences
- `remind recall` — Retrieve memories
- `remind end-session` — Consolidate at session end
- Plus topics, ingest, decisions/questions, and maintenance commands — see the installed `SKILL.md` for the full command table.

## The bundled skill

Remind ships one built-in skill: **`remind`**. It covers base memory operations (remember, recall, consolidation), topics, auto-ingest, and CLI maintenance. Install it with `remind skill-install` (no arguments installs all bundled skills; today that is only `remind`).

Example session capture:

```bash
remind remember "Chose WebSocket over polling: lower latency, simpler client" \
  -t decision -e module:notifications -e tool:websocket

remind remember "WebSocket endpoint at /ws/notifications: JWT auth, JSON events" \
  -t fact -e module:notifications

remind recall "notifications WebSocket" -k 10
remind end-session
```

## Writing your own skills

A skill is a markdown file that instructs an agent how to use Remind for a specific workflow. The bundled `remind` skill is a starting point; Remind is a primitive — you can build anything on top.

### Skill structure

A minimal skill file might look like this (save as `.claude/skills/<name>/SKILL.md`):

**Header and workflow outline**

```markdown
# My Custom Skill

> **Important**: The `remind` CLI tool is available in this environment.

## When to use
Describe when this skill should be activated.

## Workflow

### Phase 1: Load context
(Shell commands in the next block)

### Phase 2: Do the thing
(Your workflow-specific instructions here)

### Phase 3: Capture results
(Shell commands in the block after Phase 2)
```

**Phase 1 — load context**

```bash
remind recall "<relevant topic>" -k 10
remind decisions
```

**Phase 3 — capture results**

```bash
remind remember "What was learned" -t observation -e concept:topic
remind end-session
```

### Example: Code review skill

**Outline**

```markdown
# Code Review with Memory

## Workflow
1. Recall prior decisions and patterns for the module under review
2. Review the code against known conventions and prior recall context
3. Remember any new patterns, anti-patterns, or decisions discovered
4. If the review surfaces a question, capture it
```

**Before reviewing**

```bash
remind recall "code patterns and conventions" -k 10
remind recall "review" --entity module:<module-name>
remind decisions
```

**After reviewing**

```bash
remind remember "Found repeated error handling pattern in auth module — \
  should extract to middleware" -t observation -e module:auth
remind remember "Team convention: always use Result types for DB operations" \
  -t preference -e project:backend
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

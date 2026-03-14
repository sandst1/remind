# Tasks

Tasks are a special episode type for tracking discrete work items with a status lifecycle. They bridge the gap between memory (what you know) and action (what you need to do).

## Status lifecycle

```
todo → in_progress → done
  ↓         ↓
  └──► blocked ──► todo (unblock)
```

Timestamps are recorded automatically for transitions (`started_at`, `completed_at`).

## Creating tasks

```bash
remind task add "Implement JWT auth" -e module:auth --priority p0
remind task add "Write auth tests" --depends-on <task-id>
remind task add "Set up CI" --plan <plan-id> --spec <spec-id>
```

Tasks can have:
- **Priority** — `p0` (must-have), `p1` (should-have), `p2` (nice-to-have)
- **Entity tags** — Connect to modules, files, etc.
- **Dependencies** — `--depends-on` another task
- **Plan/spec links** — `--plan` and `--spec` for traceability

## Managing tasks

```bash
remind task start <id>                # todo → in_progress
remind task done <id>                 # → done
remind task block <id> "reason"       # → blocked
remind task unblock <id>              # blocked → todo

remind tasks                          # List active tasks
remind tasks --status todo            # Filter by status
remind tasks --entity module:auth     # Filter by entity
remind tasks --all                    # Include completed
```

## Tasks and consolidation

Active tasks (todo, in_progress, blocked) are **excluded from consolidation**. They stay as live operational data that you query directly.

When a task is marked `done`, it becomes eligible for consolidation. The system learns from completed work — a done task about "Implementing JWT auth" might consolidate into a concept about "Auth system implementation decisions."

This separation means your backlog stays operational while your completed work feeds the knowledge graph.

## Tasks in the workflow

Tasks are most powerful when combined with the [plan and spec skills](/guide/skills):

1. **Plan** — Spar on approach, crystallize into a plan
2. **Spec** — Decompose into individual requirements
3. **Tasks** — Break specs into work items with priorities and dependencies
4. **Implement** — Work through tasks: pick → build → verify → complete → next

Each skill stores its artifacts in Remind, so context carries across sessions and agents.

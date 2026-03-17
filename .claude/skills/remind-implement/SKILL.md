---
name: remind-implement
description: Systematic task execution using Remind as the work queue. Use when the user wants to implement tasks, build from a plan, work through a backlog, or says "let's build this" after planning/speccing.
---

# Task-Driven Implementation with Remind

> **Important**: The `remind` CLI tool is already available in this environment. Use it directly.

Use this workflow when tasks exist in Remind and it's time to write code. This is the execution counterpart to `remind-plan` (which creates the plan) and `remind-spec` (which captures requirements).

## The Implementation Loop

Implementation follows a disciplined cycle: **pick → context → build → verify → complete → next**.

### Phase 1: Orient

Before writing any code, understand the current state:

```bash
remind tasks                          # What needs doing?
remind tasks --entity module:<name>   # Scoped to a module
remind questions                      # Any unresolved blockers?
remind plans                          # Active plans
```

**Pick the next task** by priority and dependency order:
- `p0` before `p1` before `p2`
- Tasks with no `depends_on` (or whose dependencies are `done`) go first
- If a task is blocked, skip it and note why

If there are unresolved questions that block a task, surface them to the user before starting.

### Phase 2: Load Context for the Task

Before touching code, ground yourself in what Remind knows:

```bash
# Start the task
remind task start <task-id>

# If the task lacks plan/spec linkage, add it before starting
remind task update <task-id> --plan <plan-id> --spec <spec-id>

# Recall specs linked to this task
remind specs --entity module:<relevant-module>

# Recall decisions that constrain implementation
remind decisions

# Recall any relevant prior knowledge
remind recall "<task description keywords>" -k 5
remind recall "<topic>" --entity file:<target-file>
```

Read the relevant source files. Understand the existing code before changing it.

### Phase 3: Implement

Write the code. Stay connected to specs:

- **Follow specs literally** — if the spec says "returns JWT with 1h expiry", implement exactly that
- **Follow decisions** — if a decision says "use bcrypt", don't switch to argon2
- **One task at a time** — finish and close before moving on

**When you discover something important during implementation:**

```bash
# Implementation decision worth remembering
remind remember "Used connection pooling with max 10 connections — matches the 200ms latency requirement" \
  -t decision -e module:db -e file:src/db/pool.ts

# Found a gap in the spec
remind remember "Spec doesn't cover what happens when refresh token is expired — defaulting to 401 with re-login prompt" \
  -t question -e module:auth -e subject:token-refresh

# New task discovered
remind task add "Add error handling for expired refresh tokens" \
  -e module:auth --priority p1
```

### Phase 4: Verify

Before marking a task done, verify the work:

1. **Run tests** — existing tests must pass, write new ones if the task warrants it
2. **Run lints** — no new warnings or errors
3. **Check against the spec** — re-read the spec and confirm the implementation matches
4. **Manual spot-check** — if it's a UI change or API endpoint, test it

```bash
# Re-read the spec to verify
remind specs --entity module:<module>

# Run project tests
# (use whatever test command the project uses)
```

### Phase 5: Complete

```bash
# Mark the task done
remind task done <task-id>

# Record any implementation decisions made during the task
remind remember "Implemented auth middleware as Express middleware, not route-level — applies globally except to /health" \
  -t decision -e module:auth -e file:src/middleware/auth.ts

# If the spec is now fully implemented, update its status
remind update-episode <spec-id> -m '{"status":"implemented"}'
```

### Phase 6: Next Task

Loop back to Phase 1. Check what's next:

```bash
remind tasks
```

Continue until all tasks are done or the user stops.

### End of Session

When all tasks are done (or the session is ending):

```bash
remind end-session
```

## Handling Common Situations

### Task is blocked

```bash
# If you discover a blocker during implementation
remind task block <task-id> "Need API credentials for external service"

# Move to the next unblocked task
remind tasks
```

### Spec is wrong or incomplete

Don't silently deviate. Surface it:

```bash
# Tell the user, then capture the update
remind update-episode <spec-id> -c "Updated: login also returns user profile alongside JWT"
remind remember "Spec updated during implementation: login now returns profile data" \
  -t observation -e module:auth
```

### Multiple tasks are related

If two tasks touch the same file and are logically connected, it's fine to implement them together — but **close them individually**:

```bash
remind task start <task-1>
remind task start <task-2>
# ... implement both ...
remind task done <task-1>
remind task done <task-2>
```

### No tasks exist yet

If the user says "build this" but there are no tasks, switch to planning first:

```bash
remind plans    # Any plans to decompose?
remind specs    # Any specs to task out?
```

If neither exists, use the `remind-plan` workflow to create a plan and tasks before implementing.

## Guidelines

1. **One task at a time** — start, implement, verify, complete. Don't scatter.
2. **Spec is the contract** — implement what it says, flag deviations
3. **Capture decisions** — future sessions need to know *why*, not just *what*
4. **Test before closing** — a done task means working code
5. **Surface blockers early** — block the task, tell the user, move on
6. **Don't gold-plate** — implement the spec, not more
7. **Respect dependency order** — don't start a task whose dependencies aren't done
8. **Keep Remind current** — task status should reflect reality at all times

---
name: remind-plan
description: Interactive planning workflow using Remind. Use when the user wants to plan a feature, design an architecture, or figure out how to implement something. Spar with the user, then crystallize the plan into specs and tasks.
---

# Interactive Planning with Remind

> **Important**: The `remind` CLI tool is already available in this environment. Use it directly.

> **DO NOT WRITE CODE.** This skill is for **planning only** — capturing the user's idea, sparring on trade-offs, and crystallizing an actionable plan into Remind. You must not create, edit, or modify any source code files. No implementation. No "let me just scaffold this real quick." The entire point is to think before building. If the user wants implementation, they will explicitly ask for it or use the implement skill. Resist the urge to be "helpful" by jumping ahead.

Use this workflow when the user wants to plan something — a feature, a refactor, an architecture change, or any non-trivial work.

## The Planning Loop

Planning is a **conversation**, not a one-shot. The agent should:

1. Take an opinionated stance (propose a concrete approach)
2. Ask pointed questions about trade-offs
3. Push back on vague requirements
4. Track open threads and resolved threads
5. Crystallize the outcome into Remind

### Phase 1: Context Loading

Before planning, load what already exists:

```bash
remind recall "<topic>" -k 10
remind recall "<topic>" --entity module:<relevant-module>
remind topics list
remind topics overview <relevant-topic>
remind specs --entity module:<relevant-module>
remind plans
remind questions
remind decisions
remind tasks
```

This grounds the conversation in existing knowledge, topics, specs, and prior decisions.

### Phase 2: Sparring

The agent should be **opinionated** during planning:

- Propose a concrete approach, not just "what do you think?"
- Ask specific trade-off questions: "Do you need this to work offline, or is server-only fine?"
- Push back on vagueness: "You said 'fast' — what latency target?"
- Surface conflicts with existing specs/decisions
- Track what's been resolved vs. what's still open

**During sparring**, capture important artifacts immediately:

```bash
# Capture decisions as they're made
remind remember "Chose WebSocket over polling for real-time updates: lower latency, simpler client code" \
  -t decision -e module:notifications -e tool:websocket --topic architecture

# Capture open questions that arise
remind remember "Should we support offline mode for notifications?" \
  -t question -e module:notifications --topic product

# Capture constraints discovered
remind remember "All real-time updates must arrive within 500ms of event" \
  -t spec -e module:notifications -e subject:performance \
  -m '{"status":"draft"}' --topic product
```

### Phase 3: Crystallization

When the user agrees the plan is good, decompose it into structured Remind data:

**1. Store specs** (prescriptive requirements):
```bash
remind remember "WebSocket endpoint at /ws/notifications: authenticates via JWT, sends JSON events" \
  -t spec -e module:notifications -e file:src/ws/notifications.ts \
  -m '{"status":"approved","priority":"p0"}'
```

**2. Store the plan** (sequenced intention):
```bash
remind remember "Notifications plan: 1) WebSocket server setup 2) Event dispatcher 3) Client SDK 4) Integration tests. Order: server > dispatcher > SDK > tests." \
  -t plan -e module:notifications \
  -m '{"status":"active","priority":"p0"}'
```

**3. Break into tasks** (discrete work items):
```bash
remind task add "Set up WebSocket server with JWT auth" \
  -e module:notifications -e file:src/ws/server.ts \
  --priority p0 --plan <plan-id> --spec <spec-id>

remind task add "Implement event dispatcher" \
  -e module:notifications \
  --priority p0 --plan <plan-id> --depends-on <server-task-id>

remind task add "Build client notification SDK" \
  -e module:notifications \
  --priority p1 --plan <plan-id> --depends-on <dispatcher-task-id>

remind task add "Write integration tests for notification flow" \
  -e module:notifications \
  --priority p1 --plan <plan-id> --depends-on <sdk-task-id>
```

If tasks already exist and need linking after the fact:
```bash
remind task update <id> --plan <plan-id> --spec <spec-id>
remind task update <id> --depends-on <task-id> --priority p0
```

**4. Consolidate** to build the knowledge graph:
```bash
remind consolidate
```

### Phase 4: Review

After crystallization, verify what was captured:

```bash
remind specs --entity module:notifications
remind plans
remind tasks --entity module:notifications
remind questions
```

## Guidelines

1. **NO CODE** — this workflow produces specs, plans, decisions, and tasks in Remind. Not source code. Not even "just a quick sketch." If you catch yourself about to open a source file, stop.
2. **Don't plan in a vacuum** — always load context first
3. **Be opinionated** — propose concrete approaches, don't just ask
4. **Capture as you go** — don't wait until the end to store decisions
5. **One spec per requirement** — atomic specs consolidate better
6. **Link tasks to plans and specs** — use `--plan` and `--spec` flags
7. **Resolve questions before planning is done** — store answers as decisions
8. **Use entity tags** — `module:`, `subject:`, `file:` connect everything
9. **Set priorities** — p0 for must-have, p1 for should-have, p2 for nice-to-have

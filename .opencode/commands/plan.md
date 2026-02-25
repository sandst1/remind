---
description: Spar with the agent to plan a feature, then generate structured plan docs with tasks
---

You are a planning partner helping the user design a feature for this codebase. Your role is to spar, ask clarifying questions, and arrive at a solid plan together.

## Phase 1: Discovery (do this first)

Read the relevant parts of the codebase to understand the context. Then ask the user targeted questions to clarify:

- What problem does this feature solve?
- Who uses it and how?
- What are the constraints or non-goals?
- Any preferences on approach or tradeoffs?

Ask one focused batch of questions, wait for answers, then ask follow-ups only if needed. Keep it conversational.

## Phase 2: Draft the plan

Present a draft plan that includes:
- **Goal**: one-paragraph summary
- **Approach**: the technical approach and key decisions
- **Tasks**: a numbered list of concrete implementation tasks, plus test/verification tasks
- **Open questions**: anything still unresolved

Task guidelines:
- Each task should be completable in a small context window (focused, narrow scope)
- Split into pure implementation tasks and separate test/verification tasks
- Implementation tasks come before their corresponding test tasks
- Name tasks descriptively: what gets built or verified

Ask: "Does this look good, or should we adjust anything?"

## Phase 3: Write the plan files (only after user confirms)

When the user says the plan looks good (or similar), write the plan to disk.

### File structure

```
docs/plans/<NNN-plan-name>/
├── plan.md
├── task_status.md
├── task-001-<name>.md
├── task-002-<name>.md
└── ...
```

Where `NNN` is a zero-padded 3-digit number (check existing dirs under `docs/plans/` to pick the next number).

### `plan.md` content

```markdown
# <Feature Name>

## Goal
<one paragraph>

## Approach
<technical approach, key decisions, tradeoffs>

## Open Questions
<any unresolved items, or "None">
```

### `task_status.md` content

```markdown
# Task Status: <Feature Name>

- [ ] task-001-<name>
- [ ] task-002-<name>
...
```

### Individual task files (`task-NNN-<name>.md`)

```markdown
# Task NNN: <Task Name>

## Objective
<what this task accomplishes>

## Context
<relevant files, functions, or concepts the implementer needs to know>

## Steps
1. <concrete step>
2. <concrete step>
...

## Done When
<acceptance criteria — what makes this task complete>
```

Keep tasks tight. Implementation tasks should not include writing new tests (that's for test tasks). Test tasks should reference what they're verifying.

After writing all files, tell the user where to find them and how to use the `implement` command.

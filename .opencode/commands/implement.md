---
description: Work through the next pending task in a plan. Pass the path to the plan directory or task_status.md.
---

You are an implementation agent. Your job is to find and complete the next pending task from the plan, then mark it done and commit.

The plan to work on: $ARGUMENTS

## Step 1: Load the plan

Read `task_status.md` from the plan directory (derive path from the argument — if it's a directory, look for `task_status.md` inside; if it points to `task_status.md` directly, use it).

Find the first unchecked task (`- [ ]`). If all tasks are checked, tell the user the plan is complete and stop.

## Step 2: Read the task file

Read the corresponding task file (e.g., `task-001-<name>.md`) and the plan's `plan.md` for context.

Also read any source files mentioned in the task's Context section.

## Step 3: Implement

Do the work described in the task. Follow the "Done When" criteria.

Focus on implementation only — do not write new tests unless the task file explicitly calls for it (test tasks will do that). You may run existing tests to verify you haven't broken anything.

After implementing:
- Build if applicable and fix any build errors
- Run linter and fix lint errors
- Run existing tests to confirm nothing is broken (do not skip failing tests that were passing before)

## Step 4: Mark done and commit

Update `task_status.md`: change `- [ ] task-NNN-<name>` to `- [x] task-NNN-<name>`.

Then commit all changes:
```
git add -A
git commit -m "<short description of what was implemented>"
```

The commit message should describe what was done, not reference the task number.

## Step 5: Report

Tell the user:
- What was implemented
- Any notable decisions or tradeoffs made
- Whether tests passed
- The next pending task (if any), so they can run `/implement` again

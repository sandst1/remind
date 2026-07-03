---
name: remind-curate
description: Maintain Remind memory quality. Use when recall output shows an OPEN CONFLICTS warning, the user corrects previously stored information, stored memories are outdated or misfiled, topics need reorganizing, or a work session is wrapping up.
---

# Remind - Curating Memory

Keep the memory layer trustworthy: triage contradictions, correct or retire stale items, and keep topics organized.

## Conflicts

Consolidation automatically opens a conflict when it finds incompatible facts or contradicting concepts. Recall output warns with **OPEN CONFLICTS** when retrieved memory is contested.

```bash
remind conflicts                                  # List open conflicts
remind conflicts list --status all                # Include resolved/dismissed
remind conflicts resolve <id> <winning_fact_id> --note "confirmed in prod config" --by alice
remind conflicts dismiss <id> --note "both true: staging vs prod"
```

- **Resolve** when one claim is correct: the losing fact is structurally superseded (kept as history, hidden from recall) and the resolution is recorded as a decision episode.
- **Dismiss** when both claims are valid in different contexts: both facts stay active.
- Use provenance (who asserted each fact, when, source links) to decide. If you can't decide, ask the user — don't guess on contested facts.

## Correcting

```bash
remind update-episode <id> -c "Corrected information"    # Resets for re-consolidation
remind update-episode <id> -t decision                   # Fix a misclassified type
remind update-concept <id> -s "Refined summary" --confidence 0.9
remind update-episode <id> --topic architecture          # Move to another topic
remind update-concept <id> --clear-topic                 # Unset topic
```

When the user corrects a stored fact, prefer capturing the new assertion (with provenance) and letting supersession/conflict machinery handle it; use `update-episode` for typos and misclassification, not for changing history.

## Deleting outdated data

```bash
remind delete-episode <id>       # Soft delete (recoverable)
remind delete-concept <id>
remind deleted                   # Review deleted items
remind restore-episode <id>
remind restore-concept <id>
```

Delete for noise and mistakes. For facts that changed over time, don't delete — supersession keeps history queryable via `--as-of`.

## Topics

```bash
remind topics create "Architecture" -d "System design decisions and patterns"
remind topics update architecture -n "System Architecture" -d "Updated description"
remind topics delete old-topic       # Only if no episodes/concepts reference it
```

## Session end

```bash
remind end-session       # Consolidate pending episodes into concepts
```

Run at natural boundaries. Consolidation is where facts cluster, supersession applies, and conflicts are detected — curation triggers often appear right after.

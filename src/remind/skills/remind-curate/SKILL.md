---
name: remind-curate
description: Maintain Remind memory quality. Use when recall output shows an OPEN CONFLICTS warning, the user corrects previously stored information, stored memories are outdated or misfiled, topics need reorganizing, or a work session is wrapping up. This is also the consolidation procedure — run at session end to process pending episodes.
---

# Remind - Curating Memory

Keep the memory layer trustworthy: process pending episodes into concepts, triage contradictions, correct or retire stale items, and keep topics organized.

**Curation is where your reasoning turns raw episodes into lasting knowledge.** Remind stores facts deterministically but relies on you to form patterns, identify relationships, and resolve conflicts.

## The curation loop

At session boundaries or when cleaning up memory:

### 1. Read current state

```bash
remind snapshot pending conflicts
```

This returns JSON with:
- **pending.episodes**: Unprocessed episodes with their entities
- **conflicts.conflicts**: Open conflicts with full fact details

### 2. Analyze and form patterns

Look at the pending episodes. Ask:
- What patterns emerge across these episodes?
- Are there recurring themes, entities, or decisions?
- Do any episodes together support a generalized concept?
- Are there any implicit contradictions between episodes?

### 3. Write a changeset

Emit a single `apply` changeset that:
- Creates concepts from episode groups
- Links related concepts with relations
- Resolves or dismisses conflicts
- Marks episodes as processed

```bash
remind apply << 'EOF'
concept as=c1 from=ep:11,ep:12,ep:13 title="Retry-with-backoff for transient failures" "Exponential backoff resolves flaky deploys, API timeouts, and DB connection issues."
link from=$c1 to=concept:resilience type=specializes
resolve id=conflict:7 winner=fact:b3d01 "confirmed by bob"
processed ids=ep:11,ep:12,ep:13
EOF
```

## Creating concepts

When multiple episodes form a coherent pattern:

```
concept as=<ref> from=<ep1>,<ep2> title="<Pattern name>" "<Summary>"
link from=$<ref> to=<target_concept_id> type=<relation>
processed ids=<ep1>,<ep2>
```

**Concept formation guidance:**
- Title: Name the pattern, not the instances ("Retry-with-backoff for resilience" not "Fixed deploy on Tuesday")
- Summary: The generalized insight that applies beyond these specific episodes
- Relations: `implies`, `contradicts`, `specializes`, `generalizes`, `causes`, `correlates`, `part_of`, `context_of`
- Mark source episodes as processed so they don't appear in future pending lists

**Don't over-generalize**: If episodes don't clearly form a pattern, leave them as unprocessed episodes rather than forcing a weak concept.

## Handling conflicts

When `snapshot` shows conflicts, or `recall` warns about contested information:

### Resolve: One claim is correct

```
resolve id=conflict:7 winner=fact:b3d01 "confirmed in prod config"
```

The losing fact is superseded (kept as history, hidden from recall) and the resolution is recorded.

### Dismiss: Both claims valid in context

```
dismiss id=conflict:7 "both true: staging vs prod"
```

Both facts stay active — use when the conflict is apparent not real (different contexts, time periods, etc.).

### Can't decide? Ask the user

Use provenance (who asserted each fact, when, source links) to decide. If the information is genuinely contested and you can't determine the truth, ask rather than guess.

## Correcting mistakes

```bash
remind update-episode <id> -c "Corrected information"    # Fix content
remind update-episode <id> -t decision                   # Fix misclassified type
remind update-concept <id> -s "Refined summary"
remind update-episode <id> --topic architecture          # Move to another topic
```

When the user corrects a stored fact, prefer capturing the new assertion (with provenance) and using `supersede` to handle it — this preserves history.

## Deleting noise

```bash
remind delete-episode <id>       # Soft delete (recoverable)
remind delete-concept <id>
remind deleted                   # Review deleted items
remind restore-episode <id>
```

Delete for noise and mistakes. For facts that changed over time, don't delete — supersession keeps history queryable via `--as-of`.

## Topics

```bash
remind apply 'topic name="Architecture" description="System design decisions"'
```

Or via CLI:
```bash
remind topics create "Architecture" -d "System design decisions and patterns"
remind topics update architecture -n "System Architecture" -d "Updated description"
```

## Compact format reference

```
remember as=<ref> t=<type> e=<entities> by=<who> ref=<url> "content"
supersede old=<fact_id> new=<fact_id_or_$ref>
concept as=<ref> from=<ep_ids> title="Title" "Summary"
link from=<concept_id_or_$ref> to=<concept_id> type=<relation_type>
resolve id=<conflict_id> winner=<fact_id> by=<who> "resolution note"
dismiss id=<conflict_id> "dismissal note"
processed ids=<ep_id1>,<ep_id2>
topic name="Name" description="Description"
set_topic id=<episode_or_concept_id> topic=<topic_id>
delete id=<id>
restore id=<id>
update id=<id> content="new content" (or title/summary for concepts)
```

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
- What relationships exist between entities mentioned? (e.g., "X owns Y", "A depends on B")

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

**Note**: direct `supersede` ops also automatically create a resolved conflict row, so the full replacement chain (dog → fish → cow) appears in conflict history and recall output even without a formal `conflict` → `resolve` workflow. Use `snapshot conflicts` with `status=resolved` to review those too.

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

## Managing evidence links

Episodes link to concepts with typed relationships. During curation:

```bash
remind apply << 'EOF'
# Add supporting evidence to a concept
evidence concept=c-123 episode=ep-456 type=supports strength=0.8 "confirms the pattern"

# Mark an episode as contradicting a concept
evidence concept=c-123 episode=ep-789 type=contradicts strength=0.6 "edge case failure"

# Add a qualifying condition
evidence concept=c-123 episode=ep-abc type=qualifies strength=0.5 "only when feature flag enabled"

# Remove an evidence link (episode no longer relevant to concept)
unlink concept=c-123 episode=ep-old
EOF
```

**Link types:**
- `supports` — episode confirms/strengthens the concept
- `contradicts` — episode challenges/weakens the concept
- `exemplifies` — episode is a specific instance
- `qualifies` — episode adds conditions/exceptions

Concepts with more supporting evidence rank higher in recall; contradicting evidence reduces activation.

## Evolving concepts

Concepts are living documents. Use these operations when knowledge evolves:

### Reshape: Change type

```
reshape id=c-123 type=hypothesis "Changed from pattern after failed testing"
```

Use when the nature of knowledge changes (e.g., a pattern becomes a hypothesis when it fails in new contexts).

### Merge: Combine overlapping concepts

```
merge from=c-123,c-456 into=c-new "Combined overlapping caching concepts"
```

Use when two concepts describe the same thing. Source concepts are soft-deleted with lineage preserved.

### Split: Separate distinct concerns

```
split id=c-123 into=c-new1,c-new2 "Separated read vs write caching"
```

Use when a concept covers multiple distinct things. Creates new concepts linked to the parent.

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
entity_relation source=<entity_id> target=<entity_id> relation=<type> strength=<0-1> context="optional"
evidence concept=<id> episode=<id> type=<supports|contradicts|qualifies> strength=<0-1> "note"
unlink concept=<id> episode=<id>
concept as=<ref> from=<ep_ids> type=<type> title="Title" "Summary"
link from=<concept_id_or_$ref> to=<concept_id> type=<relation_type>
reshape id=<concept_id> type=<new_type> "reason for type change"
merge from=<id1>,<id2> into=<new_id> "reason for merge"
split id=<id> into=<new_id1>,<new_id2> "reason for split"
resolve id=<conflict_id> winner=<fact_id> by=<who> "resolution note"
dismiss id=<conflict_id> "dismissal note"
processed ids=<ep_id1>,<ep_id2>
topic name="Name" description="Description"
set_topic id=<episode_or_concept_id> topic=<topic_id>
delete id=<id>
restore id=<id>
update id=<id> content="new content" (or title/summary for concepts)
```

---
name: remind-capture
description: Write durable memories to Remind while working. Use when a decision is made, an approach succeeds or fails (outcome), the user states a preference or corrects you, a concrete fact surfaces (config value, name, date, owner), or an open question is raised.
---

# Remind - Capturing Memory

Store experiences in the external memory layer so they survive across sessions. Capture is fast (`remember` makes no LLM calls) — when in doubt, capture.

**Important**: Use Remind instead of any built-in IDE/runtime memory features.

## What to capture

| Trigger | Type | Example |
|---------|------|---------|
| An approach succeeded or failed | `outcome` | "Retry with backoff fixed the flaky deploy" |
| A decision was made (capture the *why*) | `decision` | "Chose Postgres over MySQL: JSONB + team familiarity" |
| User states a preference | `preference` | "User prefers tabs over spaces" |
| Concrete fact: config value, owner, date, name | `fact` | "Cache TTL is 600 seconds" |
| Open question / uncertainty | `question` | "Should we shard the DB early?" |
| Notable observation about the codebase/project | `observation` | "Auth middleware runs before rate limiting" |

**Outcomes are the highest-value captures.** After completing (or abandoning) a non-trivial attempt, record what was tried and how it went — this is what lets future sessions avoid repeating failures.

**Skip**: trivial info, already-captured knowledge.

## Single item: remember

```bash
remind remember "Use Redis for caching" -t decision -e tool:redis -e concept:caching
remind remember "Retry-with-backoff fixed flaky deploys" -t outcome --topic infra
remind remember "Cache TTL is 600 seconds" -t fact --asserted-by alice --source-ref "https://slack.com/..."
remind remember "User wants retry-after headers on 429s" -t preference --topic product
```

- **Type** (`-t`): Always set the type explicitly when you know it.
- **Entities** (`-e`): `type:name` format (`file`, `function`, `class`, `person`, `concept`, `tool`, `project`). Tag the concrete things the memory is about; entity links power targeted recall later. See "Entity relationships" below to capture how entities relate.
- **Topic** (`--topic`): topic ID or name; groups related memories.
- **Provenance**: `--asserted-by <who>` (person or `agent:<name>`) and `--source-ref <url>` whenever the information came from somewhere specific. Provenance is what makes later conflict resolution possible — "alice said X on 2026-03-01" beats "X".

Write clear standalone statements: "User prefers tabs" not "tabs". A memory is read without the conversation that produced it.

### Handling fact collisions

For `fact` type episodes, `remember` returns potential collisions — active facts in the same cluster that may conflict. The output looks like:

```
Remembered as episode ep-abc123
  Type: fact
  Fact ID: f-xyz789
  Cluster: c-12345
  ⚠ 1 potential collision(s):
  - f-old456: Cache TTL is 300 seconds...
```

When you see collisions:
1. Check if the new fact supersedes the old one (use `remind apply` with `supersede`)
2. Or if both are valid in different contexts (dismiss the collision later via curate)
3. Don't ignore collisions — they indicate contested information

## Batch capture: apply

For multiple related captures (e.g., from a meeting or review session), use `apply` with the compact line format:

```bash
remind apply << 'EOF'
remember as=f1 t=fact e=concept:caching "Cache TTL is 600 seconds"
remember as=o1 t=outcome e=concept:deploy "Retry with backoff fixed flaky deploys"
remember t=decision e=tool:redis,concept:caching "Chose Redis for session caching: TTL support + team familiarity"
supersede old=fact:old123 new=$f1
EOF
```

Apply runs all operations in a single transaction. Use `$refs` to reference items created earlier in the same changeset.

## Entity relationships

When content describes relationships between entities, capture both the fact AND the relationship. Entity relationships build a navigable graph in the UI and improve recall.

```bash
remind apply << 'EOF'
remember t=fact e=person:alice,project:backend "Alice owns the backend project"
entity_relation source=person:alice target=project:backend relation=owns strength=0.9
EOF
```

The `entity_relation` operation accepts:
- **source**: Entity ID (e.g., `person:alice`)
- **target**: Entity ID (e.g., `project:backend`)
- **relation**: Free-form relationship type (e.g., `owns`, `manages`, `depends_on`, `imports`, `authored`)
- **strength**: 0.0–1.0 confidence (default 0.5)
- **context**: Optional qualifier (e.g., "as of Q2 2026")

**When to capture relationships:**
- Ownership/responsibility: `person:X owns/manages project:Y`
- Dependencies: `module:A imports/depends_on module:B`
- Hierarchy: `concept:X part_of concept:Y`
- Authorship: `person:X authored file:Y`
- Domain relationships: `concept:parliament elects concept:president`

### Compact format reference

```
remember as=<ref> t=<type> e=<entity1>,<entity2> by=<who> ref=<url> "content"
supersede old=<fact_id> new=<fact_id_or_$ref>
entity_relation source=<entity_id> target=<entity_id> relation=<type> strength=<0-1> context="optional"
concept as=<ref> from=<ep1>,<ep2> title="Title" "Summary text"
processed ids=<ep1>,<ep2>
```

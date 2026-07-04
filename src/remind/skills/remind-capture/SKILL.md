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

## Should I capture this?

```
Is it worth remembering?
├─ Concrete fact (number, name, date, config value)?
│  └─ Yes → remember -t fact -e <entities> --asserted-by <source>
├─ Decision with rationale?
│  └─ Yes → remember -t decision -e <entities>
├─ Outcome of an attempt (success or failure)?
│  └─ Yes → remember -t outcome -e <entities>
├─ User-stated preference or correction?
│  └─ Yes → remember -t preference
├─ Open question or uncertainty?
│  └─ Yes → remember -t question
├─ Notable observation about code/project?
│  └─ Maybe → remember -t observation
└─ Trivial, transient, or already captured?
   └─ Skip
```

**Examples of what to skip:**
- "I'll use the search tool" (transient action)
- "The file has 100 lines" (trivial, queryable)
- Things you just recalled from memory (already captured)
- Speculative thoughts not grounded in evidence

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

### Handling fact collisions and related facts

For `fact` type episodes, `remember` returns two lists of potentially conflicting facts:

**Collisions** — active facts in the *same cluster* detected via:
1. **Entity overlap**: facts sharing any entity IDs
2. **Semantic similarity**: facts with similar embeddings (cosine > 0.7)

**Related facts** — active facts in *other clusters* detected via:
1. **Bare-name entity match**: strips the type prefix (`person:alice` → `alice`) so `concept:alice`, `project:alice`, etc. are all found, regardless of how the entity was typed
2. **Global embedding similarity**: facts across all clusters with cosine > 0.6

The output looks like:

```
Remembered as episode ep-abc123
  Type: fact
  Entities: concept:alice
  Fact ID: f-xyz789
  Cluster: c-12345

⚠ Entity type coercion (existing entity reused — verify this is correct):
  concept:alice → person:alice

⚠ 2 potential collision(s) in same cluster:
  - f-old456: Cache TTL is 300 seconds...
  - f-old789: Alice is a dog

Related facts — check for conflicts (1):
  [f-old012] "Alice was really a horse" · project:alice · user · 2026-07-03
```

**Entity type coercion** means an existing entity with the same name was found and reused, ignoring the type you specified. This is usually correct (normalizing `concept:alice` → `person:alice` when they mean the same thing), but if the types are genuinely different entities, you should use a more specific name to distinguish them (e.g. `concept:alice-in-wonderland` vs `person:alice-smith`).

When you see collision/related lists:
1. Read each candidate — collisions and related facts are both unresolved by default
2. If the new fact supersedes an old one: use `remind apply` with `supersede old=<id> new=<id> by=<who> note="reason"` — this automatically records a resolved conflict for provenance, so the replacement is visible in future recall and the UI conflict history
3. If there is a genuine contradiction that needs triage: use `conflict` op to record it formally
4. If both are valid in different contexts: no action needed (or `dismiss` later via curate)
5. **Don't ignore either list** — cross-cluster related facts are the most likely source of silent contradictions (same subject, different entity type)

### Nearby episodes and concepts (all episode types)

For **every** `remember` call (not just facts), the output also includes the top-5 most semantically similar episodes and concepts already in the store:

```
Nearby (2 episodes, 1 concepts) — review for conflicts:
  [ep:a1b2c3d4] (0.91) The primary structure is timber frame...
  [ep:e5f6g7h8] (0.84) Budget approved at $480,000 contingency $48,000
  [concept:c-abc123] (0.88) Structural system specification
```

The similarity score (0.0–1.0) is how close the embedding is — it is **not** a conflict signal by itself. You decide whether the content contradicts what you just stored.

**Act on nearby items when you store any episode type:**

1. **Contradiction found** — issue a `conflict` op so it shows up in `snapshot conflicts` for triage:
   ```bash
   remind apply << 'EOF'
   conflict a=ep:a1b2c3d4 b=<current_episode_id> note="doc says timber frame, new info says steel moment frame"
   EOF
   ```
2. **You already know the winner** — use `supersede` (facts only; records a resolved conflict automatically):
   ```bash
   remind apply << 'EOF'
   supersede old=<old_fact_id> new=<new_fact_id> by=<source> note="March 2026 structural report supersedes February overview"
   EOF
   ```
3. **Complementary or unrelated** — ignore and continue.

**Do not silently discard nearby items.** If the nearby content contradicts what you just stored and you do nothing, the contradiction will live in the store undetected. A `conflict` op takes one apply call and makes the tension visible to future sessions.

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

## Entity type reference

| Type | Use for | Example |
|------|---------|---------|
| `file` | Source files, configs, docs | `file:src/auth.ts` |
| `function` | Functions, methods, endpoints | `function:handleLogin` |
| `class` | Classes, interfaces, types | `class:UserService` |
| `module` | Packages, directories, namespaces | `module:authentication` |
| `person` | Human actors, team members | `person:alice` |
| `concept` | Abstract ideas, domains | `concept:caching` |
| `tool` | External tools, services, libraries | `tool:redis`, `tool:pytest` |
| `project` | Projects, repositories, services | `project:backend-api` |

**Guidelines:**
- Use the most specific type. `person:alice` not `concept:alice` for a human.
- Prefer lowercase names: `file:readme.md` not `file:README.md`
- For ambiguous names, add context: `function:auth.handleLogin` not `function:handleLogin`
- Entity names are normalized: `Alice Smith` becomes `alice-smith`

## Evidence links

Episodes can provide evidence for/against concepts with typed relationships. Use this when an experience supports, contradicts, or qualifies an existing concept:

```bash
remind apply << 'EOF'
evidence concept=c-123 episode=ep-456 type=supports strength=0.8 "confirms the caching strategy works"
evidence concept=c-123 episode=ep-789 type=contradicts strength=0.6 "edge case where caching fails"
evidence concept=c-123 episode=ep-abc type=qualifies strength=0.5 "only applies when feature flag enabled"
unlink concept=c-123 episode=ep-old
EOF
```

**Link types:**
- `supports` — episode confirms/strengthens the concept (default)
- `contradicts` — episode challenges/weakens the concept
- `exemplifies` — episode is a specific instance
- `qualifies` — episode adds conditions/exceptions
- `supersedes` — episode invalidates old info

Concepts with more supporting evidence rank higher in recall; contradicting evidence reduces activation.

## Freeform concept types

Concepts can have any type string, not just `pattern` or `fact`. Use domain-specific types:

```bash
remind apply << 'EOF'
concept type=hypothesis "Sharding at 10M rows will solve latency issues"
concept type=rule "If latency > 100ms, enable circuit breaker"
concept type=procedure "Deploy process: staging → canary → production"
EOF
```

**Well-known types with special handling:**
- `fact` / `fact_cluster` — shows validity windows, active facts
- `pattern` — shows evidence quotes, confidence
- `rule` — if-then with conditions
- `procedure` — ordered steps
- `hypothesis` — uncertain, testable belief

Any other string is valid and displays as a badge.

### Compact format reference

```
remember as=<ref> t=<type> e=<entity1>,<entity2> by=<who> ref=<url> "content"
supersede old=<fact_id> new=<fact_id_or_$ref> [by=<who>] [note="reason"]  # auto-records resolved conflict
entity_relation source=<entity_id> target=<entity_id> relation=<type> strength=<0-1> context="optional"
evidence concept=<id> episode=<id> type=<supports|contradicts|qualifies> strength=<0-1> "note"
unlink concept=<id> episode=<id>
concept as=<ref> from=<ep1>,<ep2> type=<type> title="Title" "Summary text"
processed ids=<ep1>,<ep2>
```

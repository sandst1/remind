---
name: remind-capture
description: Write durable memories to Remind while working. Use when a decision is made, an approach succeeds or fails (outcome), the user states a preference or corrects you, a concrete fact surfaces (config value, name, date, owner), or an open question is raised. Also use at session end to bulk-ingest what happened.
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

**Skip**: trivial info, already-captured knowledge, raw conversation logs (use `ingest` for those).

## remember

```bash
remind remember "Use Redis for caching" -t decision -e tool:redis -e concept:caching
remind remember "Retry-with-backoff fixed flaky deploys" -t outcome --topic infra
remind remember "Cache TTL is 600 seconds" -t fact --asserted-by alice --source-ref "https://slack.com/..."
remind remember "User wants retry-after headers on 429s" -t preference --topic product
```

- **Type** (`-t`): run `remind types` for the active set. Always set the type explicitly when you know it — auto-detection during consolidation is a fallback, not the plan.
- **Entities** (`-e`): `type:name` format (`file`, `function`, `class`, `person`, `concept`, `tool`, `project`). Tag the concrete things the memory is about; entity links power targeted recall later.
- **Topic** (`--topic`): topic ID or name; groups related memories.
- **Provenance**: `--asserted-by <who>` (person or `agent:<name>`) and `--source-ref <url>` whenever the information came from somewhere specific. Provenance is what makes later conflict resolution possible — "alice said X on 2026-03-01" beats "X".
- **Source type** (`--source-type`): origin channel (`agent`, `slack`, `github`, `manual`).

Write clear standalone statements: "User prefers tabs" not "tabs". A memory is read without the conversation that produced it.

## ingest (bulk / transcripts)

For raw text where individual memories haven't been identified yet — meeting notes, conversation logs, session transcripts — let the triage LLM extract episodes:

```bash
cat transcript.txt | remind ingest --source transcript
cat meeting.txt | remind ingest -i "extract decisions and action items"
remind ingest "long unstructured update..." --topic infra --asserted-by bob
remind flush-ingest        # force-process whatever is buffered
```

- `--instructions` / `-i` steers what triage extracts.
- `--topic` stamps all extracted episodes; omitted → per-episode topics are inferred.
- `--asserted-by` / `--source-ref` stamp provenance on all extracted episodes.
- Small inputs are buffered until a threshold; `flush-ingest` forces processing.

## Session end

Run `remind end-session` at natural boundaries to consolidate pending episodes into concepts. Before that, capture any outcomes from the session that weren't recorded in-flow.

If the project has the ambient capture hook installed (`remind hook-install`; check for a `remind ingest-transcript` Stop hook in `.claude/settings.json`), the session transcript is triaged automatically — don't also ingest the transcript manually. In-flow `remember` calls are still valuable for high-signal items: they carry explicit types, entities, and provenance that triage has to guess.

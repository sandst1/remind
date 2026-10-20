# Codex model capability and Remind interface pilot — 2026-10-20

Improving Remind's agent interface produced substantial gains with the same Luna
model. A stronger model handled the original interface more reliably. After the
interface changes, the remaining measured Luna gap was source-permalink handling,
which a focused schema follow-up addressed on three repetitions of one task.
These are small fixture results, not production reliability estimates.

## Main experiment

Four conditions crossed `gpt-6-luna` / `gpt-6.1-sol` with original / revised
Remind tool descriptions and skills. All used Codex CLI 0.163.0, medium reasoning,
the same six tools, preserved MCP initialization instructions, local embeddings,
a 60-call/300-second session budget, and the same tasks and grader. Each condition
ran capture and correction in architecture and configuration, three times each:
12 cases and 30 fresh sessions per condition, 48 cases / 120 sessions overall.
No conversation was resumed; only each disposable Remind store persisted between
sessions. Storage and retrieval implementation were held constant.

The original and revised sources were frozen before model runs. Manifests and
source/runner/grader hashes are retained with the artifacts. The revised treatment
changed the `remember`, `remember_batch`, `apply`, and `snapshot` descriptions,
and capture/curation skills. It clarified separate typed assertions, factual
corrections, source references, revisions, and verification of actual supersession
links. Both conditions had batch capture and inspection; tool exposure was not a
factor in the main comparison.

| Model | Remind interface | Full completion | Completion excluding source provenance | Initial fact capture | Structural correction history | Source provenance | Correct final answer |
|---|---|---:|---:|---:|---:|---:|---:|
| Luna | Original | 0/12 | 5/12 | 5/12 | 3/6 | 0/12 | 12/12 |
| Luna | Revised descriptions/skills | 8/12 | 12/12 | 12/12 | 6/6 | 8/12 | 12/12 |
| Sol | Original | 12/12 | 12/12 | 12/12 | 6/6 | 12/12 | 12/12 |
| Sol | Revised descriptions/skills | 12/12 | 12/12 | 12/12 | 6/6 | 12/12 | 12/12 |

"Full completion" requires all state and answer checks, including proper
`source_ref` on the current fact and supporting evidence. The 0/12 original Luna
score therefore does not mean 12 unusable answers. Correct answers hid missing
first-class facts, incomplete history, and provenance omissions. The alternative
completion column excludes only provenance; all other checks and hard violations
still apply. History is measured on the six correction cases, not capture cases.

The interface treatment raised Luna's full completion by 8/12 cases and its
non-provenance completion by 7/12. Moving to Sol instead closed all failures in
this pilot, including the remaining four source-permalink omissions. This does
not prove Sol or revised Luna will achieve those rates on unrelated work.

## Friction and resource observations

| Model / interface | Calls per case | Schema/transport error flags | Revision error flags | Unknown snapshot scopes | Other operation errors | Mean case seconds |
|---|---:|---:|---:|---:|---:|---:|
| Luna / original | 12.4 | 7 | 10 | 8 | 3 | 49.2 |
| Luna / revised | 11.2 | 0 | 3 | 6 | 0 | 52.6 |
| Sol / original | 13.2 | 12 | 0 | 0 | 0 | 64.3 |
| Sol / revised | 10.6 | 0 | 0 | 0 | 0 | 59.3 |

Sol needed approximately 20% fewer calls with the revised interface despite its
completion score already being saturated. Luna made fewer errors and calls while
doing more complete memory work; its mean elapsed time did not improve. Timing
includes server/process startup and concurrent runs. Cache hits and platform
load also affect latency. Reports retain input/cached/output/reasoning token
counts; Codex subscription usage is not an API-dollar bill.

## Focused batch-schema follow-up

All three revised-Luna configuration capture runs omitted `source_ref`, placing
the supplied artifact reference in `asserted_by`. The batch item was exposed as an
unstructured object: individual fields existed mainly in prose.

The follow-up changed only the model-visible batch item schema, making content,
type, entity arrays, label objects, speaker, and source-reference fields explicit.
It retained the same revised skills, Luna/medium, tools, and configuration capture
task. All three repetitions then preserved source references and passed the full
checks: **0/3 with descriptions alone versus 3/3 with the richer schema**.
This is a targeted exploratory result on one task, not a full 12-case rerun or a
held-out confirmation. It supports retaining the low-risk schema improvement and
testing it on broader inputs.

The schema does not fill, coerce, or split capture payloads. Existing raw-dict
capture validation and idempotency request hashing remain intact. A regression
test captures through the old raw path and replays the same receipt through the
new MCP schema, including omitted fields and integer confidence. A preliminary
follow-up invocation failed on relative skill paths before any model calls; that
infrastructure attempt was retained and excluded from the valid comparison.

## Grading audit

The main run initially used grading version 2. Transcript review found false
negatives for "Use" versus "uses" and "Keep ... separate" versus "kept/remain
separate". Version 3 normalizes those limited grammatical variants. Every saved
state in every condition, and the schema follow-up, was rescored identically;
raw scores, transcripts, and hashes remain unchanged. Nine main-case check sets
changed; only one overall result changed (revised Luna 7/12 to 8/12).
The normalization retains predicates: "delete backups" does not cover "keep
backups".

The corrected grader also:

- Uses actual linked evidence and content coverage, not a minimum of two episode
  rows, to judge supported concepts. Separately typed capture is a diagnostic.
- Requires an actual closed-fact supersession chain reaching an active current
  fact. Prose saying "superseded" is insufficient.
- Separates definite active obsolete assertions from incidental historical-value
  mentions requiring prose review.
- Checks `source_ref` specifically; placing the reference in `asserted_by` does
  not satisfy the source-permalink requirement.

The lexical checks still cannot adjudicate arbitrary paraphrase or negation.
Reported answers and failed-state examples were reviewed alongside transcripts.
The grader is deterministic infrastructure, not an internal LLM judge.

## Where to invest next

1. **Retain the description/skill and batch-schema changes.** These are measured
   gains in Remind's public agent interface, and help a stronger model use fewer
   calls as well as helping Luna maintain correct structured state.
2. **Unify record inspection.** Revised Luna still requested six unsupported
   snapshot scopes despite prose guidance. A discoverable episode lookup/snapshot
   scope is a stronger affordance than expecting agents to remember an exception.
3. **Make revision requirements and write verification easier to consume.**
   Distinguish omitted revisions from stale ones and return updated revisions and
   structural write consequences. Keep caller authorization/concurrency checks.
4. **Test the schema on held-out families before choosing a production model.**
   The main study covers two synthetic domains and repetitions share fixtures;
   nominal binomial intervals do not account for that clustering.

This study gives little reason to prioritize retrieval ranking changes first:
all 48 final answers passed the answer rubric. It demonstrates larger immediate
headroom in capture schemas, instructions, provenance, and verifiable curation.
It does not establish that retrieval is solved for larger or harder workloads.

## Reproduction and artifacts

See [the runner and comparison instructions](../README.md#comparing-models-with-remind-interface-changes).
The [machine-readable summary](./codex-interface-2026-10-20.json) retains design,
metrics, per-case checks, and rescoring metadata.
The [exact tool catalogs and skills](./codex-interface-2026-10-20-inputs.json)
archive all three interface treatments for inspection across computers.
Full frozen sources, transcripts, and before/after memory snapshots are under
`.remind/runtime/evals/interface-comparison-20261020/` on the development computer.
Raw comparison scores are in `results/comparison.json`; the uniformly rescored
version is `results/comparison.regraded.json`. The valid schema follow-up has
`batch-schema-followup-valid/report.regraded.json`.

No internal model calls were added to Remind. No CI, commit, release, or deployment
was performed as part of this experiment.

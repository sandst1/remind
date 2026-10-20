# Local Remind evaluations

Run from an installed development checkout, or prefix commands with `PYTHONPATH=src python -m remind.evals` in place of `remind-eval`.

```bash
remind-eval --suite operational
remind-eval --suite operational --transports python --scenario architecture
remind-eval --suite retrieval
remind-eval --suite agent --agent-command '/absolute/path/to/my-runner'
remind-eval --suite all --agent-command '/absolute/path/to/my-runner'
```

All evaluations run locally. There is no CI or internal model-calling agent inside Remind. MCP/REST operational checks launch the actual server on temporary loopback ports. Stores and test repositories are isolated; reports default to ignored `.remind/runtime/evals/`.

## Dataset and expected outcomes

The versioned dataset is [`src/remind/eval_data/dataset.json`](../src/remind/eval_data/dataset.json), included in the Python package. It contains six fixture families, 30 operational scenarios, 60 retrieval queries, and 12 external-agent tasks. The families cover architecture decisions, temporal configuration, preferences, ownership, evolving documents, and mixed notes.

Fixtures define source material, labels, entities, logical record aliases, expected transitions, and answer rubrics. Generated IDs and exact concept wording are not golden answers. Expected data stays in the harness, outside runner-visible task manifests. Use synthetic data; do not add private production memories.

## Operational suite

Runs capture → inspect → curate → supersede → persist → restart → retrieve through Python, CLI subprocesses, MCP client/server processes, and REST. Checks returned results and independently reads persisted state after client/server shutdown. Additional scenarios verify conflict disposition, evidence links, retry idempotency, failed-apply rollback, and portable roundtrips.

The embedding provider is a fixed offline token-hash implementation used solely for operational checks. It is not a semantic-quality benchmark. Every operational case must pass.

Related pytest regressions cover real Git checkout/merge/clone/conflicts, concurrent writers, process death after a commit decision, schema validation, sparse label filtering, source freshness, read-only recall, and exports above 10,000 episodes.

`--backend` selects a disposable SQL database for an explicitly selected case. Do not point it at an existing memory database. Default evaluation stores are temporary file-backed directories. Optional database contract tests use `REMIND_TEST_POSTGRES_URL` and `REMIND_TEST_MYSQL_URL` against empty local test databases.

## Semantic suite

Uses the actual default local embedding model. Explicit invocation permits its initial model download; subsequent runs use cached weights. Reports identify the model, dimensions, dataset digest, and configuration.

Each query runs vector-only, hybrid, and graph retrieval. Fixtures include label-excluded distractors, historical facts, resolved conflicts, changed source files, paraphrases, exact identifiers, and irrelevant queries. Reports include recall@5, nDCG@5, positive success, empty-result rate, context size, and latency. A logical answer may have multiple acceptable evidence records; recall@5 is whether an acceptable record appears in the five highest-scoring concept/episode results.

The full graph pipeline must meet 90% positive success and 90% correct empty results, with zero filter leakage or obsolete facts presented as active. Baseline modes are reported independently. Conflict-history quotations of superseded claims are allowed when explicitly identified as history.

## External agent runner contract

The harness invokes the configured command separately for each fresh session. It writes one JSON manifest to stdin and expects one JSON result on stdout. Diagnostic output belongs on stderr. Each session is limited to five minutes and 60 declared tool calls. Reports/transcripts are saved outside the agent workspace.

Input:

```json
{
  "version": 1,
  "case_id": "architecture.correction_recall",
  "session": 0,
  "fresh_session": true,
  "seed": 0,
  "task": "Capture and curate the supplied notes...",
  "workspace": "/temporary/isolated/workspace",
  "mcp_endpoint": "http://127.0.0.1:12345/sse?db=...",
  "max_tool_calls": 60,
  "timeout_seconds": 300,
  "skills": ["/installed/remind/skills/remind-capture/SKILL.md"]
}
```

Output:

```json
{
  "runner": {"name": "my-runner", "model": "configured-model", "version": "1"},
  "answer": "Current information with supporting evidence...",
  "transcript": [
    {"type": "tool_call", "name": "recall", "arguments": {"query": "..."}},
    {"type": "tool_result", "name": "recall", "result": {}}
  ]
}
```

The runner starts a fresh conversation, reads the supplied skills, and connects only to the supplied store. It must not inspect eval datasets, expected results, or prior transcripts. Agent judgment and model calls belong in the external runner. The local server uses real local embeddings.

Tasks cover capture/curation and correction across sessions, followed by read-only fetching from durable memory. Grading checks current facts, retained superseded history, source provenance, supported concepts, pending work, retrieval calls, answer rubrics, duplicate/unsupported active facts, and unchanged durable state during the final read-only session. Three repetitions per task expose variability. Completion must reach 90%, with no hard violations.

Agent grading version 3 checks linked evidence for coverage of both the decision
and outcome; one episode can contain both assertions. Separately typed capture
is reported as a diagnostic, not conflated with independent source support.
History must follow a closed fact's actual `superseded_by` chain to the active
replacement. Definite obsolete assertions and still-active original fact IDs
remain violations; incidental old-value mentions receive a prose-review flag.
Source provenance checks the actual `source_ref` field, rather than a fixture
string anywhere in the export. These checks apply identically to every model and
interface condition. It normalizes limited grammatical variants such as
use/uses and keep/kept/remain. Older grading versions must be rescored uniformly
before comparing them with v3.

Fact/rubric grading uses fixture token/regex checks and structural assertions, allowing word order and common wording variations. It does not claim unrestricted semantic judgment: review transcripts for prose quality or valid paraphrases outside the rubric. Tool-call counts rely on the runner's transcript; the runner is trusted evaluation infrastructure, not a security boundary.

Without `--agent-command`, agent status is **not_run**, and a requested agent/all run exits nonzero. Missing configuration is never counted as a pass.

### Running with Codex CLI

The source checkout includes `evals/codex_runner.py`. It uses the installed Codex
CLI and its existing login; no separate OpenAI SDK or API key is needed when
Codex is already authenticated. This adapter was exercised with Codex CLI
`0.163.0`; older versions must support `exec --json`, `--ephemeral`,
`--ignore-user-config`, and `--ignore-rules`.

From the repository root, start with a three-session correction smoke test:

```bash
REMIND_CODEX_RUNNER="'$PWD/.venv/bin/python' '$PWD/evals/codex_runner.py' --model gpt-6-luna --reasoning-effort medium"
.venv/bin/python -m remind.evals --suite agent \
  --agent-command "$REMIND_CODEX_RUNNER" \
  --scenario architecture.correction_recall --repetitions 1 \
  --output .remind/runtime/evals/codex-luna-smoke
```

After inspecting the report and transcripts, omit `--scenario` for all 12 cases
with one repetition (30 fresh sessions). Set `--repetitions 3` for the full
90-session evaluation. Each session makes real model calls through Codex.
Select another model or reasoning setting with the runner's `--model` and
`--reasoning-effort` options; `gpt-6-luna` and `medium` are the defaults. Use
`--codex /path/to/codex` to select a particular installed CLI binary.

Each invocation starts a fresh, ephemeral Codex process. User config and rule
files are skipped; shell, web, apps, and subagent tools are disabled. The runner
inlines the supplied skills and task, without the dataset, grading rubric, or
prior conversations. A required stdio MCP bridge forwards `remember`,
`remember_batch`, `apply`, `recall`, `snapshot`, and `inspect` to the supplied local
SSE endpoint and preserves its initialization instructions. These six tools are
explicitly approved for the disposable fixture store. Use `--tool-profile core`
to reproduce the original four-tool restriction. Read-only
sessions still expose writes so the grader can detect an agent violating the
task; the adapter does not silently prevent or repair such violations.

The bridge records actual requests/results and enforces the session's tool-call
budget. A missing bridge, missing model access, a failed CLI turn, zero observed
memory calls, a timeout, or an empty answer fails the run. Model decisions and
answers are never filled in by the adapter. The adapter rejects non-MCP shell,
file-edit, or web activity observed in CLI events.

The optional manifest field `runner_artifacts` selects a diagnostics directory
outside the agent workspace. The harness supplies it automatically. It retains
raw Codex events, stderr, final answers, and the bridge transcript, including on
failures. Per-session JSON results also report CLI version, selected model,
reasoning effort, and token usage. Codex does not expose a sampling seed here:
the adapter records `seed_supported: false`; harness seeds do not imply
reproducible model sampling. Filesystem and tool configuration provide controlled
evaluation conditions, not a hostile-agent security boundary.

The initial live smoke run on 2026-10-20 used `gpt-6-luna` at `medium` with Codex
CLI `0.163.0`. It completed three fresh sessions with 7, 5, and 1 observed memory
calls. The final answer matched the rubric and the recall session preserved
memory. The case **failed** the supported-pattern and structural-history checks:
the agent combined source notes into one outcome, then described supersession
without creating a supersession link. The token checker also flagged the active
fact's mixture of current information and an earlier-claim quotation; inspect
the transcript alongside this coarse flag. One smoke case does not establish
the model's overall success rate. A copy of the report and diagnostics is under
`.remind/runtime/evals/codex-luna-smoke-2026-10-20/` on the development computer;
its recorded absolute paths refer to the original `/private/tmp/` run location.
Those smoke scores use grading version 1 and the original four-tool runner;
retain them as historical diagnostics rather than a current comparison baseline.

### Comparing models with Remind interface changes

`evals/compare_agents.py` runs a factorial pilot using frozen original/revised
source trees. The same grader, runner, six tools, tasks, repetitions, and reasoning
setting apply to both interface versions and both models. Only the server tool
descriptions and supplied Remind skills change between the interface treatments;
storage and retrieval behavior stay fixed. Frozen sources and content hashes
prevent later edits from changing a condition during a run.

```bash
.venv/bin/python evals/compare_agents.py \
  --original /absolute/path/to/frozen-original/src \
  --revised /absolute/path/to/frozen-revised/src \
  --output .remind/runtime/evals/interface-comparison \
  --models gpt-6-luna gpt-6.1-sol \
  --families architecture configuration --repetitions 3 --concurrency 4
.venv/bin/python evals/analyze_comparison.py \
  .remind/runtime/evals/interface-comparison
```

The default design has 48 cases (120 fresh Codex sessions). It reports capture
fact creation, capture decomposition/provenance, evidence support, correction
history, final answers, read-only preservation, tool failures, latency, and token
usage. Artifacts include initial state, pre-recall/final state, and raw session
transcripts so grading can be audited. `analysis.json` includes descriptive model
and interface effects and Wilson intervals. This small pilot cannot establish
production reliability; sampling is stochastic and Codex token counts are not
actual billing. Use held-out families and further repetitions before making a
release-quality model selection.

The completed pilot and schema follow-up are documented in
[the 2026-10-20 results](results/codex-interface-2026-10-20.md). It found gains in
Remind's interface with the same Luna model, while a stronger model compensated
for the original interface's weaknesses. The MCP batch schema now exposes each
item's fields without coercing/default-filling the raw request, preserving
existing retry receipt hashes.

For transparent rescoring after a grader correction:

```bash
.venv/bin/python evals/regrade_comparison.py /path/to/comparison-directory
.venv/bin/python evals/analyze_comparison.py /path/to/comparison-directory
```

The rescorer also accepts an individual agent `report.json`. It leaves raw
reports intact and records the original-report and new-grader hashes.

For an isolated agent run against a frozen interface, use `remind.evals`
`--agent-server-source /path/to/src` and
`--agent-skills-root /path/to/src/remind/skills` with the same agent command.

## Reports and baselines

`--output` selects an artifact directory. `report.json` contains per-case results, metrics, timings, and failure details; `report.md` summarizes them. Failures and requested suites that cannot run return nonzero. `--scenario`, `--transports`, `--seed`, and `--repetitions` select local runs.

`--baseline path/to/report.json` compares matching case IDs/modes/transports and fails on previously passing cases that now fail. Baselines are never rewritten automatically. The included before-fix baseline records the lexical false-positive defect discovered during this implementation; it is explicitly not a passing release baseline.

Run pytest separately. The repository's pre-existing 80% coverage gate is retained; an untouched baseline run measured about 52%, despite all 319 baseline tests passing. A failed coverage gate is not the same as a failing functional scenario, and must remain visible in validation reports.

## Local SQL integration and performance

```bash
pip install -e '.[dev,postgres,mysql]'
docker compose -f evals/docker-compose.yml up -d --wait
REMIND_TEST_POSTGRES_URL='postgresql+psycopg://remind:remind@127.0.0.1:5433/remind_eval_admin' \
REMIND_TEST_MYSQL_URL='mysql+pymysql://root:remind@127.0.0.1:3307/remind_eval_admin' \
  pytest tests/test_sql_backend_contract.py --no-cov
PYTHONPATH=src python evals/benchmark.py
```

The optional integration tests create and drop their own randomly named databases on local servers; the configured user needs database-creation privileges. They skip when URLs are absent. The benchmark uses disposable stores containing 1,000 and 10,000 episodes and reports cold rebuild, warm recall, capture, pagination, and export time. Warm recall must not rebuild or mutate its projection. It requires no model download.

## Local implementation handoff — 2026-10-20

Nothing was deployed or published. Changes remain uncommitted in the working tree. No CI was added. The disposable Docker test containers have been stopped and removed.

Implemented: canonical Git-friendly JSON storage; ignored, rebuildable vector/lexical projections; migration with retained backups; atomic capture/apply and recovery journals; full UUIDs, revision checks and idempotency receipts; complete portable exports/backups; strict retrieval filters; read-only recall; file provenance/freshness; doctor; shared Python/CLI/MCP/REST workflows; revision-aware UI and pagination; updated skills/docs; and local operational, semantic, and external-agent eval harnesses.

Measured validation:

- Final pytest: 347 passed, 2 optional SQL tests skipped by default. The separately enabled PostgreSQL/MySQL checks both passed. Coverage: 57.03%; the unchanged 80% gate correctly returns a failing exit status.

- Operational: 120/120 cases across Python, CLI, MCP, and REST. The final REST retry case was rerun after HTTP conflict handling changed. The checked-in operational baseline combines those verified results and records that rerun.
- Semantic: 180 runs (60 queries across vector, hybrid, and graph). Graph and hybrid achieved 100% positive success and correct empty results, with zero filter/history leakage; vector-only positive success was 88.9%. See the versioned 0.14 baselines.
- PostgreSQL and MySQL: one disposable lifecycle each, both passed in 1.77 seconds total. No Docker scale benchmark was run.
- UI: type check passed with seven existing CSS warnings; production bundle built. Documentation site and Python wheel/source distribution built; packaged dataset, skills, UI assets, and eval documentation verified.
- Filesystem benchmark: at 10,000 records, warm recall 57 ms, capture 1.93 s, pagination 62 ms, export 352 ms, and cold rebuild 11.26 s. This is local diagnostic timing, not a universal performance guarantee.

Remaining validation limits: external-agent evaluations require an explicit runner and have not run; missing configuration reports `not_run`, never pass. The existing 80% coverage gate remains unmet (untouched baseline about 52%, implementation about 57%), despite passing functional tests. SQL checks are intentionally small; they do not establish high-volume or concurrent production performance.

This checkout's memory migrated to `.remind/memory/` (14 episodes, 2 concepts, 4 facts). Original database/log and a consistent database backup are preserved in ignored `.remind/runtime/1e4671f1493a763d/`. Local embeddings were rebuilt; `remind --embedding local doctor` reported no issues. To use the old database deliberately, select its preserved path with an explicit SQLite URL. Review text changes and memory files before committing. Git operations and deployment remain user-controlled.

Tomorrow: review the diff and breaking API contracts, configure an external-agent runner if desired, and address coverage gaps. Run the operational/retrieval suites against the checked-in 0.14 baselines to detect regressions. Large scale checks belong on disposable file stores; keep Docker checks small.

## Review follow-up — 2026-10-20

Reviewed commit `f3589e2` after transfer to the other computer. The original
handoff's working-tree statement above is historical: that implementation was
committed. This follow-up remains available as a working-tree diff.

Fixed issues found during review:

- Fact IDs used by `label`/`unlabel` redirect to source episodes. Revision checks
  now authorize the episode actually edited, while facts and episodes created
  inside the same changeset still need no prior revision.
- Query recall now applies episode history constraints and constrains entity
  expansion by labels/history. Candidate searches expand until eligible results
  fill the requested budget or candidates are exhausted. Large SQLite candidate
  budgets fall back to exact search rather than exceeding native KNN limits.
- Scoped pattern concepts retain their examples; historical fact clusters retain
  the facts valid at the requested time.
- Imports reject duplicate incoming identities, including identical duplicates,
  and assemble/validate the prospective state inside the write transaction.
- Clearing an embedding removes the stale native vector entry. First embedded
  SQLite writes can initialize indexes within the transaction; rollback restores
  the in-memory dimension state along with SQL state.
- Rejected file-store transactions that never start persistence retain their
  projection, event sequences, and polling generation.
- Background recall worker logging no longer references an undefined `args`
  variable. File-store logging stays under runtime, and config/logging paths
  decode URL escapes so paths containing spaces resolve correctly. Global file
  stores do not masquerade as project-local configuration roots.

Added regression coverage for both file and SQLite storage, configuration
precedence and invalid environment values, store discovery and migration, worker
startup/IPC/cleanup, local embedding loader cleanup, and evaluator success/failure
reporting. The Python operational fixture variants now also run under pytest.

Validation:

- Pytest: **476 passed, 2 optional SQL tests skipped**. Combined statement/branch
  coverage increased from **57.03% to 66.53%**; the unchanged 80% gate still causes
  a nonzero pytest exit. This is an outstanding coverage gap, not a passing gate.
- Operational baseline comparison: **120/120 passed**, across Python, CLI, MCP,
  and REST, with zero regressions. MCP/REST required approved local loopback
  access because the sandbox denied binding their test ports.
- Semantic baseline comparison: **180 runs**, zero regressions. Graph and hybrid
  retain 100% positive success and correct empty results; vector-only positive
  success remains 88.9%. No graph filter/history leakage was reported. The
  existing local model ran offline without downloads.
- `git diff --check` passed. Reports are in `/private/tmp/remind-review-pytest.log`,
  `/private/tmp/remind-review-coverage-final.json`,
  `/private/tmp/remind-review-operational-approved/`, and
  `/private/tmp/remind-review-retrieval/` on this computer.

Remaining gaps: the overall coverage gate is still unmet. Large uncovered areas
include legacy `llm_protocol.py`, advanced apply/retrieval branches, SQL-specific
backends, and the external-agent evaluator. External-agent evaluations still need
an explicitly configured runner and remain not-run. PostgreSQL/MySQL integration
was not rerun because the local Docker daemon is unavailable; the existing two
optional tests skipped. No production concurrency/scale claim follows from the
local SQLite tests. No CI, deployment, release, or commit was performed in this
follow-up.

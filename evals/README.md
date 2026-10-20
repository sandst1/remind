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

Fact/rubric grading uses fixture token/regex checks and structural assertions, allowing word order and common wording variations. It does not claim unrestricted semantic judgment: review transcripts for prose quality or valid paraphrases outside the rubric. Tool-call counts rely on the runner's transcript; the runner is trusted evaluation infrastructure, not a security boundary.

Without `--agent-command`, agent status is **not_run**, and a requested agent/all run exits nonzero. Missing configuration is never counted as a pass.

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

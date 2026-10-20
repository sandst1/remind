"""Local operational, retrieval, and external-agent evaluations.

Run ``python -m remind.evals --suite operational`` without model downloads.
Expected outcomes are loaded only by the harness, never supplied to agents.
"""

from __future__ import annotations

import argparse
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
import importlib.resources
import json
import math
import os
from pathlib import Path
import shlex
import socket
import subprocess
import sys
import tempfile
import time
from typing import Any

from remind.apply import ApplyEngine
from remind.interface import MemoryInterface
from remind.operations import record_revision
from remind.providers.deterministic import DeterministicEmbedding
from remind.serialization import canonical_json
from remind.storage import open_store


def dataset() -> dict:
    resource = importlib.resources.files("remind") / "eval_data" / "dataset.json"
    return json.loads(resource.read_text())


class PythonAdapter:
    def __init__(self, selector: str, embedding=None):
        self.memory = MemoryInterface(embedding or DeterministicEmbedding(), store=open_store(selector),
                                      hybrid_keyword_weight=.3)

    async def call(self, tool: str, args: dict) -> dict:
        if tool == "remember":
            return (await self.memory.remember(**args)).to_dict()
        if tool == "recall":
            return (await self.memory.recall(**args)).to_dict()
        if tool == "apply":
            return (await ApplyEngine(self.memory.store, self.memory.embedding).apply(**args)).to_dict()
        if tool == "snapshot":
            from remind.snapshot import SnapshotEngine
            return await SnapshotEngine(self.memory.store, self.memory.embedding).snapshot(args["scopes"])
        raise ValueError(tool)

    async def close(self):
        self.memory.store.engine.dispose()


def command_environment() -> dict:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1]) + os.pathsep + env.get("PYTHONPATH", "")
    env["EMBEDDING_PROVIDER"] = "deterministic"
    return env


class CLIAdapter:
    def __init__(self, selector: str, workspace: Path):
        self.selector, self.workspace = selector, workspace

    async def call(self, tool: str, args: dict) -> dict:
        command = [sys.executable, "-m", "remind.cli", "--store", self.selector,
                   "--embedding", "deterministic", tool]
        if tool == "remember":
            command += [args["content"], "--json"]
            for key, option in (("episode_type", "--type"), ("asserted_by", "--asserted-by"),
                                ("source_ref", "--source-ref"), ("idempotency_key", "--idempotency-key")):
                if args.get(key):
                    command += [option, args[key]]
            for entity in args.get("entities", []):
                command += ["--entity", entity]
            for key, value in args.get("labels", {}).items():
                command += ["--label", f"{key}={value}"]
        elif tool == "apply":
            command += [json.dumps(args["changeset"]), "--json", "--revisions", json.dumps(args.get("expected_revisions", {}))]
            if args.get("idempotency_key"):
                command += ["--idempotency-key", args["idempotency_key"]]
        elif tool == "snapshot":
            command += args["scopes"]
        elif tool == "recall":
            command += [args["query"], "--json"]
            for key, value in args.get("labels", {}).items():
                command += ["--label", f"{key}={value}"]
        result = await asyncio.to_thread(subprocess.run, command, capture_output=True, text=True,
                                         env=command_environment(), cwd=self.workspace, timeout=60)
        if not result.stdout.strip():
            raise RuntimeError(result.stderr or f"CLI exited {result.returncode}")
        value = json.loads(result.stdout)
        if result.returncode and value.get("success") is not False:
            raise RuntimeError(result.stderr)
        return value

    async def close(self):
        pass


@asynccontextmanager
async def mcp_server(selector: str, workspace: Path, embedding: str = "deterministic"):
    """Launch the actual public server and wait for its listening socket."""
    from urllib.parse import quote
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    with (workspace / "server.log").open("w") as log:
        process = subprocess.Popen([sys.executable, "-m", "remind.mcp_server", "--port", str(port),
                                    "--embedding", embedding], cwd=workspace,
                                   stdout=log, stderr=log, env=command_environment())
        try:
            for _ in range(200):
                if process.poll() is not None:
                    raise RuntimeError((workspace / "server.log").read_text())
                try:
                    reader, writer = await asyncio.open_connection("127.0.0.1", port)
                    writer.close()
                    await writer.wait_closed()
                    break
                except OSError:
                    await asyncio.sleep(.05)
            else:
                raise TimeoutError("MCP server did not start")
            yield f"http://127.0.0.1:{port}/sse?db={quote(selector, safe='')}"
        finally:
            process.terminate()
            try:
                await asyncio.to_thread(process.wait, timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                await asyncio.to_thread(process.wait)


class MCPAdapter:
    def __init__(self, session):
        self.session = session

    async def call(self, tool: str, args: dict) -> dict:
        args = dict(args)
        if "entities" in args:
            args["entities"] = ",".join(args["entities"])
        if "labels" in args:
            args["labels"] = ",".join(f"{k}={v}" for k, v in args["labels"].items())
        if tool == "snapshot":
            args["scopes"] = " ".join(args["scopes"])
        if tool == "apply":
            args["changeset"] = json.dumps(args["changeset"])
        result = await self.session.call_tool(tool, args)
        text = "".join(item.text for item in result.content if hasattr(item, "text"))
        if result.isError:
            raise RuntimeError(text)
        return json.loads(text)


class RESTAdapter:
    def __init__(self, endpoint: str, selector: str):
        import httpx
        self.client = httpx.AsyncClient(base_url=endpoint.split("/sse")[0], params={"db": selector}, timeout=60)

    async def call(self, tool: str, args: dict) -> dict:
        path = "/api/v1/query" if tool == "recall" else "/api/v1/workflow/" + tool
        response = await self.client.post(path, json=args)
        if tool == "apply" and response.status_code in {409, 422}:
            failed = response.json()
            if failed.get("success") is False and failed.get("errors"):
                return failed
        response.raise_for_status()
        return response.json()


@asynccontextmanager
async def adapter(kind: str, selector: str, workspace: Path):
    if kind == "rest":
        async with mcp_server(selector, workspace) as endpoint:
            client = RESTAdapter(endpoint, selector)
            try:
                yield client
            finally:
                await client.client.aclose()
    elif kind == "mcp":
        from mcp import ClientSession
        from mcp.client.sse import sse_client
        async with mcp_server(selector, workspace) as endpoint:
            async with sse_client(endpoint) as streams:
                async with ClientSession(*streams) as session:
                    await session.initialize()
                    yield MCPAdapter(session)
    else:
        client = PythonAdapter(selector) if kind == "python" else CLIAdapter(selector, workspace)
        try:
            yield client
        finally:
            await client.close()


async def seed(client, family: dict) -> dict:
    captured = {}
    for alias, content, kind in (("old", family["old"], "fact"), ("current", family["current"], "fact"),
                                  ("decision", family["decision"], "decision"), ("outcome", family["outcome"], "outcome")):
        captured[alias] = await client.call("remember", {"content": content, "episode_type": kind,
            "entities": [family["entity"]] + ([family["source_entity"]] if alias == "outcome" and family.get("source_entity") else []), "labels": family["labels"],
            "asserted_by": "eval-fixture", "source_ref": "fixture:" + family["id"]})
    return captured


async def revisions(client) -> dict:
    state = await client.call("snapshot", {"scopes": ["episodes:1000", "concepts:1000", "conflicts:all"]})
    found = {}
    def visit(item):
        if isinstance(item, dict):
            if item.get("id") and item.get("revision"):
                found[item["id"]] = item["revision"]
            for value in item.values():
                visit(value)
        elif isinstance(item, list):
            for value in item:
                visit(value)
    visit(state)
    # Fact revisions are available in detailed concept snapshots.
    for identifier in list(found):
        if identifier in found:
            detail = await client.call("snapshot", {"scopes": ["concept:" + identifier]})
            visit(detail)
    return found


async def curate(client, family, captured):
    expected = await revisions(client)
    result = await client.call("apply", {"changeset": [
        {"op": "concept", "as": "pattern", "title": family["subject"],
         "content": family["decision"] + ". " + family["outcome"], "confidence": 1,
         "labels": family["labels"], "from": [captured["decision"]["episode_id"], captured["outcome"]["episode_id"]]},
        {"op": "supersede", "old": captured["old"]["fact_id"], "new": captured["current"]["fact_id"],
         "note": "Latest explicit correction"},
    ], "expected_revisions": expected})
    assert result["success"], result
    return result["results"][0]["id"]


async def operational_case(case: dict, family: dict, kind: str, selector: str, workspace: Path) -> dict:
    initial = open_store(selector)
    try:
        if initial.get_all_episodes() or initial.get_all_concepts() or initial.get_all_facts():
            raise ValueError("Operational evaluations require an empty disposable store")
    finally:
        initial.engine.dispose()
    async with adapter(kind, selector, workspace) as client:
        captured = await seed(client, family)
        pattern = await curate(client, family, captured)
        result = await client.call("recall", {"query": family["current"], "labels": family["labels"]})
        assert family["current"] in result["text"], "Current fact missing"
        # Resolution history may quote obsolete values, but not as active fact rows.
        state = await client.call("snapshot", {"scopes": ["pending", "concept:" + captured["current"]["cluster_id"], "concept:" + pattern]})
        assert not state["pending"]["episodes"], "Curation left pending episodes"
        if case["variant"] == "retry_failure":
            request = {"content": "Retry safety", "idempotency_key": "retry"}
            first = await client.call("remember", request)
            assert first == await client.call("remember", request), "Duplicate retry"
            failed = await client.call("apply", {"changeset": [
                {"op": "remember", "content": "MUST ROLL BACK"},
                {"op": "update", "id": "missing", "content": "failure"}]})
            assert not failed["success"]
            recent = await client.call("snapshot", {"scopes": ["episodes:1000"]})
            assert "MUST ROLL BACK" not in json.dumps(recent)
        if case["variant"] == "conflicts":
            opened = await client.call("apply", {"changeset": [{"op": "conflict",
                "a": captured["old"]["fact_id"], "b": captured["current"]["fact_id"], "note": "Audit disagreement"}]})
            assert opened["success"], opened
            conflict_id = opened["results"][0]["id"]
            dismissed = await client.call("apply", {"changeset": [{"op": "dismiss", "id": conflict_id,
                "note": "Historical correction already explains this"}], "expected_revisions": await revisions(client)})
            assert dismissed["success"], dismissed
    # Independently inspect persistence after the public client/server has closed.
    store = open_store(selector)
    try:
        assert store.get_fact(captured["old"]["fact_id"]).superseded_by == captured["current"]["fact_id"]
        assert len(store.get_evidence_for_concept(pattern)) == 2
        assert store.get_concept(pattern).source_episodes
        if case["variant"] == "roundtrip":
            exported = store.export_data()
            restored = open_store((workspace / "restored").as_uri())
            try:
                restored.import_data(exported)
                assert restored.export_data()["records"] == exported["records"]
            finally:
                restored.engine.dispose()
    finally:
        store.engine.dispose()
    async with adapter(kind, selector, workspace) as client:
        result = await client.call("recall", {"query": family["current"], "labels": family["labels"]})
        assert family["current"] in result["text"], "Knowledge lost across process restart"
    return {"passed": True}


async def retrieval_suite(data, args, root):
    from remind.providers.local import LocalEmbedding
    provider = LocalEmbedding()
    model_probe = await provider.embed("Remind evaluation model initialization")
    rows = []
    for original in data["families"]:
        family = {**original, "source_entity": "file:source.txt"}
        directory = root / family["id"]
        directory.mkdir(parents=True)
        source = directory / "source.txt"
        source.write_text(family["outcome"])
        memory = PythonAdapter((directory / "memory").as_uri(), provider)
        memory.memory.source_root = directory
        try:
            captured = await seed(memory, family)
            opened = await memory.call("apply", {"changeset": [{"op": "conflict",
                "a": captured["old"]["fact_id"], "b": captured["current"]["fact_id"], "note": "Explicit correction"}]})
            assert opened["success"], opened
            pattern = await curate(memory, family, captured)
            await memory.call("remember", {"content": "FORBIDDEN unrelated confidential zebra note",
                "episode_type": "fact", "entities": [family["entity"]], "labels": {"area": "other"}})
            old = memory.memory.store.get_fact(captured["old"]["fact_id"])
            new = memory.memory.store.get_fact(captured["current"]["fact_id"])
            historical = old.valid_from + (new.valid_from - old.valid_from) / 2
            for query in data["retrieval"]:
                if query["family"] != family["id"] or (args.scenario and args.scenario not in query["id"]):
                    continue
                if query["category"] == "freshness":
                    source.write_text("The supporting source document changed")
                for mode in ("vector", "hybrid", "graph"):
                    m = memory.memory
                    m.retriever.hybrid_keyword_weight = 0 if mode == "vector" else .3
                    m.retriever.spread_hops = 2 if mode == "graph" else 0
                    started = time.perf_counter()
                    result = await m.recall(query["query"], k=5, episode_k=5, labels=query["labels"],
                        as_of=historical if query["category"] == "historical" else None, min_score=.3, explain=True)
                    ranked = sorted([(c.activation, c.concept.id) for c in result.concepts] +
                                    [(e.score, e.episode.id) for e in result.episodes], reverse=True)[:5]
                    if query["expected"] is None:
                        passed = not result.concepts and not result.episodes
                        rank = None
                    else:
                        key = query["expected"]
                        gold = {pattern, captured["decision"]["episode_id"], captured["outcome"]["episode_id"]} if key == "pattern" else {
                            captured[key]["cluster_id"], captured[key]["episode_id"]}
                        rank = next((i + 1 for i, (_, identifier) in enumerate(ranked) if identifier in gold), None)
                        expected = family["decision"] if key == "pattern" else family[key]
                        passed = rank is not None and expected in result.text
                    leakage = bool(query["labels"] and "FORBIDDEN" in result.text)
                    historical_leak = query["expected"] == "current" and any(
                        line.strip().startswith("• " + family["old"]) for line in result.text.splitlines())
                    if query["category"] == "freshness":
                        passed = passed and any("changed" in warning for warning in result.warnings)
                    if query["category"] == "conflict":
                        passed = passed and "Conflict history" in result.text
                    passed = passed and not leakage and not historical_leak
                    rows.append({"id": query["id"], "mode": mode, "passed": passed,
                                 "category": query["category"], "latency_ms": (time.perf_counter()-started)*1000,
                                 "recall_at_5": int(rank is not None), "ndcg_at_5": 1 / math.log2(rank+1) if rank else 0,
                                 "filter_leakage": leakage, "historical_leakage": historical_leak,
                                 "context_chars": len(result.text), "explanation": result.explanation})
        finally:
            await memory.close()
    metrics = {}
    for mode in ("vector", "hybrid", "graph"):
        selected = [r for r in rows if r["mode"] == mode]
        positive = [r for r in selected if r["category"] != "irrelevant"]
        negative = [r for r in selected if r["category"] == "irrelevant"]
        metrics[mode] = {"recall_at_5": sum(r["recall_at_5"] for r in positive)/max(1,len(positive)),
                         "ndcg_at_5": sum(r["ndcg_at_5"] for r in positive)/max(1,len(positive)),
                         "positive_success_rate": sum(r["passed"] for r in positive)/max(1,len(positive)),
                         "empty_result_rate": sum(r["passed"] for r in negative)/max(1,len(negative))}
    complete = [r for r in rows if r["mode"] == "graph"]
    gates = metrics["graph"]
    passed = bool(complete) and gates["positive_success_rate"] >= .9 and gates["empty_result_rate"] >= .9
    passed = passed and not any(r["filter_leakage"] or r["historical_leakage"] for r in complete)
    return {"status": "passed" if passed else "failed", "model": provider.name,
            "dimensions": len(model_probe), "cases": rows, "metrics": metrics}


def covers(statement: str, expected: str) -> bool:
    import re
    ignored = {"the", "a", "an", "is", "now", "for", "with", "uses"}
    words = set(re.findall(r"\w+", statement.lower()))
    required = set(re.findall(r"\w+", expected.lower())) - ignored
    return required <= words


async def agent_suite(data, args, root):
    if not args.agent_command:
        return {"status": "not_run", "reason": "Configure --agent-command", "cases": []}
    from remind.providers.local import LocalEmbedding
    await LocalEmbedding().embed("Initialize local evaluation embeddings")
    rows = []
    families = {f["id"]: f for f in data["families"]}
    import uuid
    run_root = root / uuid.uuid4().hex
    for case in data["agent"]:
        if args.scenario and args.scenario not in case["id"]:
            continue
        family = families[case["family"]]
        for repetition in range(args.repetitions):
            name = f"{case['id']}.{repetition}"
            workspace = run_root / "workspaces" / name
            transcripts = run_root / "transcripts" / name
            workspace.mkdir(parents=True)
            transcripts.mkdir(parents=True)
            selector = (workspace / "memory").as_uri()
            sessions, before_final = [], None
            initial = family["current"] if case["task"] == "capture_curate" else family["old"]
            tasks = [f"Capture the useful information and curate the decision/outcome into a supported concept. Source notes: {initial}. {family['decision']}. {family['outcome']}. Use entity {family['entity']} and labels {family['labels']}. Preserve provenance as fixture:{family['id']}."]
            if case["task"] == "correction_recall":
                tasks.append(f"The user explicitly corrects the earlier information: {family['current']}. Update and curate memory accordingly. Preserve the earlier fact as superseded history; use the same entity, labels, and source provenance.")
            tasks.append(f"Using only durable memory, what is the current information about {family['subject']} and what approach worked? Retrieve supporting evidence. This is a read-only session; do not modify memory.")
            try:
                async with mcp_server(selector, workspace, embedding="local") as endpoint:
                    for number, task in enumerate(tasks):
                        if number == len(tasks)-1:
                            store = open_store(selector)
                            before_final = store.export_data()["records"]
                            store.engine.dispose()
                        manifest = {"version": 1, "case_id": case["id"], "session": number,
                                    "fresh_session": True, "seed": args.seed + repetition,
                                    "task": task, "workspace": str(workspace), "mcp_endpoint": endpoint,
                                    "max_tool_calls": 60, "timeout_seconds": 300,
                                    "skills": [str(importlib.resources.files("remind") / "skills" / skill / "SKILL.md")
                                               for skill in ("remind-capture", "remind-curate", "remind-context")]}
                        result = await asyncio.to_thread(subprocess.run, shlex.split(args.agent_command),
                            input=json.dumps(manifest), capture_output=True, text=True, cwd=workspace,
                            timeout=300, env=command_environment())
                        output = json.loads(result.stdout)
                        if result.returncode or not isinstance(output.get("transcript"), list) or not output.get("runner") or not isinstance(output.get("answer"), str):
                            raise ValueError("Runner must return runner identity, transcript, answer, and exit successfully")
                        calls = [event for event in output["transcript"] if event.get("type") == "tool_call"]
                        if len(calls) > 60:
                            raise ValueError("Tool-call budget exceeded")
                        sessions.append(output)
                        (transcripts / f"session-{number}.json").write_text(canonical_json(output))
                store = open_store(selector)
                try:
                    facts = store.get_all_facts()
                    active = [f.statement for f in facts if f.is_active]
                    snapshot = store.export_data()["records"]
                    patterns = [c for c in store.get_all_concepts() if c.concept_type == "pattern"]
                    supported = any(len(c.source_episodes) >= 2 and store.get_evidence_for_concept(c.id) for c in patterns)
                    completion = any(covers(f, family["current"]) for f in active) and supported
                    history = case["task"] != "correction_recall" or any(covers(f.statement, family["old"]) and not f.is_active and f.superseded_by for f in facts)
                    answer = sessions[-1]["answer"]
                    import re
                    answer_matches = all(re.search(pattern, answer, re.IGNORECASE) for pattern in
                        family["answer_rubric"]["value_patterns"] + family["answer_rubric"]["approach_patterns"])
                    completion = completion and answer_matches
                    completion = completion and "fixture:" + family["id"] in json.dumps(snapshot)
                    retrieved = any(event.get("type") == "tool_call" and event.get("name") in {"recall", "snapshot"} for event in sessions[-1]["transcript"])
                    violations = []
                    if snapshot != before_final:
                        violations.append("Final read-only session changed durable memory")
                    if any(covers(f, family["old"]) for f in active):
                        violations.append("Obsolete fact remains active")
                    if len(active) != len(set(active)):
                        violations.append("Duplicate active facts")
                    if any(not any(covers(statement, family[key]) or covers(family[key], statement)
                                   for key in ("old", "current", "decision", "outcome")) for statement in active):
                        violations.append("Unsupported active fact")
                    pending_clear = store.count_unconsolidated_episodes() == 0
                    completion = completion and pending_clear
                    completion = completion and history and retrieved and not violations
                    rows.append({"id": case["id"], "repetition": repetition, "passed": completion,
                                 "hard_violations": violations, "checks": {"history": bool(history), "supported_pattern": bool(supported),
                                     "answer_rubric": bool(answer_matches), "read_performed": retrieved, "pending_clear": pending_clear},
                                 "runner": sessions[-1]["runner"],
                                 "transcripts": str(transcripts), "grading": "Fixture token coverage plus observable state; prose review required"})
                finally:
                    store.engine.dispose()
            except Exception as exc:
                rows.append({"id": case["id"], "repetition": repetition, "passed": False, "error": str(exc)})
    passed = bool(rows) and sum(r["passed"] for r in rows)/len(rows) >= .9 and not any(r.get("hard_violations") for r in rows)
    return {"status": "passed" if passed else "failed", "cases": rows}


async def run(args):
    data = dataset()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = {"version": 1, "dataset_version": data["version"], "dataset_digest": __import__("remind.serialization", fromlist=["revision"]).revision(data), "configuration": vars(args), "suites": {}}
    with tempfile.TemporaryDirectory(prefix="remind-eval-") as temporary:
        root = Path(temporary)
        if args.suite in {"all", "operational"}:
            rows = []
            families = {f["id"]: f for f in data["families"]}
            for case in data["operational"]:
                if args.scenario and args.scenario not in case["id"]:
                    continue
                for transport in args.transports.split(","):
                    workspace = root / (case["id"] + "-" + transport)
                    workspace.mkdir()
                    selector = args.backend or (workspace / "memory").as_uri()
                    start = time.perf_counter()
                    try:
                        result = await operational_case(case, families[case["family"]], transport, selector, workspace)
                    except Exception as exc:
                        result = {"passed": False, "error": repr(exc)}
                    rows.append({"id": case["id"], "transport": transport, "elapsed_seconds": time.perf_counter()-start, **result})
                    print(f"{transport}: {case['id']}: {'passed' if result['passed'] else 'FAILED'}", file=sys.stderr, flush=True)
            report["suites"]["operational"] = {"status": "passed" if rows and all(r["passed"] for r in rows) else "failed", "cases": rows}
        for name, suite in (("retrieval", retrieval_suite), ("agent", agent_suite)):
            if args.suite in {"all", name}:
                directory = output / "agent-runs" if name == "agent" else root / name
                directory.mkdir(exist_ok=True)
                try:
                    report["suites"][name] = await suite(data, args, directory)
                except Exception as exc:
                    report["suites"][name] = {"status": "failed", "error": repr(exc)}
    if args.baseline:
        baseline = json.loads(Path(args.baseline).read_text())
        regressions = []
        for name, suite in report["suites"].items():
            previous = {(r["id"], r.get("mode"), r.get("transport")): r for r in baseline.get("suites", {}).get(name, {}).get("cases", [])}
            for case in suite.get("cases", []):
                key = (case["id"], case.get("mode"), case.get("transport"))
                if previous.get(key, {}).get("passed") and not case["passed"]:
                    regressions.append({"suite": name, "id": case["id"], "mode": case.get("mode"), "transport": case.get("transport")})
                    suite["status"] = "failed"
        report["baseline"] = {"path": args.baseline, "regressions": regressions}
    (output / "report.json").write_text(canonical_json(report))
    lines = ["# Remind evaluation report", "", "| Suite | Status | Cases |", "|---|---|---:|"]
    for name, result in report["suites"].items():
        lines.append(f"| {name} | {result['status']} | {len(result.get('cases', []))} |")
        if result.get("reason") or result.get("error"):
            lines.extend(["", result.get("reason") or result["error"]])
        if "metrics" in result:
            lines.extend(["", "Retrieval metrics (graph is the release gate; vector/hybrid are diagnostic baselines):", "", "```json", canonical_json(result["metrics"]).rstrip(), "```"])
        for case in result.get("cases", []):
            if not case["passed"]:
                context = case.get("mode") or case.get("transport") or "agent"
                lines.extend(["", f"- {case['id']} ({context}): {case.get('error', 'expectation failed')}"])
    (output / "report.md").write_text("\n".join(lines) + "\n")
    print(json.dumps({name: result["status"] for name, result in report["suites"].items()}))
    return 0 if report["suites"] and all(r["status"] == "passed" for r in report["suites"].values()) else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=["operational", "retrieval", "agent", "all"], default="operational")
    parser.add_argument("--transports", default="python,cli,mcp,rest")
    parser.add_argument("--backend", help="Explicit SQL URL for a disposable evaluation database")
    parser.add_argument("--scenario", help="Run IDs containing this string")
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--agent-command")
    parser.add_argument("--baseline")
    parser.add_argument("--output", default=".remind/runtime/evals")
    args = parser.parse_args()
    if args.repetitions < 1 or set(args.transports.split(",")) - {"python", "cli", "mcp", "rest"}:
        parser.error("Use positive repetitions and known transports: python,cli,mcp,rest")
    if args.backend and (len(args.transports.split(",")) != 1 or args.scenario not in {c["id"] for c in dataset()["operational"]}):
        parser.error("A SQL backend requires one exact --scenario ID and one --transports value")
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()

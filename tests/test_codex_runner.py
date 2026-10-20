"""External runner protocol, isolation settings, and observed tool budgets."""

import json
from pathlib import Path
import sys
from types import SimpleNamespace
from urllib.parse import quote

import pytest
from mcp.types import CallToolResult, TextContent

from evals import codex_runner as runner


@pytest.fixture
def manifest(tmp_path):
    workspace = tmp_path / "isolated workspace"
    workspace.mkdir()
    skill = tmp_path / "skill" / "SKILL.md"
    skill.parent.mkdir()
    skill.write_text("Use inspected revisions before edits.")
    return {"version": 1, "fresh_session": True, "workspace": str(workspace),
            "mcp_endpoint": "http://127.0.0.1:12345/sse?db=" + quote((workspace / "memory").as_uri(), safe=""),
            "task": "Recall the current TTL without changing memory.", "skills": [str(skill)],
            "max_tool_calls": 2, "timeout_seconds": 30, "seed": 12,
            "case_id": "hidden-case-id", "expected": "THIS MUST NEVER REACH CODEX"}


def test_prompt_includes_only_task_and_skills(manifest):
    prompt = runner.build_prompt(runner.validate_manifest(manifest))
    assert manifest["task"] in prompt
    assert "Use inspected revisions" in prompt
    for hidden in (manifest["expected"], manifest["case_id"], manifest["workspace"], manifest["mcp_endpoint"]):
        assert hidden not in prompt


@pytest.mark.parametrize("field,value", [("version", 2), ("fresh_session", False), ("task", ""),
    ("max_tool_calls", 0), ("max_tool_calls", 61), ("max_tool_calls", True),
    ("timeout_seconds", 301), ("skills", [])])
def test_manifest_rejects_invalid_contract(manifest, field, value):
    manifest[field] = value
    with pytest.raises(ValueError):
        runner.validate_manifest(manifest)


@pytest.mark.parametrize("endpoint", ["https://example.invalid/sse?db=file:///tmp/memory",
    "http://127.0.0.1:12345/sse?db=file:///outside/memory",
    "http://127.0.0.1:12345/sse?db=sqlite:///existing.db",
    "http://127.0.0.1:12345/other?db=file:///tmp/memory"])
def test_manifest_refuses_remote_or_unrelated_store(manifest, endpoint):
    manifest["mcp_endpoint"] = endpoint
    with pytest.raises(ValueError):
        runner.validate_manifest(manifest)


def test_command_pins_model_and_uses_fresh_isolated_session(tmp_path):
    args = runner.codex_command("codex", "gpt-6-luna", "medium", str(tmp_path), tmp_path / "state", tmp_path / "answer")
    assert args[:2] == ["codex", "exec"]
    assert args[args.index("--model") + 1] == "gpt-6-luna"
    assert "--ephemeral" in args and "--ignore-user-config" in args and "--ignore-rules" in args
    assert args[args.index("--sandbox") + 1] == "read-only"
    settings = dict(args[i + 1].split("=", 1) for i, arg in enumerate(args) if arg == "-c")
    assert json.loads(settings["features.shell_tool"]) is False
    assert json.loads(settings["mcp_servers.remind.required"]) is True
    assert json.loads(settings["mcp_servers.remind.default_tools_approval_mode"]) == "approve"
    assert json.loads(settings["model_reasoning_effort"]) == "medium"


@pytest.mark.asyncio
async def test_bridge_records_requests_responses_and_enforces_budget(tmp_path):
    forwarded = []
    async def call(name, arguments):
        forwarded.append((name, arguments))
        return CallToolResult(content=[TextContent(type="text", text='{"text":"TTL is 300"}')])
    transcript = tmp_path / "observed.jsonl"
    bridge = runner.RecordingBridge(SimpleNamespace(call_tool=call), transcript, max_calls=1)
    result = await bridge.call("recall", {"query": "TTL"})
    assert not result.isError
    with pytest.raises(ValueError, match="budget"):
        await bridge.call("apply", {"changeset": "delete"})
    assert forwarded == [("recall", {"query": "TTL"})]
    events = runner.read_transcript(transcript)
    assert [e["type"] for e in events] == ["tool_call", "tool_result", "tool_call", "tool_result"]
    # A restarted bridge cannot reset the shared session budget.
    assert runner.RecordingBridge(None, transcript, 1).calls == 2


@pytest.mark.asyncio
async def test_bridge_records_upstream_errors(tmp_path):
    async def call(*args):
        raise RuntimeError("Transport disconnected")
    bridge = runner.RecordingBridge(SimpleNamespace(call_tool=call), tmp_path / "events", 2)
    with pytest.raises(RuntimeError, match="disconnected"):
        await bridge.call("snapshot", {"scopes": "pending"})
    assert runner.read_transcript(bridge.transcript)[-1]["error"] == "Transport disconnected"
    with pytest.raises(ValueError, match="not available"):
        await bridge.call("unrelated_tool", {})


@pytest.mark.parametrize("event", [{"type": "turn.failed", "error": {"message": "Model unavailable"}},
    {"type": "error", "message": "Login required"},
    {"type": "item.completed", "item": {"type": "command_execution"}}])
def test_incomplete_or_disallowed_codex_turn_is_failure(event):
    with pytest.raises((RuntimeError, ValueError)):
        runner.parse_events(json.dumps(event))
    with pytest.raises(RuntimeError, match="completed turn"):
        runner.parse_events("")


def test_runner_subprocess_contract(manifest, tmp_path):
    manifest["runner_artifacts"] = str(tmp_path / "diagnostics")
    fake = tmp_path / "fake-codex"
    fake.write_text(f"#!{sys.executable}\n" + '''
import json,sys
from pathlib import Path
if '--version' in sys.argv:
    print('codex-cli test-double')
    raise SystemExit(0)
settings=dict(sys.argv[i+1].split('=',1) for i,arg in enumerate(sys.argv) if arg=='-c')
bridge_args=json.loads(settings['mcp_servers.remind.args'])
state=json.loads(Path(bridge_args[-1]).read_text())
observed=[{'type':'tool_call','name':'recall','arguments':{'query':'TTL'}},
          {'type':'tool_result','name':'recall','result':{'content':[]}}]
Path(state['transcript']).write_text(''.join(json.dumps(e)+'\\n' for e in observed))
Path(sys.argv[sys.argv.index('--output-last-message')+1]).write_text('TTL is 300 seconds.')
print(json.dumps({'type':'turn.completed','usage':{'input_tokens':123,'output_tokens':12}}))
''')
    fake.chmod(0o755)
    response = runner.run(manifest, "gpt-6-luna", "medium", str(fake))
    assert response["answer"] == "TTL is 300 seconds."
    assert response["runner"]["model"] == "gpt-6-luna"
    assert response["runner"]["seed_supported"] is False
    assert response["usage"]["input_tokens"] == 123
    assert response["transcript"][0]["name"] == "recall"
    assert (tmp_path / "diagnostics/codex.jsonl").is_file()
    assert (tmp_path / "diagnostics/answer.txt").read_text() == response["answer"]


def test_missing_codex_is_an_explicit_failure(manifest):
    with pytest.raises(ValueError, match="not found"):
        runner.run(manifest, "gpt-6-luna", "medium", "/does/not/exist/codex")


def test_artifacts_cannot_live_in_agent_workspace(manifest):
    manifest["runner_artifacts"] = str(Path(manifest["workspace"]) / "transcripts")
    with pytest.raises(ValueError, match="outside"):
        runner.run(manifest, "gpt-6-luna", "medium", sys.executable)


def test_execute_timeout_stops_child_process(tmp_path):
    import os
    import subprocess
    pid_path = tmp_path / "pid"
    script = "import os,time; from pathlib import Path; Path(" + repr(str(pid_path)) + ").write_text(str(os.getpid())); time.sleep(30)"
    with pytest.raises(subprocess.TimeoutExpired):
        runner.execute([sys.executable, "-c", script], "", timeout=1)
    pid = int(pid_path.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_unrelated_mcp_server_is_rejected():
    event = {"type": "item.completed", "item": {"type": "mcp_tool_call", "server": "other", "tool": "fetch"}}
    with pytest.raises(ValueError, match="Unexpected MCP server"):
        runner.parse_events(json.dumps(event))


@pytest.mark.asyncio
async def test_extended_bridge_exposes_batch_without_relaxing_core_profile(tmp_path):
    forwarded=[]
    async def call(name, arguments):
        forwarded.append(name)
        return CallToolResult(content=[])
    session=SimpleNamespace(call_tool=call)
    extended=runner.RecordingBridge(session,tmp_path/'extended',2)
    await extended.call('remember_batch', {'items': []})
    core=runner.RecordingBridge(session,tmp_path/'core',2,runner.CORE_TOOLS)
    with pytest.raises(ValueError,match='not available'):
        await core.call('remember_batch', {'items': []})
    assert forwarded==['remember_batch']

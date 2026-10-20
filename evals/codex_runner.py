"""External Codex CLI adapter for remind.evals; no model calls live in Remind.

Reads one evaluation manifest from stdin and writes one runner result to stdout.
The --bridge mode is an internal stdio-to-SSE MCP proxy with observed transcripts.
"""

from __future__ import annotations

import argparse
import asyncio
from contextlib import nullcontext
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
from typing import Any, Optional
from urllib.parse import parse_qs, unquote, urlsplit

RUNNER_VERSION = "2"
CORE_TOOLS = {"remember", "apply", "recall", "snapshot"}
ALLOWED_TOOLS = CORE_TOOLS | {"remember_batch", "inspect"}


def validate_manifest(value: dict) -> dict:
    if not isinstance(value, dict) or value.get("version") != 1 or value.get("fresh_session") is not True:
        raise ValueError("Expected a version 1 fresh-session manifest")
    if not isinstance(value.get("task"), str) or not value["task"].strip():
        raise ValueError("Manifest requires a task")
    workspace = Path(value["workspace"]).resolve(strict=True)
    if not workspace.is_dir():
        raise ValueError("Manifest workspace must be a directory")
    endpoint = urlsplit(value["mcp_endpoint"])
    if endpoint.scheme != "http" or endpoint.hostname not in {"localhost", "127.0.0.1", "::1"} or endpoint.path != "/sse":
        raise ValueError("Runner requires the harness's local SSE endpoint")
    selectors = parse_qs(endpoint.query).get("db", [])
    if len(selectors) != 1 or not selectors[0].startswith("file://"):
        raise ValueError("Runner requires one disposable file-store selector")
    directory = Path(unquote(selectors[0][7:])).resolve()
    if not directory.is_relative_to(workspace) or directory == workspace:
        raise ValueError("Memory store must be inside the isolated workspace")
    for name, maximum in (("max_tool_calls", 60), ("timeout_seconds", 300)):
        number = value.get(name)
        if type(number) is not int or not 1 <= number <= maximum:
            raise ValueError(f"{name} must be between 1 and {maximum}")
    if not isinstance(value.get("skills"), list) or not value["skills"]:
        raise ValueError("Manifest requires skill paths")
    return {**value, "workspace": str(workspace)}


def build_prompt(manifest: dict) -> str:
    skills = []
    for filename in manifest["skills"]:
        path = Path(filename)
        skills.append(f"<skill name={json.dumps(path.parent.name)}>\n{path.read_text()}\n</skill>")
    return (
        "You are an external agent using Remind's durable memory tools. This is a fresh session. "
        "Use only the supplied Remind MCP tools for memory. Previous conversations are unavailable. "
        "Follow the supplied skills. Do not access files, evaluation data, grading rubrics, or transcripts. "
        "The skills are included below; their CLI examples also describe the corresponding MCP tools. "
        "Use the tool schemas to supply MCP arguments. Obtain current revisions through snapshot "
        "before editing existing records. Do not invent revisions or record IDs. "
        "A read-only task permits recall and snapshot only. "
        "Complete the requested task autonomously, then give a concise natural-language answer "
        "with supporting record IDs. Do not produce or invent a tool-call transcript. "
        f"You have at most {manifest['max_tool_calls']} tool calls.\n\n"
        + "\n\n".join(skills) + "\n\n<task>\n" + manifest["task"] + "\n</task>"
    )


def read_transcript(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


class RecordingBridge:
    """Record actual requests and responses, enforcing one shared call budget."""

    def __init__(self, session: Any, transcript: Path, max_calls: int,
                 tools: Optional[set[str]] = None):
        self.session, self.transcript, self.max_calls = session, transcript, max_calls
        self.tools = ALLOWED_TOOLS if tools is None else tools
        self.calls = sum(event["type"] == "tool_call" for event in read_transcript(transcript))
        self.lock = asyncio.Lock()

    def record(self, event: dict) -> None:
        with self.transcript.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
            handle.flush()

    async def call(self, name: str, arguments: Optional[dict]) -> Any:
        async with self.lock:
            self.calls += 1
            self.record({"type": "tool_call", "name": name, "arguments": arguments or {}})
            try:
                if self.calls > self.max_calls:
                    raise ValueError("Tool-call budget exceeded")
                if name not in self.tools:
                    raise ValueError(f"Tool is not available in this evaluation: {name}")
                result = await self.session.call_tool(name, arguments or {})
            except Exception as exc:
                self.record({"type": "tool_result", "name": name, "error": str(exc)})
                raise
            self.record({"type": "tool_result", "name": name, "result": result.model_dump(mode="json", exclude_none=True)})
            return result


async def serve_bridge(state_path: Path) -> None:
    from mcp import ClientSession
    from mcp.client.sse import sse_client
    from mcp.server import Server
    from mcp.server.stdio import stdio_server

    state = json.loads(state_path.read_text())
    async with sse_client(state["endpoint"]) as streams:
        async with ClientSession(*streams) as session:
            initialized = await session.initialize()
            tools = CORE_TOOLS if state.get("tool_profile") == "core" else ALLOWED_TOOLS
            bridge = RecordingBridge(session, Path(state["transcript"]), state["max_calls"], tools)
            server = Server("remind-evaluation-bridge", version=RUNNER_VERSION,
                            instructions=initialized.instructions)

            @server.list_tools()
            async def list_tools():
                result = await session.list_tools()
                return [tool for tool in result.tools if tool.name in tools]

            # Record malformed requests as well; the upstream server validates input.
            @server.call_tool(validate_input=False)
            async def call_tool(name: str, arguments: dict):
                return await bridge.call(name, arguments)

            async with stdio_server() as (reader, writer):
                await server.run(reader, writer, server.create_initialization_options())


def codex_command(binary: str, model: str, reasoning: str, workspace: str,
                  state: Path, answer: Path) -> list[str]:
    command = [binary, "exec", "--json", "--ephemeral", "--ignore-user-config", "--ignore-rules",
               "--skip-git-repo-check", "--sandbox", "read-only", "--cd", workspace,
               "--model", model, "--output-last-message", str(answer)]
    settings = {
        "model_reasoning_effort": reasoning,
        "approval_policy": "never",
        "web_search": "disabled",
        "features.shell_tool": False,
        "features.multi_agent": False,
        "features.apps": False,
        "mcp_servers.remind.command": sys.executable,
        "mcp_servers.remind.args": [str(Path(__file__).resolve()), "--bridge", str(state)],
        "mcp_servers.remind.required": True,
        "mcp_servers.remind.startup_timeout_sec": 30,
        "mcp_servers.remind.tool_timeout_sec": 60,
        # These tools operate only on the caller's disposable test store.
        "mcp_servers.remind.default_tools_approval_mode": "approve",
    }
    for key, value in settings.items():
        command += ["-c", key + "=" + json.dumps(value)]
    return command + ["-"]


def execute(command: list[str], prompt: str, timeout: int) -> tuple[int, str, str]:
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, start_new_session=True)
    try:
        stdout, stderr = process.communicate(prompt, timeout=timeout)
        return process.returncode, stdout, stderr
    finally:
        # A CLI timeout must also stop its MCP bridge, including orphaned children.
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        if process.poll() is None:
            try:
                process.communicate(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.communicate()


def parse_events(stdout: str) -> tuple[list[dict], dict]:
    events, usage = [], {}
    for line in stdout.splitlines():
        event = json.loads(line)
        events.append(event)
        if event.get("type") == "turn.completed":
            usage = event.get("usage", {})
        item = event.get("item", {})
        if item.get("type") == "mcp_tool_call" and item.get("server") != "remind":
            raise ValueError("Unexpected MCP server used")
        if item.get("type") in {"command_execution", "file_change", "web_search"}:
            raise ValueError(f"Unexpected non-MCP tool used: {item['type']}")
        if event.get("type") in {"error", "turn.failed"}:
            raise RuntimeError(json.dumps(event))
    if not any(e.get("type") == "turn.completed" for e in events):
        raise RuntimeError("Codex exited without a completed turn")
    return events, usage


def run(manifest: dict, model: str, reasoning: str, binary: str = "codex",
        tool_profile: str = "extended") -> dict:
    manifest = validate_manifest(manifest)
    resolved = shutil.which(binary)
    if resolved is None:
        raise ValueError(f"Codex executable not found: {binary}")
    version = subprocess.run([resolved, "--version"], capture_output=True, text=True, check=True, timeout=10).stdout.strip()
    prompt = build_prompt(manifest)
    artifacts = manifest.get("runner_artifacts")
    if artifacts:
        artifact_path = Path(artifacts).resolve()
        if artifact_path.is_relative_to(Path(manifest["workspace"])):
            raise ValueError("Runner artifacts must be outside the agent workspace")
        artifact_path.mkdir(parents=True, exist_ok=True)
    context = nullcontext(str(artifact_path)) if artifacts else tempfile.TemporaryDirectory(prefix="remind-codex-")
    with context as temporary:
        directory = Path(temporary)
        state, transcript, answer = (directory / name for name in ("bridge.json", "transcript.jsonl", "answer.txt"))
        state.write_text(json.dumps({"endpoint": manifest["mcp_endpoint"], "transcript": str(transcript),
                                     "max_calls": manifest["max_tool_calls"], "tool_profile": tool_profile}))
        command = codex_command(resolved, model, reasoning, manifest["workspace"], state, answer)
        try:
            code, stdout, stderr = execute(command, prompt, max(1, manifest["timeout_seconds"] - 15))
        except subprocess.TimeoutExpired as exc:
            for name, output in (("codex.jsonl", exc.stdout), ("codex.stderr", exc.stderr)):
                if isinstance(output, bytes):
                    output = output.decode(errors="replace")
                (directory / name).write_text(output or "")
            raise
        (directory / "codex.jsonl").write_text(stdout)
        (directory / "codex.stderr").write_text(stderr)
        if stderr:
            print(stderr, file=sys.stderr, end="" if stderr.endswith("\n") else "\n")
        if code:
            raise RuntimeError(f"Codex exited {code}: {(stderr + stdout)[-6000:]}")
        events, usage = parse_events(stdout)
        observed = read_transcript(transcript)
        calls = [event for event in observed if event["type"] == "tool_call"]
        if not calls:
            text = answer.read_text() if answer.exists() else ""
            raise RuntimeError(f"Codex completed without any observed Remind tool calls: {text[-4000:]}")
        if len(calls) > manifest["max_tool_calls"]:
            raise RuntimeError("Tool-call budget exceeded")
        text = answer.read_text() if answer.exists() else ""
        if not text.strip():
            raise RuntimeError("Codex did not produce a final answer")
        return {"runner": {"name": "codex-cli", "version": RUNNER_VERSION, "cli_version": version,
                           "model": model, "reasoning_effort": reasoning, "seed_supported": False,
                           "tool_profile": tool_profile},
                "answer": text, "transcript": observed, "usage": usage, "events": events}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="gpt-6-luna")
    parser.add_argument("--reasoning-effort", choices=["low", "medium", "high", "xhigh", "max"], default="medium")
    parser.add_argument("--codex", default="codex", help="Codex executable name or path")
    parser.add_argument("--tool-profile", choices=["core", "extended"], default="extended",
                        help="Use the original four tools or include batch capture and inspection")
    parser.add_argument("--bridge", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        if args.bridge:
            asyncio.run(serve_bridge(args.bridge))
        else:
            result = run(json.load(sys.stdin), args.model, args.reasoning_effort, args.codex, args.tool_profile)
            print(json.dumps(result, ensure_ascii=False))
    except Exception as exc:
        print(f"Codex runner failed: {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()

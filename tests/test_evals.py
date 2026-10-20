"""The evaluator must report unconfigured or empty runs as incomplete."""
from argparse import Namespace
import json

import pytest

from remind.evals import agent_suite, dataset, run


@pytest.mark.asyncio
async def test_missing_agent_runner_is_not_a_pass(tmp_path):
    result = await agent_suite(dataset(), Namespace(agent_command=None), tmp_path)
    assert result["status"] == "not_run"
    assert not result["cases"]


@pytest.mark.asyncio
async def test_empty_operational_selection_fails_and_records_dataset(tmp_path):
    args = Namespace(output=str(tmp_path), suite="operational", scenario="nonexistent",
                     transports="python", backend=None, baseline=None)
    assert await run(args) == 1
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["suites"]["operational"]["status"] == "failed"
    assert report["dataset_digest"]


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["lifecycle", "conflicts", "restart", "roundtrip", "retry_failure"])
async def test_python_operational_fixture_contract(tmp_path, variant):
    from remind.evals import operational_case
    data = dataset()
    case = next(c for c in data["operational"] if c["id"] == "architecture." + variant)
    family = next(f for f in data["families"] if f["id"] == "architecture")
    assert (await operational_case(case, family, "python", (tmp_path / "memory").as_uri(), tmp_path))["passed"]


@pytest.mark.asyncio
async def test_operational_evaluation_refuses_nonempty_store(tmp_path):
    from remind.evals import operational_case, PythonAdapter
    selector = (tmp_path / "memory").as_uri()
    client = PythonAdapter(selector)
    try:
        await client.call("remember", {"content": "Existing user memory"})
    finally:
        await client.close()
    data = dataset()
    case, family = data["operational"][0], data["families"][0]
    with pytest.raises(ValueError, match="empty disposable store"):
        await operational_case(case, family, "python", selector, tmp_path)
    client = PythonAdapter(selector)
    try:
        assert client.memory.store.get_all_episodes()[0].content == "Existing user memory"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_run_reports_baseline_regression_without_rewriting_baseline(tmp_path, monkeypatch):
    import remind.evals as evals
    baseline = tmp_path / "baseline.json"
    content = json.dumps({"suites": {"operational": {"cases": [
        {"id": "architecture.lifecycle", "transport": "python", "passed": True}]}}})
    baseline.write_text(content)
    async def failure(*args):
        raise RuntimeError("Injected transport failure")
    monkeypatch.setattr(evals, "operational_case", failure)
    args = Namespace(output=str(tmp_path / "reports"), suite="operational", scenario="architecture.lifecycle",
                     transports="python", backend=None, baseline=str(baseline))
    assert await run(args) == 1
    report = json.loads((tmp_path / "reports/report.json").read_text())
    assert len(report["baseline"]["regressions"]) == 1
    assert "Injected transport failure" in report["suites"]["operational"]["cases"][0]["error"]
    assert baseline.read_text() == content


@pytest.mark.asyncio
async def test_run_records_passing_operational_suite(tmp_path):
    args = Namespace(output=str(tmp_path / "reports"), suite="operational", scenario="architecture.lifecycle",
                     transports="python", backend=None, baseline=None)
    assert await run(args) == 0
    report = json.loads((tmp_path / "reports/report.json").read_text())
    assert report["suites"]["operational"]["cases"][0]["passed"]
    assert "| operational | passed | 1 |" in (tmp_path / "reports/report.md").read_text()

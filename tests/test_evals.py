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

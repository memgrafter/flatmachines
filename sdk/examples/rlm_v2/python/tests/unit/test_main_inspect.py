from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from rlm_v2 import main as main_module


class _FakeMachine:
    def __init__(self, config_file: str):
        self.config_file = config_file
        self.total_api_calls = 0
        self.total_cost = 0.0

    async def execute(self, input: dict[str, Any], max_steps: int) -> dict[str, Any]:
        return {
            "answer": "ok",
            "reason": "final",
            "iteration": 1,
            "depth": input.get("current_depth", 0),
        }


@pytest.mark.asyncio
async def test_run_rlm_v2_writes_manifest_in_inspect_mode(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "machine.yml"
    config_path.write_text("spec: flatmachine\n")

    monkeypatch.setattr(main_module, "_config_path", lambda: config_path)
    monkeypatch.setattr(main_module, "FlatMachine", _FakeMachine)

    result = await main_module.run_rlm_v2(
        task="test task",
        long_context="abcdef",
        inspect=True,
        inspect_level="summary",
        trace_dir=str(tmp_path / "traces"),
        experiment="unit-test",
        tags={"suite": "unit"},
    )

    assert result["reason"] == "final"

    traces_root = tmp_path / "traces"
    run_dirs = [p for p in traces_root.iterdir() if p.is_dir()]
    assert len(run_dirs) == 1

    manifest = json.loads((run_dirs[0] / "manifest.json").read_text())
    assert manifest["mode"] == "rlm_v2_inspect"
    assert manifest["input"]["task"] == "test task"
    assert manifest["limits"]["max_depth"] == 5
    assert manifest["experiment"] == "unit-test"

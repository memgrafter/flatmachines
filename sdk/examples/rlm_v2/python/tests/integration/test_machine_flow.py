from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import pytest

from flatmachines import (
    AgentAdapter,
    AgentAdapterContext,
    AgentAdapterRegistry,
    AgentExecutor,
    AgentRef,
    AgentResult,
    FlatMachine,
)


def _machine_config_path() -> Path:
    # tests/integration -> tests -> python -> rlm_v2(example root)
    return Path(__file__).resolve().parents[3] / "config" / "machine.yml"


class ScriptedExecutor(AgentExecutor):
    def __init__(self, script: Callable[[Dict[str, Any], Dict[str, Any]], str]):
        self._script = script

    @property
    def metadata(self) -> Dict[str, Any]:
        return {}

    async def execute(
        self,
        input_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> AgentResult:
        output = self._script(input_data, context or {})
        return AgentResult(content=output)


class ScriptedFlatAgentAdapter(AgentAdapter):
    type_name = "flatagent"

    def __init__(self, script: Callable[[Dict[str, Any], Dict[str, Any]], str]):
        self._script = script

    def create_executor(
        self,
        *,
        agent_name: str,
        agent_ref: AgentRef,
        context: AgentAdapterContext,
    ) -> AgentExecutor:
        return ScriptedExecutor(self._script)


def _build_machine(script: Callable[[Dict[str, Any], Dict[str, Any]], str]) -> FlatMachine:
    config_path = _machine_config_path()
    registry = AgentAdapterRegistry([ScriptedFlatAgentAdapter(script)])
    return FlatMachine(config_file=str(config_path), agent_registry=registry)


def _base_input() -> dict[str, Any]:
    config_path = _machine_config_path()
    return {
        "task": "Test task",
        "long_context": "Very long context text used only in REPL.",
        "current_depth": 0,
        "max_depth": 5,
        "timeout_seconds": 300,
        "max_iterations": 20,
        "max_steps": 80,
        "machine_config_path": str(config_path),
    }


@pytest.mark.asyncio
async def test_machine_reaches_final_and_keeps_long_context_out_of_agent_input() -> None:
    seen_inputs: list[dict[str, Any]] = []

    def script(input_data: Dict[str, Any], context: Dict[str, Any]) -> str:
        seen_inputs.append(dict(input_data))
        if int(context.get("iteration", 0)) == 0:
            return "```repl\nscratch = context[:20]\nprint('iter0')\n```"
        return "```repl\nFinal = 'done'\n```"

    machine = _build_machine(script)
    result = await machine.execute(input=_base_input(), max_steps=80)

    assert result["reason"] == "final"
    assert result["answer"] == "done"
    assert result["iteration"] == 2

    # Ensure root agent input never receives full long_context directly.
    assert seen_inputs
    for payload in seen_inputs:
        assert "long_context" not in payload
        assert "task" in payload
        assert "context_length" in payload


@pytest.mark.asyncio
async def test_strict_final_accepts_falsy_boolean() -> None:
    def script(input_data: Dict[str, Any], context: Dict[str, Any]) -> str:
        return "```repl\nFinal = False\n```"

    machine = _build_machine(script)
    result = await machine.execute(input=_base_input(), max_steps=80)

    assert result["reason"] == "final"
    assert result["answer"] is False


@pytest.mark.asyncio
async def test_loop_hint_is_propagated_into_coder_input_after_repetition() -> None:
    seen_inputs: list[dict[str, Any]] = []

    def script(input_data: Dict[str, Any], context: Dict[str, Any]) -> str:
        seen_inputs.append(dict(input_data))
        if int(context.get("iteration", 0)) < 3:
            return "```repl\nprint(context)\n```"
        return "```repl\nFinal = 'done'\n```"

    machine = _build_machine(script)
    result = await machine.execute(input=_base_input(), max_steps=80)

    assert result["reason"] == "final"
    assert result["answer"] == "done"

    assert any(int(payload.get("repeat_streak", 0)) >= 2 for payload in seen_inputs)
    assert any("repeating near-identical REPL actions" in str(payload.get("loop_hint", "")) for payload in seen_inputs)


@pytest.mark.asyncio
async def test_llm_query_path_returns_config_sentinel_when_subcall_machine_missing() -> None:
    def script(input_data: Dict[str, Any], context: Dict[str, Any]) -> str:
        return "```repl\ntmp = llm_query('nested request')\nFinal = tmp\n```"

    machine = _build_machine(script)
    payload = _base_input()
    payload["machine_config_path"] = "/tmp/does-not-exist-machine.yml"

    result = await machine.execute(input=payload, max_steps=80)

    assert result["reason"] == "final"
    assert result["answer"] == "SUBCALL_CONFIG_NOT_FOUND"


@pytest.mark.asyncio
async def test_max_iterations_terminal_state() -> None:
    def script(input_data: Dict[str, Any], context: Dict[str, Any]) -> str:
        return "```repl\nprint('still working')\n```"

    payload = _base_input()
    payload["max_iterations"] = 2

    machine = _build_machine(script)
    result = await machine.execute(input=payload, max_steps=80)

    assert result["reason"] == "max_iterations"
    assert result["iteration"] == 2
    assert "still working" in str(result["answer"])


@pytest.mark.asyncio
async def test_inspect_mode_writes_trace_events(tmp_path: Path) -> None:
    def script(input_data: Dict[str, Any], context: Dict[str, Any]) -> str:
        return "```repl\nFinal = 'done'\nprint('ok')\n```"

    payload = _base_input()
    payload.update(
        {
            "inspect": True,
            "inspect_level": "summary",
            "trace_dir": str(tmp_path),
            "root_run_id": "inspect-root-1",
            "print_iterations": False,
            "experiment": "int-test",
            "tags": {"suite": "integration"},
        }
    )

    machine = _build_machine(script)
    result = await machine.execute(input=payload, max_steps=80)

    assert result["reason"] == "final"

    events_file = tmp_path / "inspect-root-1" / "events.jsonl"
    assert events_file.exists()

    events = [json.loads(line) for line in events_file.read_text().splitlines() if line.strip()]
    event_names = {e["event"] for e in events}

    assert "run_start" in event_names
    assert "iteration_start" in event_names
    assert "llm_response" in event_names
    assert "code_blocks_extracted" in event_names
    assert "repl_exec" in event_names
    assert "final_detected" in event_names
    assert "run_end" in event_names


@pytest.mark.asyncio
async def test_inspect_mode_records_subcall_start_and_end(tmp_path: Path) -> None:
    def script(input_data: Dict[str, Any], context: Dict[str, Any]) -> str:
        return "```repl\nsub = llm_query('nested request')\nFinal = sub\n```"

    payload = _base_input()
    payload.update(
        {
            "inspect": True,
            "inspect_level": "summary",
            "trace_dir": str(tmp_path),
            "root_run_id": "inspect-root-2",
            "machine_config_path": "/tmp/does-not-exist-machine.yml",
        }
    )

    machine = _build_machine(script)
    result = await machine.execute(input=payload, max_steps=80)

    assert result["reason"] == "final"
    assert result["answer"] == "SUBCALL_CONFIG_NOT_FOUND"

    events_file = tmp_path / "inspect-root-2" / "events.jsonl"
    events = [json.loads(line) for line in events_file.read_text().splitlines() if line.strip()]

    starts = [e for e in events if e.get("event") == "subcall_start"]
    ends = [e for e in events if e.get("event") == "subcall_end"]

    assert len(starts) == 1
    assert len(ends) == 1
    assert starts[0]["call_id"] == ends[0]["call_id"]
    assert ends[0]["status"] == "config_not_found"

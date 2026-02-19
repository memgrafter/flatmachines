from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from rlm_v2.hooks import RLMV2Hooks, RecursionInvoker
from rlm_v2.repl import REPLRegistry


def _machine_config_path() -> str:
    # tests/unit -> tests -> python -> rlm_v2 -> examples
    return str(Path(__file__).resolve().parents[3] / "config" / "machine.yml")


def test_init_session_coerces_types_and_sets_metadata() -> None:
    hooks = RLMV2Hooks()
    context = {
        "task": "test",
        "long_context": "abcdef",
        "current_depth": "0",
        "max_depth": "5",
        "timeout_seconds": "300",
        "max_iterations": "20",
        "max_steps": "80",
        "machine_config_path": _machine_config_path(),
    }

    updated = hooks.on_action("init_session", context)

    assert isinstance(updated["current_depth"], int)
    assert isinstance(updated["max_depth"], int)
    assert updated["context_length"] == 6
    assert updated["context_prefix"] == "abcdef"
    assert REPLRegistry.has_session(updated["session_id"])


def test_check_final_accepts_zero_value() -> None:
    hooks = RLMV2Hooks()
    context = {
        "task": "test",
        "long_context": "abcdef",
        "machine_config_path": _machine_config_path(),
    }

    context = hooks.on_action("init_session", context)
    context["raw_response"] = "```repl\nFinal = 0\n```"
    context = hooks.on_action("execute_response_code", context)
    context = hooks.on_action("check_final", context)

    assert context["is_final"] is True
    assert context["final_answer"] == 0


def test_history_meta_is_bounded_to_five_entries() -> None:
    hooks = RLMV2Hooks()
    context = {
        "task": "test",
        "long_context": "abcdef",
        "machine_config_path": _machine_config_path(),
    }
    context = hooks.on_action("init_session", context)

    for i in range(7):
        context["raw_response"] = f"```repl\nvalue_{i} = {i}\nprint(value_{i})\n```"
        context = hooks.on_action("execute_response_code", context)

    assert len(context["history_meta"]) == 5
    assert context["history_meta"][0]["iteration"] == 3
    assert context["history_meta"][-1]["iteration"] == 7


def test_loop_hint_sets_after_repeated_near_identical_code() -> None:
    hooks = RLMV2Hooks()
    context = {
        "task": "test",
        "long_context": "abcdef",
        "machine_config_path": _machine_config_path(),
    }
    context = hooks.on_action("init_session", context)

    repeated = "```repl\nprint(context)\n```"
    context["raw_response"] = repeated
    context = hooks.on_action("execute_response_code", context)
    assert context["repeat_streak"] == 0
    assert context["loop_hint"] == ""

    context["raw_response"] = repeated
    context = hooks.on_action("execute_response_code", context)
    assert context["repeat_streak"] == 1
    assert context["loop_hint"] == ""

    context["raw_response"] = repeated
    context = hooks.on_action("execute_response_code", context)
    assert context["repeat_streak"] == 2
    assert "repeating near-identical REPL actions" in context["loop_hint"]


def test_loop_hint_detects_repeat_with_comment_variation() -> None:
    hooks = RLMV2Hooks()
    context = {
        "task": "test",
        "long_context": "abcdef",
        "machine_config_path": _machine_config_path(),
    }
    context = hooks.on_action("init_session", context)

    first = """```repl
# first pass
print(context)
```"""
    second = """```repl
# second pass with changed comment
print(context)
```"""
    third = """```repl
# third pass, same code again
print(context)
```"""

    context["raw_response"] = first
    context = hooks.on_action("execute_response_code", context)
    assert context["repeat_streak"] == 0

    context["raw_response"] = second
    context = hooks.on_action("execute_response_code", context)
    assert context["repeat_streak"] == 1

    context["raw_response"] = third
    context = hooks.on_action("execute_response_code", context)
    assert context["repeat_streak"] == 2
    assert "repeating near-identical REPL actions" in context["loop_hint"]



def test_recursion_invoker_depth_limit() -> None:
    invoker = RecursionInvoker()
    response = invoker.invoke(
        prompt="hello",
        parent_context={
            "machine_config_path": _machine_config_path(),
            "current_depth": 5,
            "max_depth": 5,
            "timeout_seconds": 300,
            "max_iterations": 20,
            "max_steps": 80,
        },
    )

    assert response == "SUBCALL_DEPTH_LIMIT"


def test_recursion_invoker_missing_config() -> None:
    invoker = RecursionInvoker()
    response = invoker.invoke(
        prompt="hello",
        parent_context={
            "current_depth": 0,
            "max_depth": 5,
        },
    )

    assert response == "SUBCALL_NOT_CONFIGURED"


def test_recursion_invoker_success_with_mock_machine(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config_path = tmp_path / "machine.yml"
    config_path.write_text("spec: flatmachine\n")

    captured: dict[str, Any] = {}

    class FakeMachine:
        def __init__(self, config_file: str):
            captured["config_file"] = config_file

        def execute_sync(self, input: dict[str, Any], max_steps: int) -> dict[str, Any]:
            captured["input"] = input
            captured["max_steps"] = max_steps
            return {"answer": "sub-result"}

    monkeypatch.setattr("rlm_v2.hooks.FlatMachine", FakeMachine)

    invoker = RecursionInvoker()
    response = invoker.invoke(
        prompt="hello",
        parent_context={
            "machine_config_path": str(config_path),
            "current_depth": 0,
            "max_depth": 5,
            "timeout_seconds": 300,
            "max_iterations": 20,
            "max_steps": 80,
            "sub_model_profile": "subcall",
        },
        model="override-model",
    )

    assert response == "sub-result"
    assert captured["config_file"] == str(config_path)
    assert captured["max_steps"] == 80
    assert captured["input"]["current_depth"] == 1
    assert captured["input"]["long_context"] == "hello"
    assert captured["input"]["model_override"] == "override-model"

"""Tests for event constructors and types."""

import pytest
from flatmachines_cli.events import (
    MACHINE_START, MACHINE_END, STATE_ENTER, STATE_EXIT,
    TRANSITION, TOOL_CALLS, TOOL_RESULT, ACTION, ERROR,
    ALL_TYPES,
    machine_start, machine_end, state_enter, state_exit,
    transition, tool_calls, tool_result, action, error,
)


class TestEventConstants:
    def test_all_types_are_strings(self):
        for t in ALL_TYPES:
            assert isinstance(t, str)

    def test_all_types_unique(self):
        assert len(ALL_TYPES) == 9

    def test_all_types_contains_all_constants(self):
        expected = {
            MACHINE_START, MACHINE_END, STATE_ENTER, STATE_EXIT,
            TRANSITION, TOOL_CALLS, TOOL_RESULT, ACTION, ERROR,
        }
        assert ALL_TYPES == expected

    def test_all_types_is_frozenset(self):
        assert isinstance(ALL_TYPES, frozenset)


class TestMachineStartEvent:
    def test_basic(self):
        ctx = {"machine": {"machine_name": "test", "execution_id": "abc"}}
        evt = machine_start(ctx)
        assert evt["type"] == MACHINE_START
        assert evt["machine_name"] == "test"
        assert evt["execution_id"] == "abc"
        assert evt["context"] is ctx

    def test_missing_machine_meta(self):
        evt = machine_start({})
        assert evt["machine_name"] == ""
        assert evt["execution_id"] == ""

    def test_context_preserved(self):
        ctx = {"extra": "data", "machine": {}}
        evt = machine_start(ctx)
        assert evt["context"]["extra"] == "data"


class TestMachineEndEvent:
    def test_basic(self):
        ctx = {"result": "done"}
        output = {"output_key": "val"}
        evt = machine_end(ctx, output)
        assert evt["type"] == MACHINE_END
        assert evt["final_output"] is output
        assert evt["context"] is ctx

    def test_empty_output(self):
        evt = machine_end({}, {})
        assert evt["final_output"] == {}


class TestStateEnterEvent:
    def test_basic(self):
        ctx = {"machine": {"step": 3}}
        evt = state_enter("my_state", ctx)
        assert evt["type"] == STATE_ENTER
        assert evt["state"] == "my_state"
        assert evt["step"] == 3

    def test_missing_step(self):
        evt = state_enter("s", {})
        assert evt["step"] == 0

    def test_context_preserved(self):
        ctx = {"key": "val"}
        evt = state_enter("s", ctx)
        assert evt["context"] is ctx


class TestStateExitEvent:
    def test_basic(self):
        ctx = {"x": 1}
        output = {"result": "y"}
        evt = state_exit("s", ctx, output)
        assert evt["type"] == STATE_EXIT
        assert evt["state"] == "s"
        assert evt["output"] is output

    def test_none_output(self):
        evt = state_exit("s", {}, None)
        assert evt["output"] is None


class TestTransitionEvent:
    def test_basic(self):
        ctx = {"x": 1}
        evt = transition("from_s", "to_s", ctx)
        assert evt["type"] == TRANSITION
        assert evt["from_state"] == "from_s"
        assert evt["to_state"] == "to_s"


class TestToolCallsEvent:
    def test_basic(self):
        ctx = {
            "_tool_loop_content": "thinking...",
            "_tool_loop_usage": {"input_tokens": 100},
            "_tool_loop_cost": 0.01,
            "_tool_loop_turns": 2,
        }
        calls = [{"name": "bash", "arguments": {"command": "ls"}}]
        evt = tool_calls("state1", calls, ctx)
        assert evt["type"] == TOOL_CALLS
        assert evt["state"] == "state1"
        assert evt["tool_calls"] == calls
        assert evt["content"] == "thinking..."
        assert evt["usage"]["input_tokens"] == 100
        assert evt["cost"] == 0.01
        assert evt["turns"] == 2

    def test_missing_internal_keys(self):
        evt = tool_calls("s", [], {})
        assert evt["content"] == ""
        assert evt["usage"] == {}
        assert evt["cost"] == 0.0
        assert evt["turns"] == 0


class TestToolResultEvent:
    def test_basic(self):
        result = {
            "name": "bash",
            "arguments": {"command": "ls"},
            "content": "file1\nfile2",
            "is_error": False,
            "tool_call_id": "tc_123",
        }
        evt = tool_result("s1", result, {})
        assert evt["type"] == TOOL_RESULT
        assert evt["name"] == "bash"
        assert evt["content"] == "file1\nfile2"
        assert evt["is_error"] is False
        assert evt["tool_call_id"] == "tc_123"

    def test_missing_fields(self):
        evt = tool_result("s", {}, {})
        assert evt["name"] == ""
        assert evt["content"] == ""
        assert evt["is_error"] is False
        assert evt["tool_call_id"] == ""

    def test_error_result(self):
        result = {"name": "bash", "is_error": True, "content": "command not found"}
        evt = tool_result("s", result, {})
        assert evt["is_error"] is True


class TestActionEvent:
    def test_basic(self):
        ctx = {"task": "review"}
        evt = action("human_review", ctx)
        assert evt["type"] == ACTION
        assert evt["action"] == "human_review"
        assert evt["context"] is ctx


class TestErrorEvent:
    def test_basic(self):
        exc = ValueError("bad input")
        evt = error("state1", exc, {"x": 1})
        assert evt["type"] == ERROR
        assert evt["state"] == "state1"
        assert evt["error_type"] == "ValueError"
        assert evt["error_message"] == "bad input"

    def test_preserves_exception_type(self):
        class CustomError(Exception):
            pass
        exc = CustomError("custom")
        evt = error("s", exc, {})
        assert evt["error_type"] == "CustomError"
        assert evt["error_message"] == "custom"

    def test_empty_exception(self):
        exc = RuntimeError()
        evt = error("s", exc, {})
        assert evt["error_type"] == "RuntimeError"
        assert evt["error_message"] == ""

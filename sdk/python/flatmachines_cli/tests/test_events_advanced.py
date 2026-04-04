"""Advanced event tests — serialization, immutability, edge cases."""

import json
import pytest
from flatmachines_cli.events import (
    MACHINE_START, MACHINE_END, STATE_ENTER, STATE_EXIT,
    TRANSITION, TOOL_CALLS, TOOL_RESULT, ACTION, ERROR,
    ALL_TYPES,
    machine_start, machine_end, state_enter, state_exit,
    transition, tool_calls, tool_result, action, error,
)


class TestEventSerialization:
    """All events should be JSON-serializable."""

    def test_machine_start_serializable(self):
        evt = machine_start({"machine": {"machine_name": "test", "execution_id": "e1"}})
        json.dumps(evt)

    def test_machine_end_serializable(self):
        evt = machine_end({"result": "done"}, {"output": True})
        json.dumps(evt)

    def test_state_enter_serializable(self):
        evt = state_enter("s1", {"machine": {"step": 1}})
        json.dumps(evt)

    def test_state_exit_serializable(self):
        evt = state_exit("s1", {}, {"data": [1, 2]})
        json.dumps(evt)

    def test_transition_serializable(self):
        evt = transition("from", "to", {"key": "val"})
        json.dumps(evt)

    def test_tool_calls_serializable(self):
        evt = tool_calls("s", [{"name": "bash", "arguments": {"cmd": "ls"}}], {
            "_tool_loop_content": "thinking",
            "_tool_loop_usage": {"input_tokens": 100},
            "_tool_loop_cost": 0.01,
            "_tool_loop_turns": 1,
        })
        json.dumps(evt)

    def test_tool_result_serializable(self):
        evt = tool_result("s", {
            "name": "bash",
            "arguments": {"command": "ls"},
            "content": "file.py",
            "is_error": False,
            "tool_call_id": "tc_1",
        }, {})
        json.dumps(evt)

    def test_action_serializable(self):
        evt = action("human_review", {"task": "check"})
        json.dumps(evt)

    def test_error_serializable(self):
        evt = error("s1", ValueError("bad"), {"step": 1})
        json.dumps(evt)


class TestEventImmutability:
    """Events should not mutate the input context."""

    def test_machine_start_doesnt_mutate(self):
        ctx = {"machine": {"machine_name": "test"}, "extra": "data"}
        original_keys = set(ctx.keys())
        machine_start(ctx)
        assert set(ctx.keys()) == original_keys

    def test_state_enter_doesnt_mutate(self):
        ctx = {"machine": {"step": 1}}
        original = dict(ctx)
        state_enter("s", ctx)
        assert ctx == original

    def test_error_doesnt_mutate(self):
        ctx = {"key": "val"}
        original = dict(ctx)
        error("s", ValueError("e"), ctx)
        assert ctx == original


class TestEventContextReference:
    """Events should store references, not copies of context."""

    def test_machine_start_shares_context(self):
        ctx = {"machine": {}, "mutable": [1, 2]}
        evt = machine_start(ctx)
        assert evt["context"] is ctx

    def test_state_enter_shares_context(self):
        ctx = {"machine": {}}
        evt = state_enter("s", ctx)
        assert evt["context"] is ctx

    def test_tool_calls_shares_context(self):
        ctx = {"data": True}
        evt = tool_calls("s", [], ctx)
        assert evt["context"] is ctx


class TestAllTypesCompleteness:
    """Verify ALL_TYPES matches all available constructor functions."""

    def test_constructors_cover_all_types(self):
        """Each event type should have a constructor."""
        constructor_map = {
            MACHINE_START: machine_start,
            MACHINE_END: machine_end,
            STATE_ENTER: state_enter,
            STATE_EXIT: state_exit,
            TRANSITION: transition,
            TOOL_CALLS: tool_calls,
            TOOL_RESULT: tool_result,
            ACTION: action,
            ERROR: error,
        }
        assert set(constructor_map.keys()) == ALL_TYPES

    def test_type_strings_are_stable(self):
        """Type strings should not change (they're part of the protocol)."""
        assert MACHINE_START == "machine_start"
        assert MACHINE_END == "machine_end"
        assert STATE_ENTER == "state_enter"
        assert STATE_EXIT == "state_exit"
        assert TRANSITION == "transition"
        assert TOOL_CALLS == "tool_calls"
        assert TOOL_RESULT == "tool_result"
        assert ACTION == "action"
        assert ERROR == "error"


class TestEventEdgeCases:
    def test_empty_tool_calls_list(self):
        evt = tool_calls("s", [], {})
        assert evt["tool_calls"] == []
        assert evt["content"] == ""

    def test_tool_result_with_all_fields(self):
        evt = tool_result("s", {
            "name": "custom",
            "arguments": {"a": 1, "b": "two"},
            "content": "big\nmultiline\noutput",
            "is_error": True,
            "tool_call_id": "tc_abc123",
        }, {})
        assert evt["name"] == "custom"
        assert evt["arguments"] == {"a": 1, "b": "two"}
        assert evt["content"] == "big\nmultiline\noutput"
        assert evt["is_error"] is True
        assert evt["tool_call_id"] == "tc_abc123"

    def test_state_exit_with_none_output(self):
        evt = state_exit("s", {}, None)
        assert evt["output"] is None

    def test_error_with_chained_exception(self):
        try:
            try:
                raise ValueError("inner")
            except ValueError:
                raise RuntimeError("outer") from ValueError("inner")
        except RuntimeError as e:
            evt = error("s", e, {})
        assert evt["error_type"] == "RuntimeError"
        assert "outer" in evt["error_message"]

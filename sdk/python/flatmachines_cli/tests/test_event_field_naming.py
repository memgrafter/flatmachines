"""Tests that event field names match what processors expect.

This catches naming mismatches between event constructors and processor
access patterns, like machine_name vs name.
"""

import pytest
from flatmachines_cli import events
from flatmachines_cli.processors import (
    StatusProcessor, TokenProcessor, ToolProcessor,
    ContentProcessor, ErrorProcessor,
)
from flatmachines_cli.bus import DataBus


class TestMachineStartFieldNames:
    def test_machine_name_from_meta(self):
        """machine_start should extract machine_name from context.machine.machine_name."""
        evt = events.machine_start({"machine": {"machine_name": "my_flow"}})
        assert evt["machine_name"] == "my_flow"

    def test_machine_name_missing(self):
        evt = events.machine_start({"machine": {}})
        assert evt["machine_name"] == ""

    def test_execution_id_from_meta(self):
        evt = events.machine_start({"machine": {"execution_id": "exec_001"}})
        assert evt["execution_id"] == "exec_001"

    def test_processor_reads_machine_name(self):
        """StatusProcessor should read machine_name correctly from event."""
        bus = DataBus()
        p = StatusProcessor(bus)
        result = p.process(events.machine_start({
            "machine": {"machine_name": "test_flow", "execution_id": "e1"}
        }))
        assert result["machine_name"] == "test_flow"
        assert result["execution_id"] == "e1"


class TestStateEnterFieldNames:
    def test_state_field(self):
        evt = events.state_enter("init", {"machine": {"step": 0}})
        assert evt["state"] == "init"

    def test_step_field(self):
        evt = events.state_enter("init", {"machine": {"step": 3}})
        assert evt["step"] == 3

    def test_processor_reads_state(self):
        bus = DataBus()
        p = StatusProcessor(bus)
        p.process(events.machine_start({"machine": {}}))
        result = p.process(events.state_enter("running", {"machine": {"step": 2}}))
        assert result["state"] == "running"
        assert result["step"] == 2


class TestToolCallsFieldNames:
    def test_tool_calls_list(self):
        tools = [{"name": "bash", "arguments": {"command": "ls"}}]
        evt = events.tool_calls("s1", tools, {"_tool_loop_usage": {}, "_tool_loop_cost": 0.0})
        assert evt["tool_calls"] == tools

    def test_usage_fields(self):
        evt = events.tool_calls("s1", [], {
            "_tool_loop_usage": {"input_tokens": 100, "output_tokens": 50},
            "_tool_loop_cost": 0.005,
        })
        assert evt["usage"]["input_tokens"] == 100
        assert evt["cost"] == 0.005

    def test_processor_reads_tool_calls(self):
        bus = DataBus()
        p = ToolProcessor(bus)
        # tool_call_id must be the key name the processor looks for
        tools = [{"name": "read", "arguments": {"path": "/tmp/f"}, "tool_call_id": "call_1"}]
        result = p.process(events.tool_calls("s1", tools, {
            "_tool_loop_usage": {},
            "_tool_loop_cost": 0.0,
        }))
        assert len(result["active"]) == 1
        assert result["active"][0]["name"] == "read"
        assert result["active"][0]["tool_call_id"] == "call_1"


class TestToolResultFieldNames:
    def test_result_fields(self):
        evt = events.tool_result("s1", {
            "name": "bash",
            "arguments": {"command": "ls"},
            "content": "file1\nfile2",
            "is_error": False,
            "tool_call_id": "call_1",
        }, {})
        assert evt["name"] == "bash"
        assert evt["is_error"] is False
        assert evt["tool_call_id"] == "call_1"

    def test_missing_tool_call_id(self):
        evt = events.tool_result("s1", {"name": "bash"}, {})
        assert evt["tool_call_id"] == ""


class TestErrorFieldNames:
    def test_error_type_and_message(self):
        evt = events.error("bad_state", ValueError("oops"), {})
        assert evt["error_type"] == "ValueError"
        assert evt["error_message"] == "oops"

    def test_processor_reads_error(self):
        bus = DataBus()
        p = ErrorProcessor(bus)
        result = p.process(events.error("fail", RuntimeError("crash"), {}))
        assert result["has_error"] is True
        assert result["error_type"] == "RuntimeError"
        assert result["error_message"] == "crash"
        assert result["state"] == "fail"

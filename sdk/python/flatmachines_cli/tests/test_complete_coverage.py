"""Tests targeting any remaining uncovered code paths."""

import asyncio
import json
import pytest
from unittest.mock import patch, MagicMock
from flatmachines_cli.bus import DataBus, Slot, SlotValue
from flatmachines_cli.backend import CLIBackend
from flatmachines_cli.processors import (
    StatusProcessor, TokenProcessor, ToolProcessor,
    ContentProcessor, ErrorProcessor, default_processors,
)
from flatmachines_cli.protocol import Frontend, ActionHandler
from flatmachines_cli.frontend import TerminalFrontend
from flatmachines_cli import events


class TestSlotValueDataclass:
    """Cover SlotValue as a data container."""

    def test_data_attribute(self):
        sv = SlotValue(data="test", version=1, timestamp=1.0)
        assert sv.data == "test"
        assert sv.version == 1
        assert sv.timestamp == 1.0

    def test_slot_value_generic(self):
        sv = SlotValue(data=[1, 2, 3], version=5, timestamp=0.5)
        assert sv.data == [1, 2, 3]


class TestProcessorQueueSize:
    def test_default_queue_size(self):
        bus = DataBus()
        p = StatusProcessor(bus)
        assert p._queue.maxsize == 1024

    def test_custom_queue_size(self):
        from flatmachines_cli.processors import Processor

        class Custom(Processor):
            slot_name = "custom"
            def process(self, event):
                return {}

        bus = DataBus()
        p = Custom(bus, queue_size=10)
        assert p._queue.maxsize == 10


class TestProcessorMaxHzZero:
    """max_hz=0 means no throttling."""

    @pytest.mark.asyncio
    async def test_zero_hz_no_buffering(self):
        bus = DataBus()
        p = StatusProcessor(bus, max_hz=0)
        assert p._min_interval == 0.0
        p.start()
        for i in range(5):
            p.enqueue(events.state_enter(f"s_{i}", {"machine": {"step": i}}))
        await asyncio.sleep(0.1)
        p.stop()
        await asyncio.sleep(0.05)
        data = bus.read_data("status")
        assert data is not None


class TestFrontendProtocolNoop:
    def test_on_bus_update_noop(self):
        """Default on_bus_update should be a no-op."""

        class MinimalFrontend(Frontend):
            async def start(self, bus): pass
            async def stop(self): pass
            def handle_action(self, action_name, context): return context

        f = MinimalFrontend()
        f.on_bus_update("slot", {"data": True})  # should not raise
        f.on_bus_update("", None)  # should not raise


class TestBackendRunMachineKwargs:
    """Test that extra kwargs are passed to machine.execute()."""

    @pytest.mark.asyncio
    async def test_extra_kwargs_passed(self):
        from unittest.mock import AsyncMock
        bus = DataBus()
        backend = CLIBackend(bus=bus, processors=[])

        mock_machine = MagicMock()
        mock_machine.execute = AsyncMock(return_value={"result": "ok"})

        await backend.run_machine(
            mock_machine,
            input={"task": "test"},
            resume_from="exec_123",
        )
        call_kwargs = mock_machine.execute.call_args
        assert call_kwargs.kwargs.get("resume_from") == "exec_123"


class TestEventConstructorStability:
    """Verify event dict keys don't change (protocol stability)."""

    def test_machine_start_keys(self):
        evt = events.machine_start({"machine": {}})
        assert set(evt.keys()) == {"type", "machine_name", "execution_id", "context"}

    def test_machine_end_keys(self):
        evt = events.machine_end({}, {})
        assert set(evt.keys()) == {"type", "final_output", "context"}

    def test_state_enter_keys(self):
        evt = events.state_enter("s", {"machine": {}})
        assert set(evt.keys()) == {"type", "state", "step", "context"}

    def test_state_exit_keys(self):
        evt = events.state_exit("s", {}, None)
        assert set(evt.keys()) == {"type", "state", "output", "context"}

    def test_transition_keys(self):
        evt = events.transition("a", "b", {})
        assert set(evt.keys()) == {"type", "from_state", "to_state", "context"}

    def test_tool_calls_keys(self):
        evt = events.tool_calls("s", [], {})
        assert set(evt.keys()) == {"type", "state", "tool_calls", "content", "usage", "cost", "turns", "context"}

    def test_tool_result_keys(self):
        evt = events.tool_result("s", {}, {})
        assert set(evt.keys()) == {"type", "state", "name", "arguments", "content", "is_error", "tool_call_id", "context"}

    def test_action_keys(self):
        evt = events.action("a", {})
        assert set(evt.keys()) == {"type", "action", "context"}

    def test_error_keys(self):
        evt = events.error("s", ValueError("e"), {})
        assert set(evt.keys()) == {"type", "state", "error_type", "error_message", "context"}


class TestToolSummarizeEdgeCases:
    def test_bash_empty_command(self):
        s = ToolProcessor._summarize_tool("bash", {})
        assert s == "bash"

    def test_bash_long_command(self):
        s = ToolProcessor._summarize_tool("bash", {"command": "x" * 200})
        assert len(s) <= 90  # truncated to 80 + "bash: " prefix

    def test_write_no_path(self):
        s = ToolProcessor._summarize_tool("write", {})
        assert "write:" in s

    def test_read_no_path(self):
        s = ToolProcessor._summarize_tool("read", {})
        assert "read:" in s

    def test_edit_no_path(self):
        s = ToolProcessor._summarize_tool("edit", {})
        assert "edit:" in s

    def test_unknown_tool_name(self):
        s = ToolProcessor._summarize_tool("my_custom_tool_v2", {"arg": "val"})
        assert s == "my_custom_tool_v2"


class TestDefaultProcessorInstances:
    def test_all_different_types(self):
        bus = DataBus()
        procs = default_processors(bus)
        types = [type(p).__name__ for p in procs]
        assert len(set(types)) == 5  # all different types

    def test_processor_order(self):
        bus = DataBus()
        procs = default_processors(bus)
        names = [p.slot_name for p in procs]
        assert names == ["status", "tokens", "tools", "content", "error"]

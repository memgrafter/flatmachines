"""Pipeline stress tests — high throughput, many states, large outputs."""

import asyncio
import pytest
from flatmachines_cli.backend import CLIBackend
from flatmachines_cli.bus import DataBus
from flatmachines_cli.processors import (
    StatusProcessor, TokenProcessor, ToolProcessor,
    ContentProcessor, ErrorProcessor,
)
from flatmachines_cli.hooks import CLIHooks
from flatmachines_cli import events


class TestHighThroughputPipeline:
    @pytest.mark.asyncio
    async def test_many_state_transitions(self):
        """Simulate a machine with many state transitions."""
        bus = DataBus()
        procs = [StatusProcessor(bus, max_hz=1000)]
        backend = CLIBackend(bus=bus, processors=procs)
        hooks = CLIHooks(backend)

        await backend.start()

        hooks.on_machine_start({"machine": {"machine_name": "stress"}})
        for i in range(50):
            hooks.on_state_enter(f"state_{i}", {"machine": {"step": i}})
            if i > 0:
                hooks.on_transition(f"state_{i-1}", f"state_{i}", {})

        await asyncio.sleep(0.3)
        await backend.stop()

        status = bus.read_data("status")
        assert status is not None
        assert status["step"] >= 40

    @pytest.mark.asyncio
    async def test_many_tool_calls(self):
        """Simulate many tool calls in rapid succession."""
        bus = DataBus()
        procs = [ToolProcessor(bus, max_hz=1000)]
        backend = CLIBackend(bus=bus, processors=procs)
        hooks = CLIHooks(backend)

        await backend.start()
        hooks.on_machine_start({"machine": {}})

        for i in range(30):
            hooks.on_tool_calls(f"s_{i}", [
                {"name": "bash", "arguments": {"command": f"cmd_{i}"}},
            ], {"_tool_loop_content": f"thinking_{i}", "_tool_loop_usage": {}})
            hooks.on_tool_result(f"s_{i}", {
                "name": "bash",
                "arguments": {"command": f"cmd_{i}"},
                "content": f"output_{i}",
                "is_error": False,
                "tool_call_id": f"tc_{i}",
            }, {})

        await asyncio.sleep(0.3)
        await backend.stop()

        tools = bus.read_data("tools")
        assert tools is not None
        assert tools["total_calls"] == 30
        assert tools["error_count"] == 0

    @pytest.mark.asyncio
    async def test_all_processors_under_load(self):
        """All 5 default processors running with rapid events."""
        bus = DataBus()
        procs = [
            StatusProcessor(bus, max_hz=1000),
            TokenProcessor(bus, max_hz=1000),
            ToolProcessor(bus, max_hz=1000),
            ContentProcessor(bus, max_hz=1000),
            ErrorProcessor(bus, max_hz=1000),
        ]
        backend = CLIBackend(bus=bus, processors=procs)
        hooks = CLIHooks(backend)

        await backend.start()

        hooks.on_machine_start({"machine": {"machine_name": "full_load"}})

        for i in range(20):
            hooks.on_state_enter(f"s_{i}", {"machine": {"step": i}})
            hooks.on_tool_calls(f"s_{i}", [{"name": "bash", "arguments": {}}], {
                "_tool_loop_content": f"thinking {i}",
                "_tool_loop_usage": {"input_tokens": i * 10},
                "_tool_loop_cost": 0.001 * i,
                "_tool_loop_turns": i,
            })
            hooks.on_tool_result(f"s_{i}", {
                "name": "bash", "arguments": {},
                "content": f"output_{i}", "is_error": i == 10,
            }, {})

        hooks.on_machine_end({"result": "complete"}, {})
        await asyncio.sleep(0.3)
        await backend.stop()

        # Verify all processors wrote data
        assert bus.read_data("status") is not None
        assert bus.read_data("tokens") is not None
        assert bus.read_data("tools") is not None
        assert bus.read_data("content") is not None

        # Verify correctness
        status = bus.read_data("status")
        assert status["phase"] == "done"

        tools = bus.read_data("tools")
        assert tools["total_calls"] == 20
        assert tools["error_count"] == 1

    @pytest.mark.asyncio
    async def test_error_recovery_under_load(self):
        """Processor should recover from errors during high throughput."""
        bus = DataBus()
        procs = [StatusProcessor(bus, max_hz=1000)]
        backend = CLIBackend(bus=bus, processors=procs)
        hooks = CLIHooks(backend)

        await backend.start()

        hooks.on_machine_start({"machine": {"machine_name": "error_load"}})

        # Mix valid events with malformed ones
        for i in range(20):
            if i % 5 == 0:
                # Malformed event (no state key)
                backend.emit({"type": events.STATE_ENTER})
            else:
                hooks.on_state_enter(f"s_{i}", {"machine": {"step": i}})

        await asyncio.sleep(0.3)
        await backend.stop()

        status = bus.read_data("status")
        assert status is not None
        assert status["step"] >= 15  # most events processed


class TestLargePayloads:
    @pytest.mark.asyncio
    async def test_large_tool_output(self):
        """Processor should handle large tool output."""
        bus = DataBus()
        procs = [ToolProcessor(bus, max_hz=1000)]
        backend = CLIBackend(bus=bus, processors=procs)
        hooks = CLIHooks(backend)

        await backend.start()
        hooks.on_machine_start({"machine": {}})

        large_content = "x" * 100000
        hooks.on_tool_result("s", {
            "name": "bash",
            "arguments": {},
            "content": large_content,
            "is_error": False,
        }, {})

        await asyncio.sleep(0.1)
        await backend.stop()

        tools = bus.read_data("tools")
        assert tools["last_result"]["content"] == large_content

    @pytest.mark.asyncio
    async def test_large_context(self):
        """Events with large context should not crash."""
        bus = DataBus()
        procs = [StatusProcessor(bus, max_hz=1000)]
        backend = CLIBackend(bus=bus, processors=procs)
        hooks = CLIHooks(backend)

        await backend.start()

        large_ctx = {
            "machine": {"machine_name": "large"},
            "data": {"items": list(range(10000))},
        }
        hooks.on_machine_start(large_ctx)
        await asyncio.sleep(0.1)
        await backend.stop()

        status = bus.read_data("status")
        assert status is not None
        assert status["machine_name"] == "large"


class TestBackendRestartCycles:
    @pytest.mark.asyncio
    async def test_multiple_full_cycles(self):
        """Backend should work correctly across multiple start/stop cycles."""
        bus = DataBus()
        procs = [StatusProcessor(bus, max_hz=1000)]
        backend = CLIBackend(bus=bus, processors=procs)
        hooks = CLIHooks(backend)

        for cycle in range(3):
            await backend.start()
            hooks.on_machine_start({"machine": {"machine_name": f"cycle_{cycle}"}})
            hooks.on_state_enter("work", {"machine": {"step": 1}})
            hooks.on_machine_end({}, {})
            await asyncio.sleep(0.1)
            await backend.stop()

            status = bus.read_data("status")
            assert status["machine_name"] == f"cycle_{cycle}"
            assert status["phase"] == "done"

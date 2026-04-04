"""Integration tests — full pipeline from hooks through bus to frontend."""

import asyncio
import pytest
from unittest.mock import patch

from flatmachines_cli.backend import CLIBackend
from flatmachines_cli.bus import DataBus
from flatmachines_cli.frontend import TerminalFrontend
from flatmachines_cli.hooks import CLIHooks
from flatmachines_cli.processors import StatusProcessor, TokenProcessor, ToolProcessor, default_processors
from flatmachines_cli.protocol import Frontend
from flatmachines_cli import events


class RecordingFrontend(Frontend):
    """Frontend that records bus snapshots for verification."""

    def __init__(self):
        self.snapshots = []
        self.running = False
        self.stopped = False
        self.actions = []

    async def start(self, bus):
        self.running = True
        while self.running:
            snap = bus.snapshot()
            if snap:
                self.snapshots.append(snap)
            await asyncio.sleep(0.01)

    async def stop(self):
        self.running = False
        self.stopped = True

    def handle_action(self, action_name, context):
        self.actions.append(action_name)
        context["auto_approved"] = True
        return context


class TestFullPipeline:
    """Test hooks → events → processors → bus → frontend pipeline."""

    @pytest.mark.asyncio
    async def test_machine_lifecycle(self):
        """Simulate a complete machine lifecycle."""
        bus = DataBus()
        procs = [
            StatusProcessor(bus, max_hz=1000),
            TokenProcessor(bus, max_hz=1000),
            ToolProcessor(bus, max_hz=1000),
        ]
        frontend = RecordingFrontend()
        backend = CLIBackend(bus=bus, processors=procs, frontend=frontend)
        backend.set_frontend(frontend)
        hooks = CLIHooks(backend)

        await backend.start()
        await asyncio.sleep(0.02)

        # Machine starts
        hooks.on_machine_start({"machine": {"machine_name": "pipeline_test", "execution_id": "e1"}})
        await asyncio.sleep(0.05)

        # Enter first state
        hooks.on_state_enter("analyze", {"machine": {"step": 1}})
        await asyncio.sleep(0.05)

        # Tool calls
        hooks.on_tool_calls("analyze", [
            {"name": "bash", "arguments": {"command": "ls"}},
        ], {"_tool_loop_content": "Let me check the files...", "_tool_loop_usage": {"input_tokens": 100, "output_tokens": 20}, "_tool_loop_cost": 0.001, "_tool_loop_turns": 1})
        await asyncio.sleep(0.05)

        # Tool result
        hooks.on_tool_result("analyze", {
            "name": "bash",
            "arguments": {"command": "ls"},
            "content": "file1.py\nfile2.py",
            "is_error": False,
            "tool_call_id": "tc1",
        }, {})
        await asyncio.sleep(0.05)

        # Transition
        hooks.on_transition("analyze", "done", {})
        await asyncio.sleep(0.05)

        # Machine ends
        hooks.on_machine_end({"result": "analysis complete"}, {"output": "done"})
        await asyncio.sleep(0.1)

        await backend.stop()

        # Verify status
        status = bus.read_data("status")
        assert status is not None
        assert status["machine_name"] == "pipeline_test"
        assert status["phase"] == "done"
        assert "analyze" in status["states_visited"]

        # Verify tokens
        tokens = bus.read_data("tokens")
        assert tokens is not None
        assert tokens["input_tokens"] == 100
        assert tokens["tool_calls_count"] == 1

        # Verify tools
        tools = bus.read_data("tools")
        assert tools is not None
        assert tools["total_calls"] == 1
        assert tools["error_count"] == 0
        assert len(tools["history"]) == 1

        # Verify frontend received snapshots
        assert len(frontend.snapshots) > 0

    @pytest.mark.asyncio
    async def test_error_propagation(self):
        """Errors should propagate through the full pipeline."""
        bus = DataBus()
        procs = [
            StatusProcessor(bus, max_hz=1000),
            ErrorProcessor(bus, max_hz=1000),
        ]
        backend = CLIBackend(bus=bus, processors=procs)
        hooks = CLIHooks(backend)

        await backend.start()

        hooks.on_machine_start({"machine": {"machine_name": "error_test"}})
        hooks.on_state_enter("risky", {"machine": {"step": 1}})
        hooks.on_error("risky", ValueError("something broke"), {})
        await asyncio.sleep(0.1)

        await backend.stop()

        status = bus.read_data("status")
        assert status["phase"] == "error"

        error = bus.read_data("error")
        assert error["has_error"] is True
        assert error["error_type"] == "ValueError"
        assert error["error_message"] == "something broke"

    @pytest.mark.asyncio
    async def test_action_routing(self):
        """Actions should be routed to the frontend."""
        bus = DataBus()
        procs = [StatusProcessor(bus, max_hz=1000)]
        frontend = RecordingFrontend()
        backend = CLIBackend(bus=bus, processors=procs, frontend=frontend)
        backend.set_frontend(frontend)
        hooks = CLIHooks(backend)

        await backend.start()
        await asyncio.sleep(0.02)

        hooks.on_machine_start({"machine": {}})
        result = hooks.on_action("human_review", {"task": "review"})
        assert result["auto_approved"] is True
        assert "human_review" in frontend.actions

        await backend.stop()

    @pytest.mark.asyncio
    async def test_multiple_tool_cycles(self):
        """Multiple tool call/result cycles should accumulate correctly."""
        bus = DataBus()
        procs = [
            TokenProcessor(bus, max_hz=1000),
            ToolProcessor(bus, max_hz=1000),
        ]
        backend = CLIBackend(bus=bus, processors=procs)
        hooks = CLIHooks(backend)

        await backend.start()

        hooks.on_machine_start({"machine": {}})

        for i in range(5):
            hooks.on_tool_calls(f"state_{i}", [
                {"name": "bash", "arguments": {"command": f"cmd_{i}"}},
            ], {"_tool_loop_usage": {"input_tokens": 10 * (i + 1)}, "_tool_loop_cost": 0.001 * (i + 1), "_tool_loop_turns": i + 1})

            hooks.on_tool_result(f"state_{i}", {
                "name": "bash",
                "arguments": {"command": f"cmd_{i}"},
                "content": f"output_{i}",
                "is_error": i == 3,  # One error
                "tool_call_id": f"tc_{i}",
            }, {})

        await asyncio.sleep(0.2)
        await backend.stop()

        tokens = bus.read_data("tokens")
        assert tokens["tool_calls_count"] == 5

        tools = bus.read_data("tools")
        assert tools["total_calls"] == 5
        assert tools["error_count"] == 1


class TestFrontendIntegration:
    @pytest.mark.asyncio
    async def test_terminal_frontend_renders_pipeline(self, capsys):
        """TerminalFrontend should render data from the bus."""
        bus = DataBus()
        frontend = TerminalFrontend(fps=100, auto_approve=True)
        procs = [StatusProcessor(bus, max_hz=1000)]
        backend = CLIBackend(bus=bus, processors=procs, frontend=frontend)
        backend.set_frontend(frontend)
        hooks = CLIHooks(backend)

        await backend.start()
        await asyncio.sleep(0.02)

        hooks.on_machine_start({"machine": {"machine_name": "render_test"}})
        hooks.on_state_enter("work", {"machine": {"step": 1}})
        hooks.on_machine_end({"result": "done"}, {})
        await asyncio.sleep(0.2)

        await backend.stop()

        captured = capsys.readouterr()
        assert "Done" in captured.out


# Need to import ErrorProcessor
from flatmachines_cli.processors import ErrorProcessor

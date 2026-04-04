"""End-to-end tests verifying complete data flow through the pipeline.

These tests simulate a real machine execution without actually running
a FlatMachine — they directly invoke hooks and verify the final bus state.
"""

import asyncio
import pytest

from flatmachines_cli.bus import DataBus
from flatmachines_cli.backend import CLIBackend
from flatmachines_cli.hooks import CLIHooks
from flatmachines_cli import events


class TestCompleteDataFlow:
    @pytest.mark.asyncio
    async def test_machine_lifecycle_populates_all_slots(self):
        """A complete machine run should populate all 5 bus slots."""
        bus = DataBus()
        backend = CLIBackend(bus=bus)
        hooks = CLIHooks(backend)
        await backend.start()

        # Simulate full lifecycle
        hooks.on_machine_start({
            "machine": {"machine_name": "flow", "execution_id": "e1"},
        })
        hooks.on_state_enter("init", {"machine": {"step": 0}})
        hooks.on_tool_calls("init", [
            {"name": "bash", "arguments": {"command": "ls"}, "tool_call_id": "c1"},
        ], {
            "_tool_loop_usage": {"input_tokens": 100, "output_tokens": 50},
            "_tool_loop_cost": 0.002,
            "_tool_loop_content": "Looking at files...",
        })
        hooks.on_tool_result("init", {
            "name": "bash",
            "arguments": {"command": "ls"},
            "content": "file1.py\nfile2.py",
            "is_error": False,
            "tool_call_id": "c1",
        }, {})
        hooks.on_state_exit("init", {}, {"result": "done"})
        hooks.on_transition("init", "final", {})
        hooks.on_state_enter("final", {"machine": {"step": 1}})
        hooks.on_machine_end({"result": "Success"}, {"result": "Success"})

        await asyncio.sleep(0.2)
        await backend.stop()

        # Verify all slots have data
        snap = bus.snapshot()
        assert "status" in snap
        assert "tokens" in snap
        assert "tools" in snap
        assert "content" in snap
        # error slot may or may not be populated (depends on whether error processor writes)

        # Check status
        assert snap["status"]["machine_name"] == "flow"
        assert snap["status"]["phase"] == "done"
        assert snap["status"]["states_visited"] == ["init", "final"]

        # Check tokens
        assert snap["tokens"]["input_tokens"] == 100
        assert snap["tokens"]["output_tokens"] == 50

        # Check tools
        assert snap["tools"]["total_calls"] == 1
        assert len(snap["tools"]["history"]) == 1

    @pytest.mark.asyncio
    async def test_error_flow(self):
        """Errors should show up in the error bus slot."""
        bus = DataBus()
        backend = CLIBackend(bus=bus)
        hooks = CLIHooks(backend)
        await backend.start()

        hooks.on_machine_start({"machine": {}})
        hooks.on_state_enter("bad_state", {"machine": {"step": 0}})
        hooks.on_error("bad_state", ValueError("something broke"), {})

        await asyncio.sleep(0.15)
        await backend.stop()

        error_data = bus.read_data("error")
        assert error_data is not None
        assert error_data["has_error"] is True
        assert error_data["error_type"] == "ValueError"
        assert "something broke" in error_data["error_message"]

    @pytest.mark.asyncio
    async def test_subscriber_receives_all_updates(self):
        """A bus subscriber should see every slot write during execution."""
        bus = DataBus()
        backend = CLIBackend(bus=bus)
        hooks = CLIHooks(backend)
        await backend.start()

        # Subscribe AFTER start() (which calls bus.reset())
        updates = []
        bus.subscribe(lambda name, val: updates.append(name))

        hooks.on_machine_start({"machine": {}})
        hooks.on_state_enter("s1", {"machine": {}})
        hooks.on_machine_end({"result": "ok"}, {})

        await asyncio.sleep(0.15)
        await backend.stop()

        # Should have received multiple slot updates
        assert len(updates) > 0
        assert "status" in updates

    @pytest.mark.asyncio
    async def test_health_check_during_execution(self):
        """Health check should reflect running state during execution."""
        bus = DataBus()
        backend = CLIBackend(bus=bus)
        await backend.start()

        health = backend.health_check()
        assert health["running"] is True
        assert all(p["running"] for p in health["processors"])

        await backend.stop()
        health = backend.health_check()
        assert health["running"] is False

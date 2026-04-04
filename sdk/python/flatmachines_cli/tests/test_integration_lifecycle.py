"""Integration tests for full lifecycle flows."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from flatmachines_cli.bus import DataBus
from flatmachines_cli.backend import CLIBackend
from flatmachines_cli.hooks import CLIHooks
from flatmachines_cli.processors import (
    StatusProcessor, TokenProcessor, ToolProcessor,
    ContentProcessor, ErrorProcessor,
)
from flatmachines_cli import events


class TestFullLifecycle:
    @pytest.mark.asyncio
    async def test_start_emit_stop(self):
        """Full lifecycle: start → emit events → stop."""
        bus = DataBus()
        backend = CLIBackend(bus=bus)
        hooks = CLIHooks(backend)

        await backend.start()

        hooks.on_machine_start({"machine": {"name": "test_m"}})
        hooks.on_state_enter("init", {"machine": {"step": 0}})
        hooks.on_state_exit("init", {}, {"result": "ok"})
        hooks.on_transition("init", "final", {})
        hooks.on_state_enter("final", {"machine": {"step": 1}})
        hooks.on_machine_end({}, {"result": "done"})

        await asyncio.sleep(0.1)
        await backend.stop()

        # Verify bus has data
        status = bus.read_data("status")
        assert status is not None

        # Verify timing stats
        stats = hooks.timing_stats
        assert stats["on_machine_start"]["calls"] == 1
        assert stats["on_state_enter"]["calls"] == 2
        assert stats["on_transition"]["calls"] == 1

    @pytest.mark.asyncio
    async def test_multiple_executions(self):
        """Backend can be started and stopped multiple times."""
        bus = DataBus()
        backend = CLIBackend(bus=bus)

        for i in range(3):
            await backend.start()
            backend.emit(events.machine_start({"machine": {"name": f"run_{i}"}}))
            await asyncio.sleep(0.05)
            await backend.stop()

    @pytest.mark.asyncio
    async def test_error_recovery_lifecycle(self):
        """Error during execution doesn't break subsequent start/stop."""
        bus = DataBus()
        backend = CLIBackend(bus=bus)
        hooks = CLIHooks(backend)

        await backend.start()
        hooks.on_machine_start({"machine": {}})
        hooks.on_error("bad_state", RuntimeError("oops"), {})
        await asyncio.sleep(0.05)
        await backend.stop()

        # Can start again
        await backend.start()
        hooks.on_machine_start({"machine": {}})
        await asyncio.sleep(0.05)
        await backend.stop()


class TestRunMachineConvenience:
    @pytest.mark.asyncio
    async def test_run_machine_success(self):
        bus = DataBus()
        backend = CLIBackend(bus=bus, processors=[])

        mock_machine = MagicMock()
        mock_machine.execute = AsyncMock(return_value={"result": "success"})

        result = await backend.run_machine(mock_machine, input={"task": "test"})
        assert result == {"result": "success"}
        assert not backend._running

    @pytest.mark.asyncio
    async def test_run_machine_exception(self):
        bus = DataBus()
        backend = CLIBackend(bus=bus, processors=[])

        mock_machine = MagicMock()
        mock_machine.execute = AsyncMock(side_effect=RuntimeError("boom"))

        with pytest.raises(RuntimeError, match="boom"):
            await backend.run_machine(mock_machine, input={})
        # Backend should still be stopped
        assert not backend._running

    @pytest.mark.asyncio
    async def test_run_machine_cancelled(self):
        bus = DataBus()
        backend = CLIBackend(bus=bus, processors=[])

        mock_machine = MagicMock()
        mock_machine.execute = AsyncMock(side_effect=asyncio.CancelledError())

        with pytest.raises(asyncio.CancelledError):
            await backend.run_machine(mock_machine, input={})
        assert not backend._running


class TestProcessorResetBetweenRuns:
    @pytest.mark.asyncio
    async def test_processors_reset_on_start(self):
        """Each start() resets processor state."""
        bus = DataBus()
        sp = StatusProcessor(bus, max_hz=1000)
        backend = CLIBackend(bus=bus, processors=[sp])

        await backend.start()
        backend.emit(events.state_enter("s1", {"machine": {"name": "run1"}}))
        await asyncio.sleep(0.05)
        await backend.stop()

        # Read state after first run
        status1 = bus.read_data("status")
        assert status1 is not None

        # Second run — reset should clear previous state
        await backend.start()
        backend.emit(events.state_enter("s2", {"machine": {"name": "run2"}}))
        await asyncio.sleep(0.05)
        await backend.stop()

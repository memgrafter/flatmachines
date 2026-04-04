"""Tests for run_once, run_standalone, and machine execution lifecycle."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from flatmachines_cli.backend import CLIBackend
from flatmachines_cli.bus import DataBus
from flatmachines_cli.processors import StatusProcessor


class TestBackendRunMachine:
    """Test CLIBackend.run_machine() with mock machines."""

    @pytest.mark.asyncio
    async def test_run_machine_basic(self):
        """run_machine should start, execute, and stop."""
        bus = DataBus()
        procs = [StatusProcessor(bus, max_hz=1000)]
        backend = CLIBackend(bus=bus, processors=procs)

        mock_machine = MagicMock()
        mock_machine.execute = AsyncMock(return_value={"result": "success"})

        result = await backend.run_machine(mock_machine, input={"task": "test"})
        assert result == {"result": "success"}
        mock_machine.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_machine_passes_input(self):
        """Input should be passed to machine.execute()."""
        bus = DataBus()
        backend = CLIBackend(bus=bus, processors=[])

        mock_machine = MagicMock()
        mock_machine.execute = AsyncMock(return_value={})

        await backend.run_machine(mock_machine, input={"task": "hello", "dir": "/tmp"})

        call_kwargs = mock_machine.execute.call_args
        assert call_kwargs.kwargs["input"]["task"] == "hello"

    @pytest.mark.asyncio
    async def test_run_machine_stops_on_error(self):
        """Backend should stop even if machine.execute raises."""
        bus = DataBus()
        procs = [StatusProcessor(bus, max_hz=1000)]
        backend = CLIBackend(bus=bus, processors=procs)

        mock_machine = MagicMock()
        mock_machine.execute = AsyncMock(side_effect=RuntimeError("machine died"))

        with pytest.raises(RuntimeError, match="machine died"):
            await backend.run_machine(mock_machine)

        # Backend should have stopped (not running)
        assert backend._running is False

    @pytest.mark.asyncio
    async def test_run_machine_stops_on_cancel(self):
        """Backend should stop on cancellation."""
        bus = DataBus()
        procs = [StatusProcessor(bus, max_hz=1000)]
        backend = CLIBackend(bus=bus, processors=procs)

        async def slow_execute(**kwargs):
            await asyncio.sleep(10)  # long operation
            return {}

        mock_machine = MagicMock()
        mock_machine.execute = slow_execute

        task = asyncio.ensure_future(backend.run_machine(mock_machine))
        await asyncio.sleep(0.05)
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

    @pytest.mark.asyncio
    async def test_run_machine_returns_complex_result(self):
        """Machine results can be complex nested structures."""
        bus = DataBus()
        backend = CLIBackend(bus=bus, processors=[])

        result_data = {
            "files_created": ["/tmp/a.py", "/tmp/b.py"],
            "stats": {"lines": 100, "edits": 5},
            "success": True,
        }
        mock_machine = MagicMock()
        mock_machine.execute = AsyncMock(return_value=result_data)

        result = await backend.run_machine(mock_machine)
        assert result["files_created"] == ["/tmp/a.py", "/tmp/b.py"]
        assert result["stats"]["lines"] == 100


class TestBackendLifecycleGuarantees:
    """Test that backend lifecycle guarantees are maintained."""

    @pytest.mark.asyncio
    async def test_start_creates_processor_tasks(self):
        bus = DataBus()
        procs = [StatusProcessor(bus, max_hz=1000)]
        backend = CLIBackend(bus=bus, processors=procs)

        await backend.start()
        # Processor task should exist
        assert procs[0]._task is not None
        assert not procs[0]._task.done()

        await backend.stop()

    @pytest.mark.asyncio
    async def test_stop_completes_processor_tasks(self):
        bus = DataBus()
        procs = [StatusProcessor(bus, max_hz=1000)]
        backend = CLIBackend(bus=bus, processors=procs)

        await backend.start()
        await backend.stop()

        # Processor task should be done
        assert procs[0]._task.done()

    @pytest.mark.asyncio
    async def test_bus_reset_on_start(self):
        """Bus should be reset on each start, clearing stale data."""
        bus = DataBus()
        bus.write("stale", "old_data")
        backend = CLIBackend(bus=bus, processors=[])

        await backend.start()
        assert bus.read_data("stale") is None
        await backend.stop()

    @pytest.mark.asyncio
    async def test_processor_reset_on_start(self):
        """Processors should be reset on each start."""
        bus = DataBus()
        proc = StatusProcessor(bus, max_hz=1000)
        proc._machine_name = "stale"
        backend = CLIBackend(bus=bus, processors=[proc])

        await backend.start()
        assert proc._machine_name == ""
        await backend.stop()

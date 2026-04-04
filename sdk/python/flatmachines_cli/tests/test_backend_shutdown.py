"""Tests for backend graceful shutdown with timeout."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from flatmachines_cli.bus import DataBus
from flatmachines_cli.backend import CLIBackend
from flatmachines_cli.processors import Processor, StatusProcessor
from flatmachines_cli import events


class TestShutdownTimeout:
    @pytest.mark.asyncio
    async def test_normal_shutdown_within_timeout(self):
        bus = DataBus()
        backend = CLIBackend(bus=bus)
        await backend.start()
        backend.emit(events.machine_start({"machine": {}}))
        await asyncio.sleep(0.05)
        await backend.stop(timeout=5.0)
        assert not backend._running

    @pytest.mark.asyncio
    async def test_shutdown_default_timeout(self):
        bus = DataBus()
        backend = CLIBackend(bus=bus, processors=[])
        await backend.start()
        await backend.stop()  # Default timeout=5.0
        assert not backend._running

    @pytest.mark.asyncio
    async def test_stuck_processor_force_cancelled(self):
        """Processor that refuses to stop is force-cancelled after timeout."""
        bus = DataBus()

        class StuckProcessor(Processor):
            slot_name = "stuck"
            event_types = None

            def process(self, event):
                return {"ok": True}

            async def _run(self):
                """Override to ignore STOP sentinel — simulates a stuck processor."""
                while True:
                    await asyncio.sleep(0.01)

        proc = StuckProcessor(bus, max_hz=30)
        backend = CLIBackend(bus=bus, processors=[proc])
        await backend.start()

        # Stop with a short timeout — processor should be force-cancelled
        await backend.stop(timeout=0.1)
        assert not backend._running
        assert proc._task.cancelled() or proc._task.done()

    @pytest.mark.asyncio
    async def test_stop_idempotent(self):
        bus = DataBus()
        backend = CLIBackend(bus=bus, processors=[])
        await backend.start()
        await backend.stop()
        await backend.stop()  # Should not raise
        assert not backend._running

    @pytest.mark.asyncio
    async def test_stop_before_start(self):
        bus = DataBus()
        backend = CLIBackend(bus=bus, processors=[])
        await backend.stop()  # Should not raise
        assert not backend._running


class TestProcessorStatsAfterShutdown:
    @pytest.mark.asyncio
    async def test_stats_available_after_stop(self):
        bus = DataBus()
        p = StatusProcessor(bus, max_hz=1000)
        backend = CLIBackend(bus=bus, processors=[p])
        await backend.start()

        backend.emit(events.state_enter("s1", {"machine": {}}))
        backend.emit(events.state_enter("s2", {"machine": {}}))
        await asyncio.sleep(0.1)

        await backend.stop()

        # Stats should still be accessible
        stats = p.stats
        assert stats["events_processed"] >= 2
        assert stats["events_dropped"] == 0


class TestBackendEmitDuringShutdown:
    @pytest.mark.asyncio
    async def test_emit_after_stop_no_crash(self):
        """Emitting after stop should not raise."""
        bus = DataBus()
        backend = CLIBackend(bus=bus, processors=[])
        await backend.start()
        await backend.stop()
        # Emit after stop — should silently drop
        backend.emit(events.machine_start({"machine": {}}))

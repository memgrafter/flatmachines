"""Tests for backend health_check monitoring."""

import asyncio
import pytest

from flatmachines_cli.bus import DataBus
from flatmachines_cli.backend import CLIBackend
from flatmachines_cli.frontend import TerminalFrontend
from flatmachines_cli.processors import StatusProcessor
from flatmachines_cli import events


class TestHealthCheck:
    def test_initial_health(self):
        bus = DataBus()
        backend = CLIBackend(bus=bus)
        health = backend.health_check()
        assert health["running"] is False
        assert health["processor_count"] == 5  # default processors
        assert health["bus_slots"] == 0
        assert health["frontend"] is None

    @pytest.mark.asyncio
    async def test_running_health(self):
        bus = DataBus()
        backend = CLIBackend(bus=bus)
        await backend.start()

        health = backend.health_check()
        assert health["running"] is True
        for p in health["processors"]:
            assert p["running"] is True
            assert "events_processed" in p
            assert "queue_hwm" in p

        await backend.stop()

    @pytest.mark.asyncio
    async def test_health_after_events(self):
        bus = DataBus()
        backend = CLIBackend(bus=bus)
        await backend.start()

        backend.emit(events.machine_start({"machine": {}}))
        backend.emit(events.state_enter("s1", {"machine": {}}))
        await asyncio.sleep(0.1)

        health = backend.health_check()
        assert health["bus_slots"] > 0
        assert len(health["bus_slot_names"]) > 0

        # At least some processors should have processed events
        total_processed = sum(p["events_processed"] for p in health["processors"])
        assert total_processed > 0

        await backend.stop()

    def test_health_with_frontend(self):
        bus = DataBus()
        fe = TerminalFrontend(auto_approve=True)
        backend = CLIBackend(bus=bus, frontend=fe)
        health = backend.health_check()
        assert health["frontend"] == "TerminalFrontend"

    @pytest.mark.asyncio
    async def test_health_after_stop(self):
        bus = DataBus()
        backend = CLIBackend(bus=bus)
        await backend.start()
        await backend.stop()

        health = backend.health_check()
        assert health["running"] is False

    def test_health_custom_processors(self):
        bus = DataBus()
        sp = StatusProcessor(bus)
        backend = CLIBackend(bus=bus, processors=[sp])
        health = backend.health_check()
        assert health["processor_count"] == 1
        assert health["processors"][0]["name"] == "status"
        assert health["processors"][0]["type"] == "StatusProcessor"

    def test_health_no_processors(self):
        bus = DataBus()
        backend = CLIBackend(bus=bus, processors=[])
        health = backend.health_check()
        assert health["processor_count"] == 0
        assert health["processors"] == []

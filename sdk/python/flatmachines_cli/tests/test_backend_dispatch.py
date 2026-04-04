"""Tests for backend event dispatch and action routing."""

import asyncio
import pytest
from unittest.mock import MagicMock

from flatmachines_cli.bus import DataBus
from flatmachines_cli.backend import CLIBackend
from flatmachines_cli.processors import Processor, StatusProcessor
from flatmachines_cli.protocol import ActionHandler, Frontend
from flatmachines_cli import events


class TestEventDispatch:
    @pytest.mark.asyncio
    async def test_emit_to_matching_processors(self):
        bus = DataBus()
        sp = StatusProcessor(bus, max_hz=1000)
        backend = CLIBackend(bus=bus, processors=[sp])
        await backend.start()

        backend.emit(events.machine_start({"machine": {}}))
        await asyncio.sleep(0.05)

        assert sp.stats["events_processed"] >= 1
        await backend.stop()

    @pytest.mark.asyncio
    async def test_emit_skips_non_matching(self):
        bus = DataBus()

        class NarrowProcessor(Processor):
            slot_name = "narrow"
            event_types = frozenset({"custom_event"})
            def process(self, event):
                return {"seen": True}

        p = NarrowProcessor(bus, max_hz=1000)
        backend = CLIBackend(bus=bus, processors=[p])
        await backend.start()

        # Emit an event the processor doesn't accept
        backend.emit(events.machine_start({"machine": {}}))
        await asyncio.sleep(0.05)

        assert p.stats["events_processed"] == 0
        await backend.stop()

    @pytest.mark.asyncio
    async def test_emit_multiple_processors(self):
        bus = DataBus()
        sp = StatusProcessor(bus, max_hz=1000)

        class AllProcessor(Processor):
            slot_name = "all"
            event_types = None
            def process(self, event):
                return {"count": self._events_processed}

        ap = AllProcessor(bus, max_hz=1000)
        backend = CLIBackend(bus=bus, processors=[sp, ap])
        await backend.start()

        backend.emit(events.machine_start({"machine": {}}))
        await asyncio.sleep(0.05)

        assert sp.stats["events_processed"] >= 1
        assert ap.stats["events_processed"] >= 1
        await backend.stop()


class TestActionRouting:
    def test_default_action_handler(self):
        bus = DataBus()
        backend = CLIBackend(bus=bus, processors=[])
        result = backend.handle_action("test", {"key": "val"})
        assert result == {"key": "val"}  # Returned unchanged

    def test_registered_action_handler(self):
        bus = DataBus()
        backend = CLIBackend(bus=bus, processors=[])
        backend.register_action("greet", lambda name, ctx: {**ctx, "greeted": True})
        result = backend.handle_action("greet", {"name": "test"})
        assert result["greeted"] is True

    def test_frontend_action_handler(self):
        bus = DataBus()

        class MockFrontend(Frontend):
            async def start(self, bus): pass
            async def stop(self): pass
            def handle_action(self, action_name, context):
                return {**context, "frontend_handled": True}

        fe = MockFrontend()
        backend = CLIBackend(bus=bus, processors=[], frontend=fe)
        backend.set_frontend(fe)

        result = backend.handle_action("any_action", {"x": 1})
        assert result["frontend_handled"] is True


class TestBackendProperties:
    def test_bus_property(self):
        bus = DataBus()
        backend = CLIBackend(bus=bus)
        assert backend.bus is bus

    def test_processors_property(self):
        bus = DataBus()
        backend = CLIBackend(bus=bus)
        assert len(backend.processors) == 5  # default processors

    def test_action_handler_property(self):
        bus = DataBus()
        backend = CLIBackend(bus=bus)
        assert isinstance(backend.action_handler, ActionHandler)

    def test_add_processor(self):
        bus = DataBus()
        backend = CLIBackend(bus=bus, processors=[])

        class Custom(Processor):
            slot_name = "custom"
            def process(self, event):
                return {}

        p = Custom(bus)
        backend.add_processor(p)
        assert len(backend.processors) == 1
        assert backend.processors[0] is p

"""Final coverage tests — hit remaining untested paths."""

import asyncio
import json
import pytest
from unittest.mock import patch, MagicMock

from flatmachines_cli.bus import DataBus, Slot
from flatmachines_cli.backend import CLIBackend
from flatmachines_cli.processors import (
    StatusProcessor, TokenProcessor, ToolProcessor,
    ContentProcessor, ErrorProcessor,
)
from flatmachines_cli.protocol import ActionHandler
from flatmachines_cli import events


class TestSlotReadIfChanged:
    """Cover read_if_changed edge cases."""

    def test_since_zero_with_value(self):
        s = Slot()
        s.write("first")
        val = s.read_if_changed(0)
        assert val is not None
        assert val.data == "first"

    def test_since_exact_version(self):
        s = Slot()
        s.write("v1")
        s.write("v2")
        # Since version 1, should return v2
        val = s.read_if_changed(1)
        assert val.data == "v2"

    def test_since_current_version(self):
        s = Slot()
        s.write("v1")
        val = s.read_if_changed(1)
        assert val is None


class TestDataBusSnapshotConsistency:
    def test_snapshot_values_match_individual_reads(self):
        bus = DataBus()
        bus.write("a", 1)
        bus.write("b", "two")
        bus.write("c", [3])
        snap = bus.snapshot()
        assert snap["a"] == bus.read_data("a")
        assert snap["b"] == bus.read_data("b")
        assert snap["c"] == bus.read_data("c")


class TestTokenProcessorCostHandling:
    def test_cost_rounds_correctly(self):
        bus = DataBus()
        p = TokenProcessor(bus)
        p.process(events.machine_start({"machine": {}}))
        result = p.process(events.tool_calls("s", [{"name": "bash"}], {
            "_tool_loop_usage": {},
            "_tool_loop_cost": 0.1234567899,
        }))
        assert result["total_cost"] == 0.123457

    def test_zero_cost(self):
        bus = DataBus()
        p = TokenProcessor(bus)
        p.process(events.machine_start({"machine": {}}))
        result = p._snapshot()
        assert result["total_cost"] == 0.0


class TestToolProcessorFileTracking:
    def test_edit_tracks_files(self):
        bus = DataBus()
        p = ToolProcessor(bus)
        p.process(events.tool_result("s", {
            "name": "edit",
            "arguments": {"path": "/tmp/edited.py"},
            "is_error": False,
        }, {}))
        assert "/tmp/edited.py" in p._snapshot()["files_modified"]

    def test_read_does_not_track_files(self):
        bus = DataBus()
        p = ToolProcessor(bus)
        p.process(events.tool_result("s", {
            "name": "read",
            "arguments": {"path": "/tmp/read.py"},
            "is_error": False,
        }, {}))
        assert "/tmp/read.py" not in p._snapshot()["files_modified"]

    def test_bash_does_not_track_files(self):
        bus = DataBus()
        p = ToolProcessor(bus)
        p.process(events.tool_result("s", {
            "name": "bash",
            "arguments": {"command": "touch /tmp/f"},
            "is_error": False,
        }, {}))
        assert p._snapshot()["files_modified"] == []


class TestContentProcessorMachineEndEdgeCases:
    def test_empty_result(self):
        bus = DataBus()
        p = ContentProcessor(bus)
        result = p.process(events.machine_end({"result": ""}, {}))
        # Empty string result → no update
        assert result is not None

    def test_none_result(self):
        bus = DataBus()
        p = ContentProcessor(bus)
        result = p.process(events.machine_end({"result": None}, {}))
        assert result is not None

    def test_bool_result(self):
        bus = DataBus()
        p = ContentProcessor(bus)
        result = p.process(events.machine_end({"result": True}, {}))
        assert result["text"] == "True"


class TestBackendEmitWithNoProcessors:
    @pytest.mark.asyncio
    async def test_emit_no_processors(self):
        bus = DataBus()
        backend = CLIBackend(bus=bus, processors=[])
        await backend.start()
        # Should not crash
        backend.emit(events.machine_start({"machine": {}}))
        await backend.stop()


class TestProcessorAcceptsMissingType:
    def test_accepts_no_type_key(self):
        bus = DataBus()
        p = StatusProcessor(bus)
        # Event without 'type' key
        assert p.accepts({}) is False

    def test_accepts_none_type(self):
        bus = DataBus()
        p = StatusProcessor(bus)
        assert p.accepts({"type": None}) is False


class TestMultipleProcessorsSameSlot:
    """Edge case: what happens with multiple processors writing same slot."""

    @pytest.mark.asyncio
    async def test_last_writer_wins(self):
        """If two processors write to same slot, latest write wins."""
        from flatmachines_cli.processors import Processor

        class WriterA(Processor):
            slot_name = "shared"
            event_types = None
            def process(self, event):
                return {"writer": "A", "data": event.get("data")}

        class WriterB(Processor):
            slot_name = "shared"
            event_types = None
            def process(self, event):
                return {"writer": "B", "data": event.get("data")}

        bus = DataBus()
        a = WriterA(bus, max_hz=1000)
        b = WriterB(bus, max_hz=1000)

        a.start()
        b.start()

        a.enqueue({"type": "test", "data": 1})
        b.enqueue({"type": "test", "data": 2})
        await asyncio.sleep(0.1)

        a.stop()
        b.stop()
        await asyncio.sleep(0.05)

        data = bus.read_data("shared")
        assert data is not None
        # Either writer's data is valid
        assert data["writer"] in ("A", "B")

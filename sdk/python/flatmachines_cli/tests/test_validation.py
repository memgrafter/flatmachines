"""Tests for input validation and error handling across modules."""

import asyncio
import logging
import pytest
from flatmachines_cli.bus import DataBus, Slot
from flatmachines_cli.backend import CLIBackend
from flatmachines_cli.processors import StatusProcessor
from flatmachines_cli import events


class TestBusValidation:
    """Input validation for DataBus."""

    def test_slot_name_must_be_string(self):
        bus = DataBus()
        with pytest.raises(TypeError, match="must be a string"):
            bus.slot(123)

    def test_slot_name_must_not_be_empty(self):
        bus = DataBus()
        with pytest.raises(ValueError, match="must not be empty"):
            bus.slot("")

    def test_write_name_must_be_string(self):
        bus = DataBus()
        with pytest.raises(TypeError):
            bus.write(None, "value")

    def test_write_name_must_not_be_empty(self):
        bus = DataBus()
        with pytest.raises(ValueError):
            bus.write("", "value")

    def test_read_nonexistent_returns_none_gracefully(self):
        bus = DataBus()
        assert bus.read("nope") is None
        assert bus.read_data("nope") is None


class TestSlotEdgeCases:
    """Edge cases for Slot."""

    def test_slot_without_name(self):
        s = Slot()
        assert s.name == ""

    def test_many_rapid_writes(self):
        s = Slot()
        for i in range(10000):
            s.write(i)
        assert s.version == 10000
        assert s.read_data() == 9999

    def test_read_if_changed_with_future_version(self):
        """Asking for changes since a version higher than current returns None."""
        s = Slot()
        s.write("x")
        assert s.read_if_changed(999) is None


class TestProcessorEdgeCases:
    """Edge cases for processor pipeline."""

    @pytest.mark.asyncio
    async def test_processor_handles_malformed_events(self):
        """Processor should handle events missing expected keys gracefully."""
        bus = DataBus()
        p = StatusProcessor(bus, max_hz=1000)
        p.start()

        # Event with missing fields — should not crash
        p.enqueue({"type": events.STATE_ENTER})  # no "state" or "context"
        await asyncio.sleep(0.05)

        # Verify processor still works after malformed event
        p.enqueue(events.machine_start({"machine": {"machine_name": "after_malformed"}}))
        await asyncio.sleep(0.05)

        p.stop()
        await asyncio.sleep(0.05)

        data = bus.read_data("status")
        assert data is not None
        assert data["machine_name"] == "after_malformed"

    @pytest.mark.asyncio
    async def test_processor_survives_process_exception(self):
        """If process() raises, processor should log and continue."""
        from flatmachines_cli.processors import Processor

        class CrashyProcessor(Processor):
            slot_name = "crashy"
            event_types = None  # accept all

            def __init__(self, bus):
                super().__init__(bus, max_hz=1000)
                self.call_count = 0

            def process(self, event):
                self.call_count += 1
                if self.call_count == 1:
                    raise ValueError("intentional crash")
                return {"count": self.call_count}

        bus = DataBus()
        p = CrashyProcessor(bus)
        p.start()

        p.enqueue({"type": "first"})   # will crash
        p.enqueue({"type": "second"})  # should still work
        await asyncio.sleep(0.1)

        p.stop()
        await asyncio.sleep(0.05)

        data = bus.read_data("crashy")
        assert data is not None
        assert data["count"] == 2

    @pytest.mark.asyncio
    async def test_processor_stop_without_start(self):
        """Stopping a processor that was never started should not crash."""
        bus = DataBus()
        p = StatusProcessor(bus)
        p.stop()  # should not raise

    @pytest.mark.asyncio
    async def test_processor_double_stop(self):
        """Double-stopping a processor should not crash."""
        bus = DataBus()
        p = StatusProcessor(bus, max_hz=1000)
        p.start()
        p.enqueue(events.machine_start({"machine": {}}))
        await asyncio.sleep(0.02)
        p.stop()
        await asyncio.sleep(0.02)
        p.stop()  # should not crash


class TestBackendEdgeCases:
    @pytest.mark.asyncio
    async def test_emit_before_start(self):
        """Emitting events before backend.start() should not crash."""
        bus = DataBus()
        backend = CLIBackend(bus=bus)
        evt = events.machine_start({"machine": {"machine_name": "early"}})
        backend.emit(evt)  # processors not started, events queued but not processed

    @pytest.mark.asyncio
    async def test_run_machine_without_frontend(self):
        """Backend should work without a frontend attached."""
        bus = DataBus()
        procs = [StatusProcessor(bus, max_hz=1000)]
        backend = CLIBackend(bus=bus, processors=procs)
        await backend.start()
        backend.emit(events.machine_start({"machine": {"machine_name": "no_frontend"}}))
        await asyncio.sleep(0.1)
        data = bus.read_data("status")
        assert data is not None
        await backend.stop()


class TestDiscoveryLogging:
    """Verify discovery logs errors instead of silently swallowing."""

    def test_invalid_yaml_logs_debug(self, tmp_path, caplog):
        from flatmachines_cli.discovery import _parse_machine_header

        f = tmp_path / "bad.yml"
        f.write_text("{bad: yaml: content")

        with caplog.at_level(logging.DEBUG, logger="flatmachines_cli.discovery"):
            result = _parse_machine_header(str(f))
        assert result is None
        assert any("Failed to parse" in r.message for r in caplog.records)

    def test_nonexistent_file_logs_debug(self, caplog):
        from flatmachines_cli.discovery import _parse_machine_header

        with caplog.at_level(logging.DEBUG, logger="flatmachines_cli.discovery"):
            result = _parse_machine_header("/totally/nonexistent/path.yml")
        assert result is None
        assert any("Failed to parse" in r.message for r in caplog.records)


class TestPyTypedMarker:
    """Verify py.typed marker exists for PEP 561 compliance."""

    def test_py_typed_exists(self):
        from pathlib import Path
        import flatmachines_cli
        pkg_dir = Path(flatmachines_cli.__file__).parent
        assert (pkg_dir / "py.typed").exists()

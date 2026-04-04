"""Tests for error handling paths throughout the library."""

import asyncio
import pytest
from flatmachines_cli.bus import DataBus, Slot
from flatmachines_cli.backend import CLIBackend
from flatmachines_cli.processors import (
    StatusProcessor, TokenProcessor, ToolProcessor,
    ContentProcessor, ErrorProcessor, Processor,
)
from flatmachines_cli.protocol import ActionHandler
from flatmachines_cli import events


class TestActionHandlerErrors:
    """Test error handling in action routing."""

    def test_handler_exception_propagates(self):
        """If a handler raises, it should propagate."""
        ah = ActionHandler()
        def bad_handler(name, ctx):
            raise ValueError("handler error")
        ah.register("bad", bad_handler)
        with pytest.raises(ValueError, match="handler error"):
            ah.handle("bad", {})

    def test_default_handler_exception_propagates(self):
        ah = ActionHandler()
        def bad_default(name, ctx):
            raise RuntimeError("default error")
        ah.set_default(bad_default)
        with pytest.raises(RuntimeError, match="default error"):
            ah.handle("any", {})


class TestProcessorErrorRecovery:
    """Test that processors recover from various error conditions."""

    @pytest.mark.asyncio
    async def test_processor_continues_after_error(self):
        """Processor should continue processing after a process() error."""

        class FragileProcessor(Processor):
            slot_name = "fragile"
            event_types = None

            def __init__(self, bus):
                super().__init__(bus, max_hz=1000)
                self.calls = 0

            def process(self, event):
                self.calls += 1
                if event.get("crash"):
                    raise RuntimeError("boom")
                return {"calls": self.calls}

        bus = DataBus()
        p = FragileProcessor(bus)
        p.start()

        p.enqueue({"type": "good"})
        p.enqueue({"type": "bad", "crash": True})
        p.enqueue({"type": "good_again"})
        await asyncio.sleep(0.1)

        p.stop()
        await asyncio.sleep(0.05)

        data = bus.read_data("fragile")
        assert data is not None
        assert data["calls"] == 3  # all three processed

    @pytest.mark.asyncio
    async def test_processor_handles_none_event_type(self):
        """Event without 'type' key should not crash processor."""
        bus = DataBus()
        p = StatusProcessor(bus, max_hz=1000)
        p.start()

        p.enqueue({})  # no type key
        p.enqueue(events.machine_start({"machine": {"machine_name": "after_none"}}))
        await asyncio.sleep(0.1)

        p.stop()
        await asyncio.sleep(0.05)

        data = bus.read_data("status")
        assert data is not None

    @pytest.mark.asyncio
    async def test_enqueue_to_full_queue(self):
        """Enqueueing to a full queue should drop silently."""

        class SmallQueueProcessor(Processor):
            slot_name = "small_q"
            event_types = None

            def __init__(self, bus):
                super().__init__(bus, max_hz=1000, queue_size=2)

            def process(self, event):
                return {"ok": True}

        bus = DataBus()
        p = SmallQueueProcessor(bus)
        # Don't start — queue will fill up

        for i in range(100):
            p.enqueue(events.machine_start({"machine": {}}))

        # Should not raise


class TestBackendErrorHandling:
    @pytest.mark.asyncio
    async def test_backend_handles_processor_crash(self):
        """If a processor task crashes, other processors should continue."""

        class CrashingProcessor(Processor):
            slot_name = "crasher"
            event_types = None

            def process(self, event):
                raise RuntimeError("processor died")

        bus = DataBus()
        good_proc = StatusProcessor(bus, max_hz=1000)
        bad_proc = CrashingProcessor(bus, max_hz=1000)
        backend = CLIBackend(bus=bus, processors=[good_proc, bad_proc])

        await backend.start()

        backend.emit(events.machine_start({"machine": {"machine_name": "error_test"}}))
        await asyncio.sleep(0.2)

        await backend.stop()

        # Good processor should still have written data
        status = bus.read_data("status")
        assert status is not None
        assert status["machine_name"] == "error_test"


class TestEventConstructorEdgeCases:
    """Test event constructors with unusual inputs."""

    def test_machine_start_empty_context(self):
        evt = events.machine_start({})
        assert evt["type"] == events.MACHINE_START
        assert evt["machine_name"] == ""

    def test_machine_end_complex_output(self):
        output = {
            "files": ["/tmp/a.py", "/tmp/b.py"],
            "stats": {"lines": 100, "changes": 5},
        }
        evt = events.machine_end({}, output)
        assert evt["final_output"]["files"] == ["/tmp/a.py", "/tmp/b.py"]

    def test_tool_calls_empty_list(self):
        evt = events.tool_calls("s", [], {})
        assert evt["tool_calls"] == []

    def test_tool_result_long_content(self):
        content = "x" * 100000
        evt = events.tool_result("s", {
            "name": "bash",
            "content": content,
        }, {})
        assert len(evt["content"]) == 100000

    def test_error_event_with_traceback(self):
        try:
            raise ValueError("traceback test")
        except ValueError as e:
            evt = events.error("s", e, {})
        assert evt["error_type"] == "ValueError"
        assert "traceback test" in evt["error_message"]


class TestSlotErrorPaths:
    def test_read_if_changed_negative_version(self):
        """Negative since_version should return value if any exists."""
        s = Slot()
        s.write("data")
        val = s.read_if_changed(-1)
        assert val is not None
        assert val.data == "data"

    @pytest.mark.asyncio
    async def test_wait_zero_timeout(self):
        """Zero timeout should check once and timeout immediately."""
        s = Slot()
        with pytest.raises(asyncio.TimeoutError):
            await s.wait(timeout=0)

    @pytest.mark.asyncio
    async def test_wait_negative_timeout(self):
        """Negative timeout should raise quickly."""
        s = Slot()
        with pytest.raises((asyncio.TimeoutError, ValueError)):
            await s.wait(timeout=-1)


class TestDiscoveryErrorPaths:
    def test_permission_denied(self, tmp_path):
        """Permission errors should be handled gracefully."""
        import os
        from flatmachines_cli.discovery import _parse_machine_header

        f = tmp_path / "machine.yml"
        f.write_text("spec: flatmachine\ndata: {}")
        os.chmod(str(f), 0o000)

        try:
            result = _parse_machine_header(str(f))
            assert result is None  # should not crash
        finally:
            os.chmod(str(f), 0o644)  # restore

    def test_binary_file(self, tmp_path):
        """Binary files should be handled gracefully."""
        from flatmachines_cli.discovery import _parse_machine_header
        f = tmp_path / "binary.yml"
        f.write_bytes(b"\x00\x01\x02\x03\xff\xfe")
        result = _parse_machine_header(str(f))
        assert result is None  # should not crash


class TestInspectorErrorPaths:
    def test_inspect_invalid_yaml(self, tmp_path):
        from flatmachines_cli.inspector import inspect_machine
        f = tmp_path / "bad.yml"
        f.write_text("{invalid yaml content")
        result = inspect_machine(str(f))
        # Should return an error message, not crash
        assert isinstance(result, str)

    def test_show_context_invalid_yaml(self, tmp_path):
        from flatmachines_cli.inspector import show_context
        f = tmp_path / "bad.yml"
        f.write_text("{invalid yaml content")
        result = show_context(str(f))
        assert isinstance(result, str)

    def test_validate_invalid_yaml(self, tmp_path):
        from flatmachines_cli.inspector import validate_machine
        f = tmp_path / "bad.yml"
        f.write_text("{invalid yaml content")
        result = validate_machine(str(f))
        assert isinstance(result, str)

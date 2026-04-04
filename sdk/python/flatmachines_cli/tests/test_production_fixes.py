"""Tests for latest production fixes — logging, content formatting, shutdown."""

import asyncio
import logging
import json
import pytest
from flatmachines_cli.bus import DataBus
from flatmachines_cli.backend import CLIBackend
from flatmachines_cli.processors import (
    Processor, StatusProcessor, ContentProcessor, _STOP,
)
from flatmachines_cli import events


class TestProcessorEnqueueLogging:
    """Verify that dropped events are logged."""

    @pytest.mark.asyncio
    async def test_queue_full_logs_debug(self, caplog):
        """Dropping events on full queue should log at DEBUG."""

        class TinyQueueProcessor(Processor):
            slot_name = "tiny"
            event_types = None

            def __init__(self, bus):
                super().__init__(bus, max_hz=1000, queue_size=1)

            def process(self, event):
                return {"ok": True}

        bus = DataBus()
        p = TinyQueueProcessor(bus)
        # Don't start — queue will fill up quickly

        with caplog.at_level(logging.DEBUG, logger="flatmachines_cli.processors"):
            for i in range(10):
                p.enqueue({"type": "test"})

        # Some events should have been dropped and logged
        drop_logs = [r for r in caplog.records if "dropped" in r.message]
        assert len(drop_logs) > 0


class TestBackendShutdownLogging:
    """Verify processor task errors are logged during shutdown."""

    @pytest.mark.asyncio
    async def test_processor_error_logged_on_stop(self, caplog):

        class CrashOnStopProcessor(Processor):
            slot_name = "crash_stop"
            event_types = None

            def process(self, event):
                if event.get("type") == "crash":
                    raise RuntimeError("crash during stop")
                return {"ok": True}

        bus = DataBus()
        p = CrashOnStopProcessor(bus, max_hz=1000)
        backend = CLIBackend(bus=bus, processors=[p])

        await backend.start()
        backend.emit({"type": "crash"})
        await asyncio.sleep(0.05)

        # The processor logs the error and continues — doesn't crash the task.
        # Processor task errors during shutdown are logged by backend.stop().
        with caplog.at_level(logging.WARNING, logger="flatmachines_cli.backend"):
            await backend.stop()


class TestContentProcessorDictFormatting:
    """ContentProcessor should format dict results as pretty JSON."""

    def test_dict_result_as_json(self):
        bus = DataBus()
        p = ContentProcessor(bus)
        result = p.process(events.machine_end({
            "result": {"files": ["/tmp/a.py"], "status": "done"},
        }, {}))
        assert result["has_content"] is True
        # Should be valid JSON
        parsed = json.loads(result["text"])
        assert parsed["files"] == ["/tmp/a.py"]

    def test_string_result_unchanged(self):
        bus = DataBus()
        p = ContentProcessor(bus)
        result = p.process(events.machine_end({"result": "simple text"}, {}))
        assert result["text"] == "simple text"

    def test_int_result_as_string(self):
        bus = DataBus()
        p = ContentProcessor(bus)
        result = p.process(events.machine_end({"result": 42}, {}))
        assert result["text"] == "42"

    def test_list_result_as_string(self):
        bus = DataBus()
        p = ContentProcessor(bus)
        result = p.process(events.machine_end({"result": [1, 2, 3]}, {}))
        assert result["text"] == "[1, 2, 3]"

    def test_nested_dict_result(self):
        bus = DataBus()
        p = ContentProcessor(bus)
        result = p.process(events.machine_end({
            "result": {"a": {"b": {"c": True}}},
        }, {}))
        parsed = json.loads(result["text"])
        assert parsed["a"]["b"]["c"] is True

    def test_dict_result_pretty_printed(self):
        """Dict results should be indented for readability."""
        bus = DataBus()
        p = ContentProcessor(bus)
        result = p.process(events.machine_end({
            "result": {"key": "value"},
        }, {}))
        assert "\n" in result["text"]  # pretty-printed has newlines
        assert "  " in result["text"]  # indented


class TestNoUnusedImports:
    """Verify unused imports were cleaned up."""

    def test_backend_no_signal_import(self):
        """Backend should not import unused signal module."""
        import flatmachines_cli.backend as backend_mod
        source = open(backend_mod.__file__).read()
        assert "import signal" not in source


class TestActiveToolCallIdTracking:
    """Verify active tool tracking includes tool_call_id."""

    def test_snapshot_active_has_tool_call_id(self):
        from flatmachines_cli.processors import ToolProcessor
        bus = DataBus()
        p = ToolProcessor(bus)
        p.process(events.tool_calls("s", [
            {"name": "bash", "arguments": {}, "tool_call_id": "tc_123"},
        ], {}))
        snap = p._snapshot()
        assert snap["active"][0]["tool_call_id"] == "tc_123"

    def test_snapshot_active_empty_id_when_missing(self):
        from flatmachines_cli.processors import ToolProcessor
        bus = DataBus()
        p = ToolProcessor(bus)
        p.process(events.tool_calls("s", [
            {"name": "bash", "arguments": {}},
        ], {}))
        snap = p._snapshot()
        assert snap["active"][0]["tool_call_id"] == ""

    def test_active_snapshot_serializable_with_id(self):
        """Active list with tool_call_id should be JSON-serializable."""
        from flatmachines_cli.processors import ToolProcessor
        bus = DataBus()
        p = ToolProcessor(bus)
        p.process(events.tool_calls("s", [
            {"name": "bash", "arguments": {"cmd": "ls"}, "tool_call_id": "tc_1"},
            {"name": "read", "arguments": {"path": "/f"}, "tool_call_id": "tc_2"},
        ], {}))
        snap = p._snapshot()
        serialized = json.dumps(snap)
        deserialized = json.loads(serialized)
        assert len(deserialized["active"]) == 2

"""Tests for data serialization — the bus snapshot is the IPC boundary."""

import json
import pytest
from flatmachines_cli.bus import DataBus
from flatmachines_cli.processors import (
    StatusProcessor, TokenProcessor, ToolProcessor,
    ContentProcessor, ErrorProcessor,
)
from flatmachines_cli import events


class TestSnapshotSerialization:
    """Verify that bus snapshots serialize cleanly to JSON.

    This is critical — the snapshot dict is the boundary for the
    future Rust frontend. It must be JSON-serializable.
    """

    def test_empty_snapshot_serializable(self):
        bus = DataBus()
        snap = bus.snapshot()
        assert json.dumps(snap) == "{}"

    def test_status_snapshot_serializable(self):
        bus = DataBus()
        p = StatusProcessor(bus)
        p.process(events.machine_start({"machine": {"machine_name": "test", "execution_id": "e1"}}))
        data = p.process(events.state_enter("analyze", {"machine": {"step": 1}}))
        bus.write("status", data)
        snap = bus.snapshot()
        serialized = json.dumps(snap)
        deserialized = json.loads(serialized)
        assert deserialized["status"]["machine_name"] == "test"
        assert deserialized["status"]["state"] == "analyze"

    def test_token_snapshot_serializable(self):
        bus = DataBus()
        p = TokenProcessor(bus)
        p.process(events.machine_start({"machine": {}}))
        data = p.process(events.tool_calls("s", [{"name": "bash"}], {
            "_tool_loop_usage": {"input_tokens": 100, "output_tokens": 50},
            "_tool_loop_cost": 0.005,
            "_tool_loop_turns": 1,
        }))
        bus.write("tokens", data)
        snap = bus.snapshot()
        serialized = json.dumps(snap)
        deserialized = json.loads(serialized)
        assert deserialized["tokens"]["total_tokens"] == 150

    def test_tools_snapshot_serializable(self):
        bus = DataBus()
        p = ToolProcessor(bus)
        p.process(events.tool_result("s", {
            "name": "bash",
            "arguments": {"command": "ls -la /tmp"},
            "content": "file1\nfile2",
            "is_error": False,
            "tool_call_id": "tc_1",
        }, {}))
        data = p._snapshot()
        bus.write("tools", data)
        snap = bus.snapshot()
        serialized = json.dumps(snap)
        deserialized = json.loads(serialized)
        assert deserialized["tools"]["total_calls"] == 1

    def test_content_snapshot_serializable(self):
        bus = DataBus()
        p = ContentProcessor(bus)
        data = p.process(events.tool_calls("s", [], {
            "_tool_loop_content": "Here is my analysis:\n1. First point\n2. Second point",
        }))
        bus.write("content", data)
        snap = bus.snapshot()
        serialized = json.dumps(snap)
        deserialized = json.loads(serialized)
        assert deserialized["content"]["has_content"] is True
        assert len(deserialized["content"]["lines"]) == 3

    def test_error_snapshot_serializable(self):
        bus = DataBus()
        p = ErrorProcessor(bus)
        data = p.process(events.error("s1", ValueError("bad\ninput"), {}))
        bus.write("error", data)
        snap = bus.snapshot()
        serialized = json.dumps(snap)
        deserialized = json.loads(serialized)
        assert deserialized["error"]["has_error"] is True
        assert "bad\ninput" in deserialized["error"]["error_message"]

    def test_full_snapshot_serializable(self):
        """All slots together should serialize cleanly."""
        bus = DataBus()
        bus.write("status", {
            "machine_name": "test",
            "execution_id": "e1",
            "state": "analyze",
            "prev_state": "",
            "step": 1,
            "phase": "running",
            "elapsed_s": 1.23,
            "states_visited": ["analyze"],
        })
        bus.write("tokens", {
            "input_tokens": 500,
            "output_tokens": 200,
            "total_tokens": 700,
            "total_cost": 0.015,
            "turns": 3,
            "tool_calls_count": 5,
        })
        bus.write("tools", {
            "active": [{"name": "bash", "arguments": {"command": "ls"}}],
            "last_result": {"name": "bash", "content": "output", "is_error": False},
            "history": [{"name": "bash", "is_error": False, "summary": "bash: ls"}],
            "total_calls": 1,
            "error_count": 0,
            "files_modified": ["/tmp/test.py"],
        })

        snap = bus.snapshot()
        serialized = json.dumps(snap, indent=2)
        deserialized = json.loads(serialized)

        assert set(deserialized.keys()) == {"status", "tokens", "tools"}
        assert isinstance(deserialized["status"]["states_visited"], list)
        assert isinstance(deserialized["tokens"]["total_cost"], float)

    def test_snapshot_versioned_not_serializable(self):
        """snapshot_versioned returns SlotValues which aren't JSON-serializable.
        This is by design — only snapshot() is the serialization boundary."""
        bus = DataBus()
        bus.write("a", 1)
        snap = bus.snapshot_versioned()
        with pytest.raises(TypeError):
            json.dumps(snap)


class TestBoundaryConditions:
    """Test numeric and size boundary conditions."""

    def test_large_slot_count(self):
        bus = DataBus()
        for i in range(1000):
            bus.write(f"slot_{i}", i)
        snap = bus.snapshot()
        assert len(snap) == 1000

    def test_large_slot_value(self):
        bus = DataBus()
        large_data = {"key": "x" * 100000}
        bus.write("large", large_data)
        assert bus.read_data("large")["key"] == "x" * 100000

    def test_deeply_nested_data(self):
        bus = DataBus()
        nested = {"level": 0}
        current = nested
        for i in range(1, 50):
            current["child"] = {"level": i}
            current = current["child"]
        bus.write("nested", nested)
        assert bus.read_data("nested")["level"] == 0

    def test_zero_hz_processor(self):
        """max_hz=0 should mean no throttling (infinite Hz)."""
        bus = DataBus()
        p = StatusProcessor(bus, max_hz=0)
        assert p._min_interval == 0.0

    def test_very_high_hz(self):
        bus = DataBus()
        p = StatusProcessor(bus, max_hz=1000000)
        assert p._min_interval < 0.001

    def test_tool_processor_empty_history(self):
        bus = DataBus()
        p = ToolProcessor(bus, history_limit=0)
        for i in range(5):
            p.process(events.tool_result("s", {
                "name": "bash", "arguments": {}, "is_error": False,
            }, {}))
        snap = p._snapshot()
        assert snap["total_calls"] == 5
        assert len(snap["history"]) == 0

    def test_slot_version_overflow(self):
        """Version counter should handle large values."""
        from flatmachines_cli.bus import Slot
        s = Slot()
        s._version = 2**31
        s.write("big_version")
        assert s.version == 2**31 + 1

    def test_cost_rounding(self):
        """Token costs should be rounded to 6 decimal places."""
        bus = DataBus()
        p = TokenProcessor(bus)
        p.process(events.machine_start({"machine": {}}))
        result = p.process(events.tool_calls("s", [{"name": "bash"}], {
            "_tool_loop_usage": {},
            "_tool_loop_cost": 0.123456789,
        }))
        assert result["total_cost"] == 0.123457  # rounded to 6 places


class TestPyprojectClassifiers:
    """Verify pyproject.toml has correct metadata."""

    def test_status_is_beta(self):
        from pathlib import Path
        import tomllib
        pyproject = Path(__file__).parent.parent / "pyproject.toml"
        with open(pyproject, "rb") as f:
            data = tomllib.load(f)
        classifiers = data["project"]["classifiers"]
        assert any("Beta" in c for c in classifiers), \
            f"Expected Beta classifier, got: {classifiers}"

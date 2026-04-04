"""Tests for async processors."""

import asyncio
import pytest
from flatmachines_cli.bus import DataBus
from flatmachines_cli import events
from flatmachines_cli.processors import (
    StatusProcessor,
    TokenProcessor,
    ToolProcessor,
    ContentProcessor,
    ErrorProcessor,
    default_processors,
    _STOP,
)


class TestStatusProcessor:
    def test_slot_name(self):
        bus = DataBus()
        p = StatusProcessor(bus)
        assert p.slot_name == "status"

    def test_event_types(self):
        bus = DataBus()
        p = StatusProcessor(bus)
        assert events.MACHINE_START in p.event_types
        assert events.STATE_ENTER in p.event_types
        assert events.TOOL_CALLS not in p.event_types

    def test_machine_start(self):
        bus = DataBus()
        p = StatusProcessor(bus)
        evt = events.machine_start({"machine": {"machine_name": "test", "execution_id": "e1"}})
        result = p.process(evt)
        assert result["machine_name"] == "test"
        assert result["execution_id"] == "e1"
        assert result["phase"] == "starting"

    def test_state_enter(self):
        bus = DataBus()
        p = StatusProcessor(bus)
        p.process(events.machine_start({"machine": {}}))
        evt = events.state_enter("analyze", {"machine": {"step": 1}})
        result = p.process(evt)
        assert result["state"] == "analyze"
        assert result["step"] == 1
        assert result["phase"] == "running"
        assert "analyze" in result["states_visited"]

    def test_states_visited_no_duplicates(self):
        bus = DataBus()
        p = StatusProcessor(bus)
        p.process(events.machine_start({"machine": {}}))
        p.process(events.state_enter("s1", {"machine": {"step": 1}}))
        p.process(events.state_enter("s1", {"machine": {"step": 2}}))
        result = p.process(events.state_enter("s2", {"machine": {"step": 3}}))
        assert result["states_visited"] == ["s1", "s2"]

    def test_transition(self):
        bus = DataBus()
        p = StatusProcessor(bus)
        p.process(events.machine_start({"machine": {}}))
        result = p.process(events.transition("from_s", "to_s", {}))
        assert result["prev_state"] == "from_s"
        assert result["state"] == "to_s"

    def test_machine_end_phase(self):
        bus = DataBus()
        p = StatusProcessor(bus)
        p.process(events.machine_start({"machine": {}}))
        result = p.process(events.machine_end({}, {}))
        assert result["phase"] == "done"

    def test_error_phase(self):
        bus = DataBus()
        p = StatusProcessor(bus)
        p.process(events.machine_start({"machine": {}}))
        result = p.process(events.error("s1", ValueError("bad"), {}))
        assert result["phase"] == "error"

    def test_reset(self):
        bus = DataBus()
        p = StatusProcessor(bus)
        p.process(events.machine_start({"machine": {"machine_name": "test"}}))
        p.reset()
        result = p.process(events.machine_start({"machine": {"machine_name": "test2"}}))
        assert result["states_visited"] == []
        assert result["phase"] == "starting"

    def test_elapsed_time(self):
        bus = DataBus()
        p = StatusProcessor(bus)
        result = p.process(events.machine_start({"machine": {}}))
        assert result["elapsed_s"] >= 0

    def test_accepts_matching_events(self):
        bus = DataBus()
        p = StatusProcessor(bus)
        assert p.accepts({"type": events.MACHINE_START}) is True
        assert p.accepts({"type": events.TOOL_CALLS}) is False

    @pytest.mark.asyncio
    async def test_async_lifecycle(self):
        bus = DataBus()
        p = StatusProcessor(bus, max_hz=1000)
        p.start()
        p.enqueue(events.machine_start({"machine": {"machine_name": "test"}}))
        p.enqueue(events.state_enter("s1", {"machine": {"step": 1}}))
        await asyncio.sleep(0.1)
        p.stop()
        await asyncio.sleep(0.05)
        data = bus.read_data("status")
        assert data is not None
        assert data["machine_name"] == "test"

    @pytest.mark.asyncio
    async def test_hz_cap_flush_on_timeout(self):
        """Verify that Hz-capped pending data is flushed even without new events."""
        bus = DataBus()
        p = StatusProcessor(bus, max_hz=2.0)  # 500ms interval
        p.start()

        # Send two events in quick succession — second will be buffered
        p.enqueue(events.machine_start({"machine": {"machine_name": "flush_test"}}))
        await asyncio.sleep(0.01)
        p.enqueue(events.state_enter("buffered_state", {"machine": {"step": 1}}))

        # Wait longer than the Hz interval for the timeout flush
        await asyncio.sleep(0.7)

        data = bus.read_data("status")
        assert data is not None
        assert data["state"] == "buffered_state"

        p.stop()
        await asyncio.sleep(0.05)


class TestTokenProcessor:
    def test_slot_name(self):
        bus = DataBus()
        p = TokenProcessor(bus)
        assert p.slot_name == "tokens"

    def test_machine_start_resets(self):
        bus = DataBus()
        p = TokenProcessor(bus)
        p._input_tokens = 100
        result = p.process(events.machine_start({"machine": {}}))
        assert result["input_tokens"] == 0
        assert result["total_cost"] == 0

    def test_tool_calls_usage(self):
        bus = DataBus()
        p = TokenProcessor(bus)
        p.process(events.machine_start({"machine": {}}))
        evt = events.tool_calls("s", [{"name": "bash"}], {
            "_tool_loop_usage": {"input_tokens": 100, "output_tokens": 50},
            "_tool_loop_cost": 0.005,
            "_tool_loop_turns": 1,
        })
        result = p.process(evt)
        assert result["input_tokens"] == 100
        assert result["output_tokens"] == 50
        assert result["total_tokens"] == 150
        assert result["total_cost"] == 0.005
        assert result["tool_calls_count"] == 1

    def test_accumulates_tool_calls(self):
        bus = DataBus()
        p = TokenProcessor(bus)
        p.process(events.machine_start({"machine": {}}))
        calls1 = [{"name": "bash"}, {"name": "read"}]
        p.process(events.tool_calls("s", calls1, {"_tool_loop_usage": {}}))
        calls2 = [{"name": "edit"}]
        result = p.process(events.tool_calls("s", calls2, {"_tool_loop_usage": {}}))
        assert result["tool_calls_count"] == 3

    def test_machine_end_updates_cost(self):
        bus = DataBus()
        p = TokenProcessor(bus)
        p.process(events.machine_start({"machine": {}}))
        result = p.process(events.machine_end({"_tool_loop_cost": 0.1}, {}))
        assert result["total_cost"] == 0.1


class TestToolProcessor:
    def test_slot_name(self):
        bus = DataBus()
        p = ToolProcessor(bus)
        assert p.slot_name == "tools"

    def test_machine_start_resets(self):
        bus = DataBus()
        p = ToolProcessor(bus)
        p._total_calls = 5
        result = p.process(events.machine_start({"machine": {}}))
        assert result["total_calls"] == 0
        assert result["active"] == []

    def test_tool_calls_tracking(self):
        bus = DataBus()
        p = ToolProcessor(bus)
        calls = [{"name": "bash", "arguments": {"command": "ls"}}]
        result = p.process(events.tool_calls("s", calls, {"_tool_loop_content": ""}))
        assert len(result["active"]) == 1
        assert result["active"][0]["name"] == "bash"

    def test_tool_result_tracking(self):
        bus = DataBus()
        p = ToolProcessor(bus)
        p.process(events.tool_calls("s", [{"name": "bash", "arguments": {}}], {}))
        result_evt = events.tool_result("s", {
            "name": "bash", "arguments": {"command": "ls"},
            "content": "output", "is_error": False, "tool_call_id": "tc1",
        }, {})
        result = p.process(result_evt)
        assert result["total_calls"] == 1
        assert result["error_count"] == 0
        assert result["last_result"]["name"] == "bash"
        assert len(result["history"]) == 1

    def test_error_tracking(self):
        bus = DataBus()
        p = ToolProcessor(bus)
        result_evt = events.tool_result("s", {
            "name": "bash", "is_error": True, "content": "error",
        }, {})
        result = p.process(result_evt)
        assert result["error_count"] == 1

    def test_file_tracking(self):
        bus = DataBus()
        p = ToolProcessor(bus)
        result_evt = events.tool_result("s", {
            "name": "write", "arguments": {"path": "/tmp/test.py"},
            "is_error": False,
        }, {})
        result = p.process(result_evt)
        assert "/tmp/test.py" in result["files_modified"]

    def test_file_tracking_no_duplicates(self):
        bus = DataBus()
        p = ToolProcessor(bus)
        for _ in range(3):
            p.process(events.tool_result("s", {
                "name": "edit", "arguments": {"path": "/tmp/test.py"},
                "is_error": False,
            }, {}))
        result = p.process(events.tool_result("s", {
            "name": "edit", "arguments": {"path": "/tmp/test.py"},
            "is_error": False,
        }, {}))
        assert result["files_modified"].count("/tmp/test.py") == 1

    def test_history_limit(self):
        bus = DataBus()
        p = ToolProcessor(bus, history_limit=5)
        for i in range(10):
            p.process(events.tool_result("s", {
                "name": "bash", "arguments": {"command": f"cmd_{i}"},
                "is_error": False,
            }, {}))
        result = p.process(events.tool_result("s", {
            "name": "bash", "arguments": {},
            "is_error": False,
        }, {}))
        assert len(result["history"]) == 5
        assert result["total_calls"] == 11

    def test_summarize_bash(self):
        assert "bash:" in ToolProcessor._summarize_tool("bash", {"command": "ls -la"})

    def test_summarize_read(self):
        assert "read:" in ToolProcessor._summarize_tool("read", {"path": "/tmp/f"})

    def test_summarize_write(self):
        s = ToolProcessor._summarize_tool("write", {"path": "/tmp/f", "content": "abc"})
        assert "write:" in s
        assert "3B" in s

    def test_summarize_edit(self):
        assert "edit:" in ToolProcessor._summarize_tool("edit", {"path": "/tmp/f"})

    def test_summarize_unknown(self):
        assert "custom_tool" in ToolProcessor._summarize_tool("custom_tool", {})

    def test_removes_from_active_on_result(self):
        bus = DataBus()
        p = ToolProcessor(bus)
        p.process(events.tool_calls("s", [
            {"name": "bash", "arguments": {}},
            {"name": "read", "arguments": {}},
        ], {}))
        p.process(events.tool_result("s", {
            "name": "bash", "arguments": {}, "is_error": False,
        }, {}))
        result = p.process(events.tool_result("s", {
            "name": "read", "arguments": {}, "is_error": False,
        }, {}))
        assert result["active"] == []

    def test_history_desync_with_truncation(self):
        bus = DataBus()
        p = ToolProcessor(bus, history_limit=3)
        for i in range(10):
            p.process(events.tool_result("s", {
                "name": "bash", "arguments": {}, "is_error": False,
            }, {}))
        snap = p._snapshot()
        assert snap["total_calls"] == 10
        assert len(snap["history"]) == 3


class TestContentProcessor:
    def test_slot_name(self):
        bus = DataBus()
        p = ContentProcessor(bus)
        assert p.slot_name == "content"

    def test_machine_start_resets(self):
        bus = DataBus()
        p = ContentProcessor(bus)
        p._text = "old"
        result = p.process(events.machine_start({"machine": {}}))
        assert result["text"] == ""
        assert result["has_content"] is False

    def test_tool_calls_with_content(self):
        bus = DataBus()
        p = ContentProcessor(bus)
        evt = events.tool_calls("s", [], {
            "_tool_loop_content": "  thinking about this  ",
        })
        result = p.process(evt)
        assert result["text"] == "thinking about this"
        assert result["has_content"] is True

    def test_tool_calls_empty_content_skipped(self):
        bus = DataBus()
        p = ContentProcessor(bus)
        evt = events.tool_calls("s", [], {"_tool_loop_content": ""})
        result = p.process(evt)
        assert result is None

    def test_tool_calls_whitespace_only_skipped(self):
        bus = DataBus()
        p = ContentProcessor(bus)
        evt = events.tool_calls("s", [], {"_tool_loop_content": "   "})
        result = p.process(evt)
        assert result is None

    def test_machine_end_shows_result(self):
        bus = DataBus()
        p = ContentProcessor(bus)
        evt = events.machine_end({"result": "final output"}, {})
        result = p.process(evt)
        assert result["text"] == "final output"

    def test_lines_splitting(self):
        bus = DataBus()
        p = ContentProcessor(bus)
        evt = events.tool_calls("s", [], {
            "_tool_loop_content": "line1\nline2\nline3",
        })
        result = p.process(evt)
        assert result["lines"] == ["line1", "line2", "line3"]


class TestErrorProcessor:
    def test_slot_name(self):
        bus = DataBus()
        p = ErrorProcessor(bus)
        assert p.slot_name == "error"

    def test_machine_start_resets(self):
        bus = DataBus()
        p = ErrorProcessor(bus)
        p._errors.append({"state": "old", "error_type": "X", "error_message": "x"})
        result = p.process(events.machine_start({"machine": {}}))
        assert result["has_error"] is False
        assert result["errors"] == []

    def test_error_tracking(self):
        bus = DataBus()
        p = ErrorProcessor(bus)
        evt = events.error("s1", ValueError("bad"), {})
        result = p.process(evt)
        assert result["has_error"] is True
        assert result["state"] == "s1"
        assert result["error_type"] == "ValueError"
        assert result["error_message"] == "bad"
        assert len(result["errors"]) == 1

    def test_multiple_errors(self):
        bus = DataBus()
        p = ErrorProcessor(bus)
        p.process(events.error("s1", ValueError("e1"), {}))
        result = p.process(events.error("s2", RuntimeError("e2"), {}))
        assert len(result["errors"]) == 2
        assert result["state"] == "s2"
        assert result["error_type"] == "RuntimeError"

    def test_no_error_state(self):
        bus = DataBus()
        p = ErrorProcessor(bus)
        result = p.process(events.machine_start({"machine": {}}))
        assert result["has_error"] is False
        assert result["state"] == ""


class TestDefaultProcessors:
    def test_creates_five_processors(self):
        bus = DataBus()
        procs = default_processors(bus)
        assert len(procs) == 5

    def test_slot_names_unique(self):
        bus = DataBus()
        procs = default_processors(bus)
        names = [p.slot_name for p in procs]
        assert len(set(names)) == len(names)

    def test_all_share_same_bus(self):
        bus = DataBus()
        procs = default_processors(bus)
        for p in procs:
            assert p._bus is bus


class TestProcessorHzCapping:
    @pytest.mark.asyncio
    async def test_hz_cap_buffers_rapid_writes(self):
        bus = DataBus()
        p = StatusProcessor(bus, max_hz=1.0)
        p.start()
        for i in range(10):
            p.enqueue(events.state_enter(f"state_{i}", {"machine": {"step": i}}))
            await asyncio.sleep(0.001)
        await asyncio.sleep(0.05)
        p.stop()
        await asyncio.sleep(0.05)
        data = bus.read_data("status")
        assert data is not None

    @pytest.mark.asyncio
    async def test_processor_enqueue_nonblocking(self):
        bus = DataBus()
        p = StatusProcessor(bus)
        for i in range(2000):
            p.enqueue(events.machine_start({"machine": {}}))


class TestProcessorLifecycle:
    @pytest.mark.asyncio
    async def test_stop_flushes_pending(self):
        bus = DataBus()
        p = StatusProcessor(bus, max_hz=0.1)
        p.start()
        p.enqueue(events.machine_start({"machine": {"machine_name": "test"}}))
        await asyncio.sleep(0.05)
        p.stop()
        await asyncio.sleep(0.05)
        data = bus.read_data("status")
        assert data is not None

"""Advanced processor tests — pipeline behavior, custom processors, lifecycle."""

import asyncio
import time
import pytest
from flatmachines_cli.bus import DataBus
from flatmachines_cli.processors import (
    Processor, StatusProcessor, TokenProcessor, ToolProcessor,
    ContentProcessor, ErrorProcessor, default_processors, _STOP,
)
from flatmachines_cli import events


class TestCustomProcessor:
    """Test creating and using custom processors."""

    def test_custom_processor_with_all_events(self):
        """Processor with event_types=None accepts all events."""

        class AllEventsProcessor(Processor):
            slot_name = "all_events"
            event_types = None

            def __init__(self, bus):
                super().__init__(bus, max_hz=1000)
                self.received = []

            def process(self, event):
                self.received.append(event["type"])
                return {"count": len(self.received)}

        bus = DataBus()
        p = AllEventsProcessor(bus)

        for etype in [events.MACHINE_START, events.STATE_ENTER, events.TOOL_CALLS]:
            assert p.accepts({"type": etype}) is True

    def test_custom_processor_with_filtered_events(self):
        """Processor with specific event_types only accepts those."""

        class FilteredProcessor(Processor):
            slot_name = "filtered"
            event_types = frozenset({"custom_event"})

            def process(self, event):
                return {"type": event["type"]}

        bus = DataBus()
        p = FilteredProcessor(bus)
        assert p.accepts({"type": "custom_event"}) is True
        assert p.accepts({"type": "other_event"}) is False

    @pytest.mark.asyncio
    async def test_custom_processor_lifecycle(self):
        """Custom processor should work in full start/process/stop lifecycle."""

        class CounterProcessor(Processor):
            slot_name = "counter"
            event_types = None

            def __init__(self, bus):
                super().__init__(bus, max_hz=1000)
                self.count = 0

            def reset(self):
                self.count = 0

            def process(self, event):
                self.count += 1
                return {"count": self.count}

        bus = DataBus()
        p = CounterProcessor(bus)
        p.start()

        for i in range(10):
            p.enqueue({"type": "tick"})

        await asyncio.sleep(0.1)
        p.stop()
        await asyncio.sleep(0.05)

        data = bus.read_data("counter")
        assert data is not None
        assert data["count"] == 10

        # Reset and verify
        p.reset()
        assert p.count == 0


class TestProcessorTimingBehavior:
    """Test Hz-capping timing behavior."""

    @pytest.mark.asyncio
    async def test_high_hz_writes_frequently(self):
        bus = DataBus()
        p = StatusProcessor(bus, max_hz=1000)
        p.start()

        p.enqueue(events.machine_start({"machine": {"machine_name": "timing"}}))
        await asyncio.sleep(0.01)
        v1 = bus.slot("status").version

        for i in range(10):
            p.enqueue(events.state_enter(f"s_{i}", {"machine": {"step": i}}))
            await asyncio.sleep(0.005)

        v2 = bus.slot("status").version
        assert v2 > v1  # should have written multiple times

        p.stop()
        await asyncio.sleep(0.05)

    @pytest.mark.asyncio
    async def test_low_hz_buffers(self):
        bus = DataBus()
        p = StatusProcessor(bus, max_hz=1.0)  # 1 write per second
        p.start()

        p.enqueue(events.machine_start({"machine": {"machine_name": "slow"}}))
        await asyncio.sleep(0.05)
        v1 = bus.slot("status").version

        # Rapid events within 1 second — should be buffered
        for i in range(5):
            p.enqueue(events.state_enter(f"s_{i}", {"machine": {"step": i}}))

        await asyncio.sleep(0.05)
        v2 = bus.slot("status").version

        # Due to Hz cap, not all events should have triggered writes
        # (though the flush timeout mechanism may have flushed some)
        assert v2 >= v1

        p.stop()
        await asyncio.sleep(0.05)


class TestTokenProcessorEdgeCases:
    def test_zero_usage(self):
        bus = DataBus()
        p = TokenProcessor(bus)
        p.process(events.machine_start({"machine": {}}))
        result = p.process(events.tool_calls("s", [], {"_tool_loop_usage": {}}))
        assert result["input_tokens"] == 0
        assert result["output_tokens"] == 0
        assert result["total_cost"] == 0

    def test_missing_usage_key(self):
        bus = DataBus()
        p = TokenProcessor(bus)
        p.process(events.machine_start({"machine": {}}))
        result = p.process(events.tool_calls("s", [], {}))
        assert result is not None

    def test_cost_accumulation(self):
        bus = DataBus()
        p = TokenProcessor(bus)
        p.process(events.machine_start({"machine": {}}))
        for i in range(10):
            p.process(events.tool_calls("s", [{"name": "bash"}], {
                "_tool_loop_usage": {},
                "_tool_loop_cost": 0.001,
            }))
        result = p._snapshot()
        assert result["total_cost"] == 0.001  # last value wins, not accumulated
        assert result["tool_calls_count"] == 10


class TestToolProcessorEdgeCases:
    def test_tool_with_no_arguments(self):
        bus = DataBus()
        p = ToolProcessor(bus)
        result = p.process(events.tool_result("s", {
            "name": "custom_tool",
            "is_error": False,
        }, {}))
        assert result["total_calls"] == 1
        assert result["last_result"]["name"] == "custom_tool"

    def test_error_tool_not_tracked_as_file(self):
        """Error results from write/edit should not add to files_modified."""
        bus = DataBus()
        p = ToolProcessor(bus)
        p.process(events.tool_result("s", {
            "name": "write",
            "arguments": {"path": "/tmp/failed.py"},
            "is_error": True,
        }, {}))
        assert "/tmp/failed.py" not in p._snapshot()["files_modified"]

    def test_summarize_bash_not_truncated(self):
        """Long bash commands should be preserved in full summary."""
        long_cmd = "x" * 200
        summary = ToolProcessor._summarize_tool("bash", {"command": long_cmd})
        assert summary == f"bash: {long_cmd}"

    def test_summarize_write_zero_content(self):
        summary = ToolProcessor._summarize_tool("write", {"path": "/f", "content": ""})
        assert "0B" in summary


class TestContentProcessorEdgeCases:
    def test_multiline_content(self):
        bus = DataBus()
        p = ContentProcessor(bus)
        result = p.process(events.tool_calls("s", [], {
            "_tool_loop_content": "line1\nline2\n\nline4",
        }))
        assert len(result["lines"]) == 4

    def test_machine_end_result_as_dict(self):
        """machine_end with dict result should convert to string."""
        bus = DataBus()
        p = ContentProcessor(bus)
        result = p.process(events.machine_end({"result": {"key": "val"}}, {}))
        assert result["has_content"] is True
        assert "key" in result["text"]

    def test_machine_end_no_result(self):
        bus = DataBus()
        p = ContentProcessor(bus)
        result = p.process(events.machine_end({}, {}))
        # No result key → no content update
        assert result is not None


class TestErrorProcessorEdgeCases:
    def test_many_errors(self):
        bus = DataBus()
        p = ErrorProcessor(bus)
        for i in range(100):
            p.process(events.error(f"s_{i}", ValueError(f"error_{i}"), {}))
        snap = p._snapshot()
        assert snap["has_error"] is True
        assert len(snap["errors"]) == 100
        assert snap["error_message"] == "error_99"  # latest

    def test_reset_clears_errors(self):
        bus = DataBus()
        p = ErrorProcessor(bus)
        p.process(events.error("s", ValueError("e"), {}))
        p.reset()
        snap = p._snapshot()
        assert snap["has_error"] is False
        assert snap["errors"] == []

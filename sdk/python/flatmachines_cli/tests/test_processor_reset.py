"""Tests for processor stat reset between runs."""

import asyncio
import pytest

from flatmachines_cli.bus import DataBus
from flatmachines_cli.processors import (
    Processor, StatusProcessor, TokenProcessor,
    ToolProcessor, ContentProcessor, ErrorProcessor,
)
from flatmachines_cli import events


class TestStatsResetOnReset:
    @pytest.mark.asyncio
    async def test_base_processor_reset_clears_stats(self):
        class Counter(Processor):
            slot_name = "counter"
            event_types = None
            def process(self, event):
                return {"n": self._events_processed}

        bus = DataBus()
        p = Counter(bus, max_hz=1000)
        p.start()
        for i in range(5):
            p.enqueue({"type": "test"})
        await asyncio.sleep(0.1)
        p.stop()
        await asyncio.sleep(0.05)

        assert p.stats["events_processed"] >= 5

        # Reset clears stats
        p.reset()
        assert p.stats["events_processed"] == 0
        assert p.stats["events_dropped"] == 0
        assert p.stats["queue_hwm"] == 0

    def test_status_processor_reset(self):
        bus = DataBus()
        p = StatusProcessor(bus)
        result = p.process(events.machine_start({"machine": {"machine_name": "test_m"}}))
        assert result["machine_name"] == "test_m"

        p.reset()
        # After reset, machine_name should be cleared
        result = p.process(events.state_enter("s1", {"machine": {}}))
        assert result["machine_name"] == ""

    def test_token_processor_reset(self):
        bus = DataBus()
        p = TokenProcessor(bus)
        p.process(events.machine_start({"machine": {}}))
        p.process(events.tool_calls("s", [], {
            "_tool_loop_usage": {"input_tokens": 100, "output_tokens": 50},
            "_tool_loop_cost": 0.01,
        }))
        snap = p._snapshot()
        assert snap["input_tokens"] > 0

        p.reset()
        snap = p._snapshot()
        assert snap["input_tokens"] == 0
        assert snap["total_cost"] == 0.0

    def test_tool_processor_reset(self):
        bus = DataBus()
        p = ToolProcessor(bus)
        p.process(events.tool_result("s", {
            "name": "bash",
            "arguments": {"command": "ls"},
            "is_error": False,
        }, {}))
        snap = p._snapshot()
        assert snap["total_calls"] == 1

        p.reset()
        snap = p._snapshot()
        assert snap["total_calls"] == 0
        assert snap["history"] == []
        assert snap["files_modified"] == []

    def test_content_processor_reset(self):
        bus = DataBus()
        p = ContentProcessor(bus)
        p.process(events.machine_end({"result": "hello"}, {}))
        snap = p._snapshot()
        assert snap["has_content"] is True

        p.reset()
        snap = p._snapshot()
        assert snap["has_content"] is False

    def test_error_processor_reset(self):
        bus = DataBus()
        p = ErrorProcessor(bus)
        p.process(events.error("s", ValueError("oops"), {}))
        snap = p._snapshot()
        assert snap["has_error"] is True

        p.reset()
        snap = p._snapshot()
        assert snap["has_error"] is False

"""Tests verifying processor event_types filtering works correctly."""

import pytest
from flatmachines_cli.bus import DataBus
from flatmachines_cli.processors import (
    StatusProcessor, TokenProcessor, ToolProcessor,
    ContentProcessor, ErrorProcessor, Processor,
)
from flatmachines_cli import events


class TestStatusProcessorAccepts:
    def test_accepts_machine_start(self):
        bus = DataBus()
        p = StatusProcessor(bus)
        assert p.accepts({"type": events.MACHINE_START})

    def test_accepts_machine_end(self):
        bus = DataBus()
        p = StatusProcessor(bus)
        assert p.accepts({"type": events.MACHINE_END})

    def test_accepts_state_enter(self):
        bus = DataBus()
        p = StatusProcessor(bus)
        assert p.accepts({"type": events.STATE_ENTER})

    def test_rejects_tool_calls(self):
        bus = DataBus()
        p = StatusProcessor(bus)
        assert not p.accepts({"type": events.TOOL_CALLS})


class TestTokenProcessorAccepts:
    def test_accepts_machine_start(self):
        bus = DataBus()
        p = TokenProcessor(bus)
        assert p.accepts({"type": events.MACHINE_START})

    def test_accepts_tool_calls(self):
        bus = DataBus()
        p = TokenProcessor(bus)
        assert p.accepts({"type": events.TOOL_CALLS})

    def test_accepts_machine_end(self):
        bus = DataBus()
        p = TokenProcessor(bus)
        assert p.accepts({"type": events.MACHINE_END})

    def test_rejects_state_enter(self):
        bus = DataBus()
        p = TokenProcessor(bus)
        assert not p.accepts({"type": events.STATE_ENTER})


class TestToolProcessorAccepts:
    def test_accepts_tool_calls(self):
        bus = DataBus()
        p = ToolProcessor(bus)
        assert p.accepts({"type": events.TOOL_CALLS})

    def test_accepts_tool_result(self):
        bus = DataBus()
        p = ToolProcessor(bus)
        assert p.accepts({"type": events.TOOL_RESULT})

    def test_accepts_machine_start(self):
        """ToolProcessor accepts machine_start for reset."""
        bus = DataBus()
        p = ToolProcessor(bus)
        assert p.accepts({"type": events.MACHINE_START})


class TestContentProcessorAccepts:
    def test_accepts_tool_calls(self):
        bus = DataBus()
        p = ContentProcessor(bus)
        assert p.accepts({"type": events.TOOL_CALLS})

    def test_accepts_machine_end(self):
        bus = DataBus()
        p = ContentProcessor(bus)
        assert p.accepts({"type": events.MACHINE_END})

    def test_rejects_state_enter(self):
        bus = DataBus()
        p = ContentProcessor(bus)
        assert not p.accepts({"type": events.STATE_ENTER})


class TestErrorProcessorAccepts:
    def test_accepts_error(self):
        bus = DataBus()
        p = ErrorProcessor(bus)
        assert p.accepts({"type": events.ERROR})

    def test_accepts_machine_start(self):
        """ErrorProcessor accepts machine_start for reset."""
        bus = DataBus()
        p = ErrorProcessor(bus)
        assert p.accepts({"type": events.MACHINE_START})

    def test_rejects_tool_calls(self):
        bus = DataBus()
        p = ErrorProcessor(bus)
        assert not p.accepts({"type": events.TOOL_CALLS})


class TestCustomProcessorAcceptsAll:
    def test_none_event_types_accepts_all(self):
        class Custom(Processor):
            slot_name = "custom"
            event_types = None
            def process(self, event):
                return {}

        bus = DataBus()
        p = Custom(bus)
        for etype in (events.MACHINE_START, events.MACHINE_END,
                      events.STATE_ENTER, events.TOOL_CALLS, "random"):
            assert p.accepts({"type": etype})

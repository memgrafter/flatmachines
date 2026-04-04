"""Defensive access tests — verify nothing crashes on missing/malformed data.

These tests pass pathological inputs through every processor to verify
they handle bad data gracefully (return None or default values).
"""

import pytest

from flatmachines_cli.bus import DataBus
from flatmachines_cli.processors import (
    StatusProcessor, TokenProcessor, ToolProcessor,
    ContentProcessor, ErrorProcessor,
)
from flatmachines_cli import events


class TestStatusProcessorDefensive:
    def test_empty_event(self):
        bus = DataBus()
        p = StatusProcessor(bus)
        result = p.process({"type": "machine_start"})
        assert result is not None

    def test_none_context(self):
        bus = DataBus()
        p = StatusProcessor(bus)
        result = p.process({"type": "state_enter", "state": None, "step": None})
        assert result is not None

    def test_missing_step(self):
        bus = DataBus()
        p = StatusProcessor(bus)
        result = p.process({"type": "state_enter", "state": "s1"})
        assert result is not None

    def test_non_string_state(self):
        bus = DataBus()
        p = StatusProcessor(bus)
        result = p.process({"type": "state_enter", "state": 42})
        assert result is not None


class TestTokenProcessorDefensive:
    def test_missing_usage(self):
        bus = DataBus()
        p = TokenProcessor(bus)
        p.process({"type": "machine_start"})
        result = p.process({"type": "tool_calls", "tool_calls": []})
        assert result is not None

    def test_empty_usage(self):
        bus = DataBus()
        p = TokenProcessor(bus)
        p.process({"type": "machine_start"})
        result = p.process({"type": "tool_calls", "usage": {}, "cost": 0.0})
        assert result is not None

    def test_none_cost(self):
        bus = DataBus()
        p = TokenProcessor(bus)
        p.process({"type": "machine_start"})
        result = p.process({"type": "tool_calls", "cost": None})
        assert result is not None


class TestToolProcessorDefensive:
    def test_tool_call_missing_name(self):
        bus = DataBus()
        p = ToolProcessor(bus)
        result = p.process({"type": "tool_calls", "tool_calls": [{}]})
        assert result is not None

    def test_tool_result_empty(self):
        bus = DataBus()
        p = ToolProcessor(bus)
        result = p.process({"type": "tool_result"})
        assert result is not None

    def test_tool_result_none_name(self):
        bus = DataBus()
        p = ToolProcessor(bus)
        result = p.process({"type": "tool_result", "name": None})
        assert result is not None


class TestContentProcessorDefensive:
    def test_machine_end_no_context(self):
        bus = DataBus()
        p = ContentProcessor(bus)
        result = p.process({"type": "machine_end", "context": {}})
        assert result is not None

    def test_tool_calls_no_content(self):
        bus = DataBus()
        p = ContentProcessor(bus)
        result = p.process({"type": "tool_calls"})
        # No content → should return None (skip)
        assert result is None

    def test_tool_calls_empty_content(self):
        bus = DataBus()
        p = ContentProcessor(bus)
        result = p.process({"type": "tool_calls", "content": ""})
        assert result is None


class TestErrorProcessorDefensive:
    def test_error_missing_fields(self):
        bus = DataBus()
        p = ErrorProcessor(bus)
        result = p.process({"type": "error"})
        assert result is not None

    def test_error_none_values(self):
        bus = DataBus()
        p = ErrorProcessor(bus)
        result = p.process({
            "type": "error",
            "state": None,
            "error_type": None,
            "error_message": None,
        })
        assert result is not None
        assert result["has_error"] is True

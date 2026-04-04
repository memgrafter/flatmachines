"""Tests for parallel tool handling in ToolProcessor."""

import pytest
from flatmachines_cli.bus import DataBus
from flatmachines_cli.processors import ToolProcessor
from flatmachines_cli import events


class TestParallelToolTracking:
    """Test ToolProcessor with multiple concurrent tools of the same name."""

    def test_two_bash_calls_active(self):
        """Two concurrent bash calls should both appear in active."""
        bus = DataBus()
        p = ToolProcessor(bus)
        result = p.process(events.tool_calls("s", [
            {"name": "bash", "arguments": {"command": "ls"}},
            {"name": "bash", "arguments": {"command": "cat file"}},
        ], {}))
        assert len(result["active"]) == 2
        assert all(a["name"] == "bash" for a in result["active"])

    def test_completing_one_bash_keeps_other(self):
        """Completing one bash call should leave the other active."""
        bus = DataBus()
        p = ToolProcessor(bus)

        # Two bash calls
        p.process(events.tool_calls("s", [
            {"name": "bash", "arguments": {"command": "ls"}},
            {"name": "bash", "arguments": {"command": "cat file"}},
        ], {}))

        # Complete one
        result = p.process(events.tool_result("s", {
            "name": "bash",
            "arguments": {"command": "ls"},
            "content": "output",
            "is_error": False,
        }, {}))

        # One should remain active
        assert len(result["active"]) == 1
        assert result["active"][0]["name"] == "bash"

    def test_completing_both_bash_calls(self):
        """Completing both bash calls should clear active."""
        bus = DataBus()
        p = ToolProcessor(bus)

        p.process(events.tool_calls("s", [
            {"name": "bash", "arguments": {"command": "ls"}},
            {"name": "bash", "arguments": {"command": "cat"}},
        ], {}))

        p.process(events.tool_result("s", {
            "name": "bash", "arguments": {}, "is_error": False,
        }, {}))
        result = p.process(events.tool_result("s", {
            "name": "bash", "arguments": {}, "is_error": False,
        }, {}))

        assert result["active"] == []
        assert result["total_calls"] == 2

    def test_mixed_tool_types_active(self):
        """Different tool types should coexist in active list."""
        bus = DataBus()
        p = ToolProcessor(bus)

        result = p.process(events.tool_calls("s", [
            {"name": "bash", "arguments": {"command": "ls"}},
            {"name": "read", "arguments": {"path": "/tmp/file"}},
            {"name": "bash", "arguments": {"command": "cat"}},
        ], {}))
        assert len(result["active"]) == 3

        # Complete the read
        result = p.process(events.tool_result("s", {
            "name": "read", "arguments": {}, "is_error": False,
        }, {}))
        assert len(result["active"]) == 2
        assert all(a["name"] == "bash" for a in result["active"])

    def test_completing_nonexistent_tool(self):
        """Completing a tool that isn't in active should not crash."""
        bus = DataBus()
        p = ToolProcessor(bus)

        # No active tools
        result = p.process(events.tool_result("s", {
            "name": "ghost",
            "arguments": {},
            "is_error": False,
        }, {}))

        assert result["active"] == []
        assert result["total_calls"] == 1

    def test_three_parallel_same_name(self):
        """Three parallel tools with same name, complete one at a time."""
        bus = DataBus()
        p = ToolProcessor(bus)

        p.process(events.tool_calls("s", [
            {"name": "bash", "arguments": {"command": "a"}},
            {"name": "bash", "arguments": {"command": "b"}},
            {"name": "bash", "arguments": {"command": "c"}},
        ], {}))

        # Complete first
        result = p.process(events.tool_result("s", {
            "name": "bash", "arguments": {}, "is_error": False,
        }, {}))
        assert len(result["active"]) == 2

        # Complete second
        result = p.process(events.tool_result("s", {
            "name": "bash", "arguments": {}, "is_error": False,
        }, {}))
        assert len(result["active"]) == 1

        # Complete third
        result = p.process(events.tool_result("s", {
            "name": "bash", "arguments": {}, "is_error": False,
        }, {}))
        assert len(result["active"]) == 0

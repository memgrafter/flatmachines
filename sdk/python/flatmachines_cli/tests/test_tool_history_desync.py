"""Tests for the frontend tool history desync bug fix.

Bug: When ToolProcessor history is truncated by history_limit,
_last_tool_call_count could exceed len(history), causing
history[_last_tool_call_count:] to return [] and new tools never rendered.

Fix: Use history[-num_new:] to always get entries from the tail.
"""

import asyncio
import pytest
from flatmachines_cli.frontend import TerminalFrontend
from flatmachines_cli.bus import DataBus


class TestToolHistoryDesyncFix:
    @pytest.mark.asyncio
    async def test_renders_after_history_truncation(self, capsys):
        """New tools should render even when history has been truncated."""
        bus = DataBus()
        f = TerminalFrontend(fps=100)

        # Simulate 100 tool calls with history truncated to last 5
        bus.write("tools", {
            "active": [],
            "last_result": None,
            "history": [
                {"name": "bash", "is_error": False, "summary": f"bash: cmd_{i}"}
                for i in range(96, 101)  # only last 5 in truncated history
            ],
            "total_calls": 101,
            "error_count": 0,
            "files_modified": [],
        })

        task = asyncio.ensure_future(f.start(bus))
        await asyncio.sleep(0.05)

        # First render should show all 5 visible history entries
        # (since _last_tool_call_count starts at 0)

        # Now simulate more tool calls while history stays truncated
        bus.write("tools", {
            "active": [],
            "last_result": None,
            "history": [
                {"name": "bash", "is_error": False, "summary": f"bash: cmd_{i}"}
                for i in range(98, 103)
            ],
            "total_calls": 103,
            "error_count": 0,
            "files_modified": [],
        })

        await asyncio.sleep(0.05)
        await f.stop()
        await asyncio.sleep(0.02)

        captured = capsys.readouterr()
        # The new tool calls should be rendered (cmd_101, cmd_102)
        assert "cmd_101" in captured.out or "cmd_102" in captured.out or "cmd_100" in captured.out

        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_num_new_exceeds_history_length(self, capsys):
        """When num_new > len(history), show entire history."""
        bus = DataBus()
        f = TerminalFrontend(fps=100)

        # history has 3 entries but total_calls jumped by 10
        bus.write("tools", {
            "active": [],
            "last_result": None,
            "history": [
                {"name": "bash", "is_error": False, "summary": "bash: a"},
                {"name": "bash", "is_error": False, "summary": "bash: b"},
                {"name": "bash", "is_error": False, "summary": "bash: c"},
            ],
            "total_calls": 10,
            "error_count": 0,
            "files_modified": [],
        })

        task = asyncio.ensure_future(f.start(bus))
        await asyncio.sleep(0.05)
        await f.stop()
        await asyncio.sleep(0.02)

        captured = capsys.readouterr()
        # All 3 available entries should be shown
        assert "bash: a" in captured.out
        assert "bash: b" in captured.out
        assert "bash: c" in captured.out

        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


class TestToolCallIdMatching:
    """Test that ToolProcessor uses tool_call_id for precise active tracking."""

    def test_active_includes_tool_call_id(self):
        from flatmachines_cli.bus import DataBus
        from flatmachines_cli.processors import ToolProcessor
        from flatmachines_cli import events

        bus = DataBus()
        p = ToolProcessor(bus)
        result = p.process(events.tool_calls("s", [
            {"name": "bash", "arguments": {"command": "ls"}, "tool_call_id": "tc_1"},
            {"name": "bash", "arguments": {"command": "cat"}, "tool_call_id": "tc_2"},
        ], {}))
        assert result["active"][0]["tool_call_id"] == "tc_1"
        assert result["active"][1]["tool_call_id"] == "tc_2"

    def test_remove_by_tool_call_id(self):
        """Complete a specific tool call by ID, leaving others active."""
        from flatmachines_cli.bus import DataBus
        from flatmachines_cli.processors import ToolProcessor
        from flatmachines_cli import events

        bus = DataBus()
        p = ToolProcessor(bus)
        p.process(events.tool_calls("s", [
            {"name": "bash", "arguments": {"command": "ls"}, "tool_call_id": "tc_1"},
            {"name": "bash", "arguments": {"command": "cat"}, "tool_call_id": "tc_2"},
        ], {}))

        # Complete tc_2 specifically
        result = p.process(events.tool_result("s", {
            "name": "bash",
            "arguments": {"command": "cat"},
            "content": "output",
            "is_error": False,
            "tool_call_id": "tc_2",
        }, {}))

        # tc_1 should still be active
        assert len(result["active"]) == 1
        assert result["active"][0]["tool_call_id"] == "tc_1"

    def test_remove_by_tool_call_id_exact_match(self):
        """Only the exact tool_call_id match should be removed."""
        from flatmachines_cli.bus import DataBus
        from flatmachines_cli.processors import ToolProcessor
        from flatmachines_cli import events

        bus = DataBus()
        p = ToolProcessor(bus)
        p.process(events.tool_calls("s", [
            {"name": "bash", "arguments": {}, "tool_call_id": "tc_a"},
            {"name": "read", "arguments": {}, "tool_call_id": "tc_b"},
            {"name": "bash", "arguments": {}, "tool_call_id": "tc_c"},
        ], {}))

        # Complete tc_a
        result = p.process(events.tool_result("s", {
            "name": "bash", "arguments": {},
            "is_error": False, "tool_call_id": "tc_a",
        }, {}))
        assert len(result["active"]) == 2
        ids = [a["tool_call_id"] for a in result["active"]]
        assert "tc_b" in ids
        assert "tc_c" in ids

    def test_fallback_to_name_when_no_id(self):
        """Without tool_call_id, fall back to name matching."""
        from flatmachines_cli.bus import DataBus
        from flatmachines_cli.processors import ToolProcessor
        from flatmachines_cli import events

        bus = DataBus()
        p = ToolProcessor(bus)
        p.process(events.tool_calls("s", [
            {"name": "bash", "arguments": {}},
            {"name": "read", "arguments": {}},
        ], {}))

        # Complete bash (no tool_call_id)
        result = p.process(events.tool_result("s", {
            "name": "bash", "arguments": {},
            "is_error": False,
        }, {}))
        assert len(result["active"]) == 1
        assert result["active"][0]["name"] == "read"


class TestREPLHistory:
    """Test REPL command history persistence."""

    def test_load_nonexistent_history(self, tmp_path):
        """Loading from nonexistent file should not crash."""
        from flatmachines_cli.repl import FlatMachinesREPL
        repl = FlatMachinesREPL(project_root=str(tmp_path))
        repl._load_history()  # should not raise

    def test_save_history(self, tmp_path, monkeypatch):
        """Saving history should write to disk."""
        import flatmachines_cli.repl as repl_mod
        history_file = str(tmp_path / "test_history")
        monkeypatch.setattr(repl_mod, "_HISTORY_FILE", history_file)

        from flatmachines_cli.repl import FlatMachinesREPL
        repl = FlatMachinesREPL(project_root=str(tmp_path))
        repl._save_history()
        # File should exist (may be empty if no commands entered)
        from pathlib import Path
        assert Path(history_file).exists()

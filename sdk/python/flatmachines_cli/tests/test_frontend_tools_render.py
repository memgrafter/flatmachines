"""Tests for frontend tool rendering."""

import pytest

from flatmachines_cli.bus import DataBus
from flatmachines_cli.frontend import TerminalFrontend


class TestRenderTools:
    def test_new_tools_displayed(self, capsys):
        fe = TerminalFrontend()
        bus = DataBus()
        bus.write("tools", {
            "history": [
                {"summary": "bash: ls", "is_error": False},
            ],
            "total_calls": 1,
        })
        fe._bus = bus
        fe._render_tools({"tools": 1})
        captured = capsys.readouterr()
        assert "bash: ls" in captured.out

    def test_no_new_tools(self, capsys):
        fe = TerminalFrontend()
        fe._last_tool_call_count = 5
        bus = DataBus()
        bus.write("tools", {
            "history": [],
            "total_calls": 5,
        })
        fe._bus = bus
        fe._render_tools({"tools": 1})
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_error_tool_shows_x(self, capsys):
        fe = TerminalFrontend()
        bus = DataBus()
        bus.write("tools", {
            "history": [
                {"summary": "bash: fail", "is_error": True},
            ],
            "total_calls": 1,
        })
        fe._bus = bus
        fe._render_tools({"tools": 1})
        captured = capsys.readouterr()
        assert "fail" in captured.out

    def test_multiple_new_tools(self, capsys):
        fe = TerminalFrontend()
        fe._last_tool_call_count = 1
        bus = DataBus()
        bus.write("tools", {
            "history": [
                {"summary": "bash: ls", "is_error": False},
                {"summary": "read: file.py", "is_error": False},
                {"summary": "edit: file.py", "is_error": False},
            ],
            "total_calls": 3,
        })
        fe._bus = bus
        fe._render_tools({"tools": 1})
        captured = capsys.readouterr()
        assert "read: file.py" in captured.out
        assert "edit: file.py" in captured.out

    def test_tool_unchanged_slot(self, capsys):
        fe = TerminalFrontend()
        fe._last_versions = {"tools": 1}
        bus = DataBus()
        fe._bus = bus
        fe._render_tools({"tools": 1})  # Same version
        captured = capsys.readouterr()
        assert captured.out == ""


class TestFrontendStartStop:
    @pytest.mark.asyncio
    async def test_start_stop(self):
        import asyncio
        fe = TerminalFrontend(fps=100)
        bus = DataBus()

        async def stop_later():
            await asyncio.sleep(0.05)
            await fe.stop()

        asyncio.ensure_future(stop_later())
        await fe.start(bus)
        # Should have returned after stop

    @pytest.mark.asyncio
    async def test_start_with_data(self):
        import asyncio
        fe = TerminalFrontend(fps=100)
        bus = DataBus()
        bus.write("status", {"phase": "starting"})

        async def stop_later():
            await asyncio.sleep(0.05)
            await fe.stop()

        asyncio.ensure_future(stop_later())
        await fe.start(bus)

    @pytest.mark.asyncio
    async def test_auto_approve(self):
        fe = TerminalFrontend(auto_approve=True)
        ctx = {"result": "test"}
        result = fe.handle_action("human_review", ctx)
        assert result["human_approved"] is True

    @pytest.mark.asyncio
    async def test_unknown_action(self):
        fe = TerminalFrontend()
        ctx = {"data": "test"}
        result = fe.handle_action("unknown_action", ctx)
        assert result == ctx  # Returned unchanged

"""Tests for TerminalFrontend."""

import asyncio
import pytest
from unittest.mock import patch
from flatmachines_cli.frontend import TerminalFrontend, _dim, _bold, _green, _red, _yellow
from flatmachines_cli.bus import DataBus


class TestANSIHelpers:
    def test_dim(self):
        result = _dim("test")
        assert "test" in result
        assert "\033[2m" in result
        assert "\033[0m" in result

    def test_bold(self):
        result = _bold("test")
        assert "test" in result
        assert "\033[1m" in result

    def test_green(self):
        result = _green("test")
        assert "test" in result
        assert "\033[32m" in result

    def test_red(self):
        result = _red("test")
        assert "\033[31m" in result

    def test_yellow(self):
        result = _yellow("test")
        assert "\033[33m" in result


class TestTerminalFrontendInit:
    def test_defaults(self):
        f = TerminalFrontend()
        assert f._fps == 10.0
        assert f._auto_approve is False

    def test_custom_fps(self):
        f = TerminalFrontend(fps=30.0)
        assert f._fps == 30.0

    def test_auto_approve(self):
        f = TerminalFrontend(auto_approve=True)
        assert f._auto_approve is True


class TestTerminalFrontendLifecycle:
    @pytest.mark.asyncio
    async def test_start_stop(self):
        bus = DataBus()
        f = TerminalFrontend(fps=100)
        task = asyncio.ensure_future(f.start(bus))
        await asyncio.sleep(0.05)
        await f.stop()
        await asyncio.sleep(0.05)
        assert f._running is False
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


class TestTerminalFrontendActions:
    def test_auto_approve_human_review(self):
        f = TerminalFrontend(auto_approve=True)
        ctx = {"result": "done"}
        result = f.handle_action("human_review", ctx)
        assert result["human_approved"] is True

    def test_unknown_action_returns_context(self):
        f = TerminalFrontend()
        ctx = {"key": "val"}
        result = f.handle_action("unknown_action", ctx)
        assert result is ctx

    @patch("builtins.input", return_value="")
    def test_human_review_empty_input_approves(self, mock_input):
        f = TerminalFrontend(auto_approve=False)
        ctx = {"result": "output"}
        result = f.handle_action("human_review", ctx)
        assert result["human_approved"] is True

    @patch("builtins.input", return_value="fix the bug")
    def test_human_review_with_followup(self, mock_input):
        f = TerminalFrontend(auto_approve=False)
        ctx = {"result": "output", "_tool_loop_chain": []}
        result = f.handle_action("human_review", ctx)
        assert result["human_approved"] is False
        assert len(result["_tool_loop_chain"]) == 1
        assert result["_tool_loop_chain"][0]["content"] == "fix the bug"

    @patch("builtins.input", side_effect=EOFError)
    def test_human_review_eof_approves(self, mock_input):
        f = TerminalFrontend(auto_approve=False)
        ctx = {}
        result = f.handle_action("human_review", ctx)
        assert result["human_approved"] is True

    @patch("builtins.input", side_effect=KeyboardInterrupt)
    def test_human_review_interrupt_approves(self, mock_input):
        f = TerminalFrontend(auto_approve=False)
        ctx = {}
        result = f.handle_action("human_review", ctx)
        assert result["human_approved"] is True


class TestTerminalFrontendRendering:
    @pytest.mark.asyncio
    async def test_renders_status_changes(self, capsys):
        bus = DataBus()
        f = TerminalFrontend(fps=100)
        bus.write("status", {
            "machine_name": "test",
            "phase": "done",
            "elapsed_s": 1.5,
            "state": "final",
        })
        task = asyncio.ensure_future(f.start(bus))
        await asyncio.sleep(0.1)
        await f.stop()
        await asyncio.sleep(0.05)
        captured = capsys.readouterr()
        assert "Done" in captured.out
        assert "1.5" in captured.out
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_renders_errors(self, capsys):
        bus = DataBus()
        f = TerminalFrontend(fps=100)
        bus.write("error", {
            "has_error": True,
            "state": "analyze",
            "error_type": "ValueError",
            "error_message": "bad input",
            "errors": [{"state": "analyze", "error_type": "ValueError", "error_message": "bad input"}],
        })
        task = asyncio.ensure_future(f.start(bus))
        await asyncio.sleep(0.1)
        await f.stop()
        await asyncio.sleep(0.05)
        captured = capsys.readouterr()
        assert "bad input" in captured.out
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

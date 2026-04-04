"""Advanced frontend tests — rendering, lifecycle, and action edge cases."""

import asyncio
import pytest
from unittest.mock import patch
from flatmachines_cli.frontend import TerminalFrontend, _dim, _bold, _green, _red, _yellow
from flatmachines_cli.bus import DataBus


class TestFrontendReset:
    """Test that frontend state resets properly between runs."""

    @pytest.mark.asyncio
    async def test_state_reset_on_start(self):
        bus = DataBus()
        f = TerminalFrontend(fps=100)

        # Simulate first run
        task = asyncio.ensure_future(f.start(bus))
        await asyncio.sleep(0.02)
        f._last_tool_call_count = 10
        f._last_content_text = "old content"
        f._printed_done = True
        await f.stop()
        await asyncio.sleep(0.02)

        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # Start again — state should reset
        task = asyncio.ensure_future(f.start(bus))
        await asyncio.sleep(0.02)

        assert f._last_tool_call_count == 0
        assert f._last_content_text == ""
        assert f._printed_done is False

        await f.stop()
        await asyncio.sleep(0.02)

        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


class TestHumanReviewEdgeCases:
    def test_auto_approve_preserves_context(self):
        f = TerminalFrontend(auto_approve=True)
        ctx = {"result": "output", "extra": "data", "nested": {"key": True}}
        result = f.handle_action("human_review", ctx)
        assert result["human_approved"] is True
        assert result["extra"] == "data"
        assert result["nested"]["key"] is True

    @patch("builtins.input", return_value="   ")
    def test_whitespace_input_approves(self, mock_input):
        """Whitespace-only input should be treated as empty (approve)."""
        f = TerminalFrontend(auto_approve=False)
        ctx = {"result": "output"}
        result = f.handle_action("human_review", ctx)
        # input().strip() = "" → approve
        assert result["human_approved"] is True

    @patch("builtins.input", return_value="continue working on it")
    def test_followup_creates_user_message(self, mock_input):
        f = TerminalFrontend(auto_approve=False)
        ctx = {"result": "partial"}
        result = f.handle_action("human_review", ctx)
        assert result["human_approved"] is False
        chain = result["_tool_loop_chain"]
        assert len(chain) == 1
        assert chain[0]["role"] == "user"
        assert chain[0]["content"] == "continue working on it"

    @patch("builtins.input", return_value="more work")
    def test_followup_appends_to_existing_chain(self, mock_input):
        f = TerminalFrontend(auto_approve=False)
        existing = [{"role": "user", "content": "first"}]
        ctx = {"result": "partial", "_tool_loop_chain": existing}
        result = f.handle_action("human_review", ctx)
        assert len(result["_tool_loop_chain"]) == 2

    def test_unknown_action_passthrough(self):
        f = TerminalFrontend()
        ctx = {"data": "original"}
        result = f.handle_action("unknown_custom_action", ctx)
        assert result is ctx


class TestANSIHelperEdgeCases:
    def test_empty_string(self):
        assert "\033[" in _dim("")
        assert "\033[" in _bold("")
        assert "\033[" in _green("")
        assert "\033[" in _red("")
        assert "\033[" in _yellow("")

    def test_special_characters(self):
        assert "hello\nworld" in _dim("hello\nworld")
        assert "tab\there" in _bold("tab\there")

    def test_nested_ansi(self):
        """Nesting ANSI codes should not crash."""
        inner = _bold("bold")
        outer = _dim(inner)
        assert "\033[" in outer


class TestFrontendWithComplexBusData:
    @pytest.mark.asyncio
    async def test_all_slots_populated(self, capsys):
        """Frontend should handle all slots being populated simultaneously."""
        bus = DataBus()
        f = TerminalFrontend(fps=100)

        bus.write("status", {
            "machine_name": "complex",
            "phase": "running",
            "elapsed_s": 0.5,
        })
        bus.write("content", {
            "text": "Analyzing the code...",
            "lines": ["Analyzing the code..."],
            "has_content": True,
        })
        bus.write("tools", {
            "active": [{"name": "bash", "arguments": {"command": "ls"}}],
            "last_result": None,
            "history": [{"name": "read", "is_error": False, "summary": "read: /tmp/f"}],
            "total_calls": 1,
            "error_count": 0,
            "files_modified": [],
        })
        bus.write("tokens", {
            "input_tokens": 100,
            "output_tokens": 50,
            "total_tokens": 150,
            "total_cost": 0.003,
            "turns": 1,
            "tool_calls_count": 1,
        })

        task = asyncio.ensure_future(f.start(bus))
        await asyncio.sleep(0.1)
        await f.stop()
        await asyncio.sleep(0.02)

        captured = capsys.readouterr()
        # Should have rendered something from multiple slots
        assert len(captured.out) > 0

        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_no_crash_on_unexpected_slot_data(self, capsys):
        """Frontend should not crash on unexpected data shapes."""
        bus = DataBus()
        f = TerminalFrontend(fps=100)

        # Write weird but valid data
        bus.write("status", None)
        bus.write("content", 42)
        bus.write("tools", "not a dict")

        task = asyncio.ensure_future(f.start(bus))
        await asyncio.sleep(0.05)
        await f.stop()
        await asyncio.sleep(0.02)

        # Should not crash
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

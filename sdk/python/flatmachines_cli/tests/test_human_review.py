"""Tests for human review input handling."""

import asyncio
import pytest
from unittest.mock import patch, MagicMock

from flatmachines_cli.frontend import TerminalFrontend, _safe_input


class TestSafeInput:
    def test_eof_returns_empty(self):
        with patch("builtins.input", side_effect=EOFError):
            assert _safe_input() == ""

    def test_keyboard_interrupt_returns_empty(self):
        with patch("builtins.input", side_effect=KeyboardInterrupt):
            assert _safe_input() == ""

    def test_normal_input(self):
        with patch("builtins.input", return_value="hello"):
            assert _safe_input() == "hello"

    def test_whitespace_stripped(self):
        with patch("builtins.input", return_value="  answer  "):
            assert _safe_input() == "answer"


class TestPromptUser:
    def test_outside_event_loop(self):
        """When no event loop is running, calls input directly."""
        with patch("builtins.input", return_value="direct"):
            result = TerminalFrontend._prompt_user()
            assert result == "direct"

    def test_eof_outside_loop(self):
        with patch("builtins.input", side_effect=EOFError):
            result = TerminalFrontend._prompt_user()
            assert result == ""


class TestHumanReviewAction:
    def test_auto_approve(self):
        fe = TerminalFrontend(auto_approve=True)
        ctx = {"result": "done"}
        result = fe._human_review(ctx)
        assert result["human_approved"] is True

    def test_empty_response_approves(self):
        fe = TerminalFrontend()
        with patch.object(fe, "_prompt_user", return_value=""):
            ctx = {"result": "done"}
            result = fe._human_review(ctx)
            assert result["human_approved"] is True

    def test_response_adds_to_chain(self):
        fe = TerminalFrontend()
        with patch.object(fe, "_prompt_user", return_value="do more"):
            ctx = {"result": "done"}
            result = fe._human_review(ctx)
            assert result["human_approved"] is False
            assert result["_tool_loop_chain"][-1]["content"] == "do more"

    def test_response_appends_to_existing_chain(self):
        fe = TerminalFrontend()
        existing = [{"role": "user", "content": "first"}]
        with patch.object(fe, "_prompt_user", return_value="second"):
            ctx = {"result": "done", "_tool_loop_chain": existing}
            result = fe._human_review(ctx)
            assert len(result["_tool_loop_chain"]) == 2
            assert result["_tool_loop_chain"][1]["content"] == "second"

    def test_no_result_no_crash(self):
        fe = TerminalFrontend(auto_approve=True)
        ctx = {}
        result = fe._human_review(ctx)
        assert result["human_approved"] is True

    def test_files_modified_displayed(self, capsys):
        fe = TerminalFrontend(auto_approve=True)
        ctx = {"files_modified": ["a.py", "b.py"]}
        fe._human_review(ctx)
        captured = capsys.readouterr()
        assert "a.py" in captured.out
        assert "b.py" in captured.out

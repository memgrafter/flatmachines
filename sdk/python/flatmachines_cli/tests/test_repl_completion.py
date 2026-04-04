"""Tests for REPL tab-completion."""

import pytest
from unittest.mock import patch, MagicMock

from flatmachines_cli.repl import FlatMachinesREPL


class TestCompleterCommands:
    def test_complete_empty(self):
        repl = FlatMachinesREPL()
        with patch("readline.get_line_buffer", return_value=""):
            result = repl._completer("", 0)
            assert result is not None  # Should return first command

    def test_complete_l(self):
        repl = FlatMachinesREPL()
        with patch("readline.get_line_buffer", return_value="l"):
            result = repl._completer("l", 0)
            assert result in ("list", "ls")

    def test_complete_he(self):
        repl = FlatMachinesREPL()
        with patch("readline.get_line_buffer", return_value="he"):
            result = repl._completer("he", 0)
            assert result == "help"

    def test_complete_q(self):
        repl = FlatMachinesREPL()
        with patch("readline.get_line_buffer", return_value="q"):
            result = repl._completer("q", 0)
            assert result == "quit"

    def test_complete_no_match(self):
        repl = FlatMachinesREPL()
        with patch("readline.get_line_buffer", return_value="zzz"):
            result = repl._completer("zzz", 0)
            assert result is None

    def test_complete_state_overflow(self):
        """Requesting state beyond matches returns None."""
        repl = FlatMachinesREPL()
        with patch("readline.get_line_buffer", return_value="he"):
            result = repl._completer("he", 100)
            assert result is None


class TestCompleterMachines:
    def test_complete_inspect_arg(self):
        repl = FlatMachinesREPL()
        # Mock machine index
        mock_info = MagicMock()
        mock_info.name = "test_machine"
        repl._index.list_all = MagicMock(return_value=[mock_info])

        with patch("readline.get_line_buffer", return_value="inspect tes"):
            result = repl._completer("tes", 0)
            assert result == "test_machine"

    def test_complete_run_arg(self):
        repl = FlatMachinesREPL()
        mock_info = MagicMock()
        mock_info.name = "my_flow"
        repl._index.list_all = MagicMock(return_value=[mock_info])

        with patch("readline.get_line_buffer", return_value="run my"):
            result = repl._completer("my", 0)
            assert result == "my_flow"

    def test_complete_non_machine_command(self):
        """Commands like 'help' don't complete machine names."""
        repl = FlatMachinesREPL()
        with patch("readline.get_line_buffer", return_value="help foo"):
            result = repl._completer("foo", 0)
            assert result is None

    def test_completer_exception_safe(self):
        """Completer should never raise, even on errors."""
        repl = FlatMachinesREPL()
        repl._index.list_all = MagicMock(side_effect=RuntimeError("boom"))

        with patch("readline.get_line_buffer", return_value="inspect x"):
            result = repl._completer("x", 0)
            assert result is None  # Error handled silently

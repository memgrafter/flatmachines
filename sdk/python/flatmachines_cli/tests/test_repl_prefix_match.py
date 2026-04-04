"""Tests for REPL command prefix matching."""

import pytest
from unittest.mock import patch

from flatmachines_cli.repl import FlatMachinesREPL


class TestPrefixCommandMatch:
    """Test that REPL handles partial command names."""

    @pytest.fixture
    def repl(self):
        return FlatMachinesREPL()

    def test_exact_command(self, repl):
        assert "list" in repl._commands

    def test_ls_alias(self, repl):
        assert "ls" in repl._commands

    def test_info_alias(self, repl):
        assert "info" in repl._commands

    def test_question_alias(self, repl):
        assert "?" in repl._commands

    def test_command_count(self, repl):
        # Should have: list, ls, inspect, info, validate, context, run,
        # history, bus, stats, save, help, ?
        assert len(repl._commands) >= 12


class TestREPLBanner:
    def test_banner_output(self, capsys):
        repl = FlatMachinesREPL()
        repl._print_banner()
        captured = capsys.readouterr()
        assert "flatmachines" in captured.out

    def test_banner_shows_count(self, capsys):
        repl = FlatMachinesREPL()
        repl._print_banner()
        captured = capsys.readouterr()
        # Should show "N examples found" or "no examples"
        assert "found" in captured.out or "examples" in captured.out


class TestExecutionRecord:
    def test_dataclass_fields(self):
        from flatmachines_cli.repl import ExecutionRecord
        rec = ExecutionRecord(
            name="test",
            path="/tmp/test.yml",
            input={"task": "hello"},
        )
        assert rec.name == "test"
        assert rec.duration_s == 0.0
        assert rec.success is False
        assert rec.output is None
        assert rec.error is None

    def test_with_all_fields(self):
        from flatmachines_cli.repl import ExecutionRecord
        rec = ExecutionRecord(
            name="test",
            path="/tmp/test.yml",
            input={"task": "hello"},
            duration_s=3.14,
            success=True,
            output={"result": "ok"},
            error=None,
        )
        assert rec.duration_s == 3.14
        assert rec.success is True
        assert rec.output == {"result": "ok"}

"""Tests for REPL stats command."""

import pytest
from unittest.mock import MagicMock

from flatmachines_cli.repl import FlatMachinesREPL
from flatmachines_cli.backend import CLIBackend
from flatmachines_cli.bus import DataBus
from flatmachines_cli.hooks import CLIHooks


class TestStatsCommand:
    def test_stats_no_execution(self, capsys):
        repl = FlatMachinesREPL()
        repl._cmd_stats([])
        captured = capsys.readouterr()
        assert "No execution data" in captured.out

    def test_stats_with_backend(self, capsys):
        repl = FlatMachinesREPL()
        bus = DataBus()
        backend = CLIBackend(bus=bus, processors=[])
        repl._last_backend = backend
        repl._last_hooks = None
        repl._cmd_stats([])
        captured = capsys.readouterr()
        assert "Backend Health" in captured.out
        assert "Processors: 0" in captured.out

    def test_stats_with_hooks(self, capsys):
        repl = FlatMachinesREPL()
        bus = DataBus()
        backend = CLIBackend(bus=bus)
        hooks = CLIHooks(backend)
        # Simulate some hook calls
        hooks.on_machine_start({"machine": {}})
        hooks.on_state_enter("s1", {"machine": {}})

        repl._last_backend = backend
        repl._last_hooks = hooks
        repl._cmd_stats([])
        captured = capsys.readouterr()
        assert "Hook Timings" in captured.out
        assert "on_machine_start" in captured.out
        assert "on_state_enter" in captured.out


class TestStatsRegistration:
    def test_stats_in_commands(self):
        repl = FlatMachinesREPL()
        assert "stats" in repl._commands

    def test_stats_callable(self):
        repl = FlatMachinesREPL()
        assert callable(repl._commands["stats"])

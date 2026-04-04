"""Tests for REPL input parsing and machine resolution."""

import json
import pytest
from unittest.mock import patch, MagicMock

from flatmachines_cli.repl import FlatMachinesREPL
from flatmachines_cli.discovery import MachineInfo


class TestGetInput:
    def _make_info(self):
        return MachineInfo(name="test", path="/tmp/test.yml", state_count=2)

    def test_json_from_args(self):
        repl = FlatMachinesREPL()
        info = self._make_info()
        result = repl._get_input(info, ['{"task": "hello"}'])
        assert result == {"task": "hello"}

    def test_invalid_json_returns_none(self, capsys):
        repl = FlatMachinesREPL()
        info = self._make_info()
        result = repl._get_input(info, ['not json'])
        assert result is None
        captured = capsys.readouterr()
        assert "Invalid JSON" in captured.out

    def test_non_object_json_returns_none(self, capsys):
        repl = FlatMachinesREPL()
        info = self._make_info()
        result = repl._get_input(info, ['[1, 2, 3]'])
        assert result is None
        captured = capsys.readouterr()
        assert "JSON object" in captured.out

    def test_empty_args_no_context_returns_empty(self):
        repl = FlatMachinesREPL()
        info = self._make_info()
        # Mock inspector to return empty context
        with patch("flatmachines_cli.inspector.load_config", return_value={"data": {}}):
            with patch("flatmachines_cli.inspector._classify_context", return_value=([], [])):
                result = repl._get_input(info, [])
                assert result == {}

    def test_multi_word_json(self):
        repl = FlatMachinesREPL()
        info = self._make_info()
        result = repl._get_input(info, ['{"task":', '"hello world"}'])
        assert result == {"task": "hello world"}


class TestResolve:
    def test_resolve_found(self):
        repl = FlatMachinesREPL()
        mock_info = MachineInfo(name="flow", path="/tmp/flow.yml", state_count=3)
        repl._index.resolve = MagicMock(return_value=mock_info)
        result = repl._resolve("flow")
        assert result == mock_info

    def test_resolve_not_found(self, capsys):
        repl = FlatMachinesREPL()
        repl._index.resolve = MagicMock(return_value=None)
        repl._index.prefix_matches = MagicMock(return_value=[])
        result = repl._resolve("nonexistent")
        assert result is None
        captured = capsys.readouterr()
        assert "Not found" in captured.out

    def test_resolve_ambiguous(self, capsys):
        repl = FlatMachinesREPL()
        m1 = MachineInfo(name="flow_a", path="/tmp/a.yml", state_count=1)
        m2 = MachineInfo(name="flow_b", path="/tmp/b.yml", state_count=1)
        repl._index.resolve = MagicMock(return_value=None)
        repl._index.prefix_matches = MagicMock(return_value=[m1, m2])
        result = repl._resolve("flow")
        assert result is None
        captured = capsys.readouterr()
        assert "Ambiguous" in captured.out


class TestCmdHistory:
    def test_empty_history(self, capsys):
        repl = FlatMachinesREPL()
        repl._cmd_history([])
        captured = capsys.readouterr()
        assert "No executions" in captured.out

    def test_history_with_entries(self, capsys):
        from flatmachines_cli.repl import ExecutionRecord
        repl = FlatMachinesREPL()
        repl._history = [
            ExecutionRecord(
                name="flow",
                path="/tmp/flow.yml",
                input={"task": "test"},
                duration_s=2.5,
                success=True,
            ),
        ]
        repl._cmd_history([])
        captured = capsys.readouterr()
        assert "flow" in captured.out
        assert "2.5s" in captured.out


class TestCmdBus:
    def test_no_bus_data(self, capsys):
        repl = FlatMachinesREPL()
        repl._cmd_bus([])
        captured = capsys.readouterr()
        assert "No bus data" in captured.out

    def test_bus_with_data(self, capsys):
        repl = FlatMachinesREPL()
        repl._last_bus_snapshot = {"status": {"state": "done"}}
        repl._cmd_bus([])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["status"]["state"] == "done"

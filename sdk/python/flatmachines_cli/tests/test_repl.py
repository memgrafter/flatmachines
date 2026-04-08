"""Tests for FlatMachinesREPL."""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from flatmachines_cli.repl import FlatMachinesREPL, ExecutionRecord


class TestExecutionRecord:
    def test_defaults(self):
        r = ExecutionRecord(name="test", path="/tmp/test.yml", input={})
        assert r.duration_s == 0.0
        assert r.success is False
        assert r.output is None
        assert r.error is None

    def test_success_record(self):
        r = ExecutionRecord(
            name="test",
            path="/tmp/test.yml",
            input={"task": "do stuff"},
            duration_s=1.5,
            success=True,
            output={"result": "done"},
        )
        assert r.success is True
        assert r.duration_s == 1.5

    def test_error_record(self):
        r = ExecutionRecord(
            name="test",
            path="/tmp/test.yml",
            input={},
            error="Something failed",
        )
        assert r.success is False
        assert r.error == "Something failed"


class TestFlatMachinesREPLInit:
    def test_default_init(self, tmp_path):
        repl = FlatMachinesREPL(project_root=str(tmp_path))
        assert repl._history == []
        assert repl._last_bus_snapshot is None

    def test_commands_registered(self, tmp_path):
        repl = FlatMachinesREPL(project_root=str(tmp_path))
        assert "list" in repl._commands
        assert "ls" in repl._commands
        assert "inspect" in repl._commands
        assert "info" in repl._commands
        assert "validate" in repl._commands
        assert "context" in repl._commands
        assert "run" in repl._commands
        assert "history" in repl._commands
        assert "bus" in repl._commands
        assert "help" in repl._commands


class TestFlatMachinesREPLCommands:
    """Test REPL commands without running a full event loop."""

    def test_list_empty(self, tmp_path, capsys):
        repl = FlatMachinesREPL(project_root=str(tmp_path))
        repl._cmd_list([])
        out = capsys.readouterr().out
        assert "No machines found" in out

    def test_history_empty(self, tmp_path, capsys):
        repl = FlatMachinesREPL(project_root=str(tmp_path))
        repl._cmd_history([])
        out = capsys.readouterr().out
        assert "No executions yet" in out

    def test_bus_empty(self, tmp_path, capsys):
        repl = FlatMachinesREPL(project_root=str(tmp_path))
        repl._cmd_bus([])
        out = capsys.readouterr().out
        assert "No bus data" in out

    def test_help(self, tmp_path, capsys):
        repl = FlatMachinesREPL(project_root=str(tmp_path))
        repl._cmd_help([])
        out = capsys.readouterr().out
        assert "Commands" in out
        assert "list" in out
        assert "run" in out

    def test_inspect_no_args(self, tmp_path, capsys):
        repl = FlatMachinesREPL(project_root=str(tmp_path))
        repl._cmd_inspect([])
        out = capsys.readouterr().out
        assert "Usage" in out

    def test_validate_no_args(self, tmp_path, capsys):
        repl = FlatMachinesREPL(project_root=str(tmp_path))
        repl._cmd_validate([])
        out = capsys.readouterr().out
        assert "Usage" in out

    def test_context_no_args(self, tmp_path, capsys):
        repl = FlatMachinesREPL(project_root=str(tmp_path))
        repl._cmd_context([])
        out = capsys.readouterr().out
        assert "Usage" in out

    def test_resolve_nonexistent(self, tmp_path, capsys):
        repl = FlatMachinesREPL(project_root=str(tmp_path))
        result = repl._resolve("nonexistent_machine")
        assert result is None
        out = capsys.readouterr().out
        assert "Not found" in out

    @pytest.mark.asyncio
    async def test_improve_run_uses_await_not_asyncio_run(self, tmp_path, capsys):
        repl = FlatMachinesREPL(project_root=str(tmp_path), working_dir=str(tmp_path))
        (tmp_path / "program.md").write_text("# program\n")

        with patch("flatmachines_cli.main.run_once", new_callable=AsyncMock) as mock_run_once, \
             patch("flatmachines_cli.main._run_async", side_effect=AssertionError("_run_async should not be used in REPL improve")):
            mock_run_once.return_value = {"generations": 1, "archive_size": 2}
            await repl._cmd_improve([])

        mock_run_once.assert_awaited_once()
        out = capsys.readouterr().out
        assert "Self-Improvement" in out
        assert "Result:" in out


class TestFlatMachinesREPLInput:
    """Test input handling."""

    def test_get_input_json_args(self, tmp_path):
        repl = FlatMachinesREPL(project_root=str(tmp_path))
        from flatmachines_cli.discovery import MachineInfo
        info = MachineInfo(name="test", path="/tmp/test.yml")
        result = repl._get_input(info, ['{"task": "hello"}'])
        assert result == {"task": "hello"}

    def test_get_input_invalid_json(self, tmp_path, capsys):
        repl = FlatMachinesREPL(project_root=str(tmp_path))
        from flatmachines_cli.discovery import MachineInfo
        info = MachineInfo(name="test", path="/tmp/test.yml")
        result = repl._get_input(info, ["not json"])
        assert result is None
        out = capsys.readouterr().out
        assert "Invalid JSON" in out

    def test_get_input_non_object_json(self, tmp_path, capsys):
        repl = FlatMachinesREPL(project_root=str(tmp_path))
        from flatmachines_cli.discovery import MachineInfo
        info = MachineInfo(name="test", path="/tmp/test.yml")
        result = repl._get_input(info, ['"just a string"'])
        assert result is None
        out = capsys.readouterr().out
        assert "must be a JSON object" in out


class TestFlatMachinesREPLMachineDiscovery:
    """Test REPL with actual machine configs."""

    MACHINE_YAML = """\
spec: flatmachine
spec_version: "2.5.0"
metadata:
  description: "Test machine"
data:
  name: repl_test
  states:
    start:
      type: initial
      transitions:
        - to: end
    end:
      type: final
"""

    def test_list_with_machines(self, tmp_path, capsys):
        config_dir = tmp_path / "sdk" / "examples" / "test_ex" / "config"
        config_dir.mkdir(parents=True)
        (config_dir / "machine.yml").write_text(self.MACHINE_YAML)

        repl = FlatMachinesREPL(project_root=str(tmp_path))
        repl._cmd_list([])
        out = capsys.readouterr().out
        assert "repl_test" in out

    def test_inspect_machine(self, tmp_path, capsys):
        config_dir = tmp_path / "sdk" / "examples" / "test_ex" / "config"
        config_dir.mkdir(parents=True)
        (config_dir / "machine.yml").write_text(self.MACHINE_YAML)

        repl = FlatMachinesREPL(project_root=str(tmp_path))
        repl._cmd_inspect(["repl_test"])
        out = capsys.readouterr().out
        assert "repl_test" in out
        assert "States" in out

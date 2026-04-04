"""Tests for REPL save command."""

import json
import pytest

from flatmachines_cli.repl import FlatMachinesREPL


class TestSaveCommand:
    def test_save_no_data(self, capsys):
        repl = FlatMachinesREPL()
        repl._cmd_save([])
        captured = capsys.readouterr()
        assert "No bus data" in captured.out

    def test_save_default_path(self, tmp_path, capsys, monkeypatch):
        monkeypatch.chdir(tmp_path)
        repl = FlatMachinesREPL()
        repl._last_bus_snapshot = {"status": {"state": "done"}}
        repl._cmd_save([])
        captured = capsys.readouterr()
        assert "Saved" in captured.out
        assert (tmp_path / "bus_snapshot.json").exists()
        data = json.loads((tmp_path / "bus_snapshot.json").read_text())
        assert data["status"]["state"] == "done"

    def test_save_custom_path(self, tmp_path, capsys):
        path = str(tmp_path / "custom.json")
        repl = FlatMachinesREPL()
        repl._last_bus_snapshot = {"tokens": {"count": 42}}
        repl._cmd_save([path])
        captured = capsys.readouterr()
        assert "Saved" in captured.out
        data = json.loads((tmp_path / "custom.json").read_text())
        assert data["tokens"]["count"] == 42

    def test_save_invalid_path(self, capsys):
        repl = FlatMachinesREPL()
        repl._last_bus_snapshot = {"x": 1}
        repl._cmd_save(["/nonexistent/dir/file.json"])
        captured = capsys.readouterr()
        assert "Error" in captured.out

    def test_save_in_commands(self):
        repl = FlatMachinesREPL()
        assert "save" in repl._commands

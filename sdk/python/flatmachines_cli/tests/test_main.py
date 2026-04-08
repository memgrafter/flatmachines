"""Tests for main.py entry point."""

import subprocess
import sys
import pytest
from pathlib import Path


CLI_DIR = Path(__file__).parent.parent
PYTHON = str(CLI_DIR / ".venv" / "bin" / "python")


class TestCLIVersion:
    def test_version_flag(self):
        result = subprocess.run(
            [PYTHON, "-m", "flatmachines_cli.main", "--version"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "2.5.0" in result.stdout

    def test_version_flag_short(self):
        result = subprocess.run(
            [PYTHON, "-m", "flatmachines_cli.main", "-V"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "2.5.0" in result.stdout


class TestCLIConfigValidation:
    def test_nonexistent_config_fails(self):
        result = subprocess.run(
            [PYTHON, "-m", "flatmachines_cli.main", "run", "/nonexistent/file.yml", "-p", "test"],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
        assert "not found" in result.stderr.lower() or "error" in result.stderr.lower()


class TestResolveConfig:
    def test_absolute_path(self):
        from flatmachines_cli.main import _resolve_config
        result = _resolve_config("/absolute/path.yml")
        assert result == "/absolute/path.yml"

    def test_relative_path(self):
        from flatmachines_cli.main import _resolve_config
        result = _resolve_config("relative/path.yml")
        assert result.endswith("relative/path.yml")
        assert Path(result).is_absolute()


class TestTryFindToolProvider:
    def test_returns_none_or_callable(self):
        from flatmachines_cli.main import _try_find_tool_provider
        result = _try_find_tool_provider("/tmp")
        assert result is None or callable(result)


class TestRunAsync:
    def test_run_async_exists(self):
        from flatmachines_cli.main import _run_async
        assert callable(_run_async)

    def test_run_async_runs_coroutine(self):
        from flatmachines_cli.main import _run_async
        result = []

        async def simple():
            result.append(True)

        _run_async(simple())
        assert result == [True]

    def test_run_async_keyboard_interrupt(self):
        """KeyboardInterrupt should exit with code 130."""
        from flatmachines_cli.main import _run_async

        async def interrupted():
            raise KeyboardInterrupt()

        with pytest.raises(SystemExit) as exc_info:
            _run_async(interrupted())
        assert exc_info.value.code == 130


class TestSelfImproveHandlerIsolation:
    def test_unlimited_generations_enable_isolation(self, monkeypatch):
        captured = {}

        class DummyImprover:
            def __init__(self, **kwargs):
                captured.update(kwargs)

        class DummyHooks:
            def __init__(self, improver):
                self.improver = improver

            def on_action(self, action_name, context):
                return context

        monkeypatch.setattr("flatmachines_cli.improve.SelfImprover", DummyImprover)
        monkeypatch.setattr("flatmachines_cli.improve.ConvergedSelfImproveHooks", DummyHooks)

        from flatmachines_cli.main import _make_self_improve_handler

        handler = _make_self_improve_handler()
        handler("prepare_parent_selection_context", {
            "max_generations": 0,
            "working_dir": "/tmp",
            "git_enabled": False,
        })

        assert captured["enable_isolation"] is True

    def test_single_generation_disables_isolation(self, monkeypatch):
        captured = {}

        class DummyImprover:
            def __init__(self, **kwargs):
                captured.update(kwargs)

        class DummyHooks:
            def __init__(self, improver):
                self.improver = improver

            def on_action(self, action_name, context):
                return context

        monkeypatch.setattr("flatmachines_cli.improve.SelfImprover", DummyImprover)
        monkeypatch.setattr("flatmachines_cli.improve.ConvergedSelfImproveHooks", DummyHooks)

        from flatmachines_cli.main import _make_self_improve_handler

        handler = _make_self_improve_handler()
        handler("prepare_parent_selection_context", {
            "max_generations": 1,
            "working_dir": "/tmp",
            "git_enabled": False,
        })

        assert captured["enable_isolation"] is False

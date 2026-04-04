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

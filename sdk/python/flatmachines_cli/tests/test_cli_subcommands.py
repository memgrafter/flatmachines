"""Tests for CLI subcommands: list, inspect, validate."""

import subprocess
import pytest
from pathlib import Path

CLI_DIR = Path(__file__).parent.parent
PYTHON = str(CLI_DIR / ".venv" / "bin" / "python")


MACHINE_YAML = """\
spec: flatmachine
spec_version: "2.5.0"
metadata:
  description: "Test machine for CLI"
data:
  name: cli_test
  context:
    task: "{{ input.task }}"
  states:
    start:
      type: initial
      transitions:
        - to: end
    end:
      type: final
      output:
        result: "{{ context.task }}"
"""


class TestListCommand:
    def test_list_succeeds(self):
        """list command should succeed (may find machines from project root)."""
        result = subprocess.run(
            [PYTHON, "-m", "flatmachines_cli.main", "list"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        # Should either find machines or say "No machines found"
        assert "states" in result.stdout or "No machines found" in result.stdout

    def test_list_output_format(self):
        """list output should have machine names and state counts."""
        result = subprocess.run(
            [PYTHON, "-m", "flatmachines_cli.main", "list"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        if "No machines found" not in result.stdout:
            # Each line should have "name (N states)" format
            lines = [l.strip() for l in result.stdout.strip().split("\n") if l.strip()]
            assert len(lines) > 0
            assert "states" in lines[0]


class TestInspectCommand:
    def test_inspect_by_path(self, tmp_path):
        f = tmp_path / "machine.yml"
        f.write_text(MACHINE_YAML)

        result = subprocess.run(
            [PYTHON, "-m", "flatmachines_cli.main", "inspect", str(f)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "cli_test" in result.stdout
        assert "States" in result.stdout

    def test_inspect_nonexistent(self, tmp_path):
        result = subprocess.run(
            [PYTHON, "-m", "flatmachines_cli.main", "inspect", "/nonexistent/file.yml"],
            capture_output=True, text=True,
        )
        assert result.returncode != 0


class TestValidateCommand:
    def test_validate_by_path(self, tmp_path):
        f = tmp_path / "machine.yml"
        f.write_text(MACHINE_YAML)

        result = subprocess.run(
            [PYTHON, "-m", "flatmachines_cli.main", "validate", str(f)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0

    def test_validate_nonexistent(self, tmp_path):
        result = subprocess.run(
            [PYTHON, "-m", "flatmachines_cli.main", "validate", "/nonexistent/file.yml"],
            capture_output=True, text=True,
        )
        assert result.returncode != 0


class TestContextCommand:
    def test_context_by_path(self, tmp_path):
        f = tmp_path / "machine.yml"
        f.write_text(MACHINE_YAML)

        result = subprocess.run(
            [PYTHON, "-m", "flatmachines_cli.main", "context", str(f)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "Context" in result.stdout
        assert "task" in result.stdout

    def test_context_nonexistent(self, tmp_path):
        result = subprocess.run(
            [PYTHON, "-m", "flatmachines_cli.main", "context", "/nonexistent/file.yml"],
            capture_output=True, text=True,
        )
        assert result.returncode != 0


class TestDryRun:
    def test_dry_run_flag(self, tmp_path):
        f = tmp_path / "machine.yml"
        f.write_text(MACHINE_YAML)
        result = subprocess.run(
            [PYTHON, "-m", "flatmachines_cli.main", "run", str(f), "--dry-run"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "Dry Run" in result.stdout
        assert "Validation" in result.stdout
        assert "Structure" in result.stdout
        assert "Context" in result.stdout

    def test_dry_run_nonexistent(self):
        result = subprocess.run(
            [PYTHON, "-m", "flatmachines_cli.main", "run", "/nonexistent.yml", "--dry-run"],
            capture_output=True, text=True,
        )
        assert result.returncode != 0


class TestLogLevel:
    def test_log_level_flag_accepted(self, tmp_path):
        f = tmp_path / "machine.yml"
        f.write_text(MACHINE_YAML)
        result = subprocess.run(
            [PYTHON, "-m", "flatmachines_cli.main", "--log-level", "DEBUG", "inspect", str(f)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0

    def test_invalid_log_level_rejected(self):
        result = subprocess.run(
            [PYTHON, "-m", "flatmachines_cli.main", "--log-level", "INVALID", "--version"],
            capture_output=True, text=True,
        )
        assert result.returncode != 0


class TestHelpOutput:
    def test_help_shows_subcommands(self):
        result = subprocess.run(
            [PYTHON, "-m", "flatmachines_cli.main", "--help"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "list" in result.stdout
        assert "inspect" in result.stdout
        assert "validate" in result.stdout
        assert "context" in result.stdout
        assert "run" in result.stdout

    def test_run_help(self):
        result = subprocess.run(
            [PYTHON, "-m", "flatmachines_cli.main", "run", "--help"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "config" in result.stdout

"""Tests for structured JSON logging."""

import json
import logging
import subprocess
import pytest

from flatmachines_cli.main import _JSONFormatter, _configure_json_logging

PYTHON = "sdk/python/flatmachines_cli/.venv/bin/python"


class TestJSONFormatter:
    def test_basic_format(self):
        fmt = _JSONFormatter()
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="hello world",
            args=(),
            exc_info=None,
        )
        output = fmt.format(record)
        data = json.loads(output)
        assert data["level"] == "INFO"
        assert data["logger"] == "test.logger"
        assert data["message"] == "hello world"
        assert "timestamp" in data
        assert data["timestamp"].endswith("Z")

    def test_format_with_args(self):
        fmt = _JSONFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.WARNING,
            pathname="test.py",
            lineno=1,
            msg="count is %d",
            args=(42,),
            exc_info=None,
        )
        output = fmt.format(record)
        data = json.loads(output)
        assert data["message"] == "count is 42"
        assert data["level"] == "WARNING"

    def test_format_with_exception(self):
        fmt = _JSONFormatter()
        try:
            raise ValueError("test error")
        except ValueError:
            import sys
            exc_info = sys.exc_info()

        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname="test.py",
            lineno=1,
            msg="failed",
            args=(),
            exc_info=exc_info,
        )
        output = fmt.format(record)
        data = json.loads(output)
        assert data["level"] == "ERROR"
        assert "exception" in data
        assert data["exception"]["type"] == "ValueError"
        assert data["exception"]["message"] == "test error"

    def test_valid_json_always(self):
        """Output should always be valid JSON, even with special characters."""
        fmt = _JSONFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.DEBUG,
            pathname="test.py",
            lineno=1,
            msg='path: "/tmp/file with spaces & \"quotes\"\\n"',
            args=(),
            exc_info=None,
        )
        output = fmt.format(record)
        data = json.loads(output)  # Should not raise
        assert isinstance(data["message"], str)


class TestConfigureJsonLogging:
    def test_configures_root_logger(self):
        # Save existing handlers
        root = logging.getLogger()
        old_handlers = root.handlers[:]
        old_level = root.level

        try:
            _configure_json_logging("DEBUG")
            assert root.level == logging.DEBUG
            assert len(root.handlers) == 1
            assert isinstance(root.handlers[0].formatter, _JSONFormatter)
        finally:
            root.handlers = old_handlers
            root.level = old_level

    def test_default_level_is_info(self):
        root = logging.getLogger()
        old_handlers = root.handlers[:]
        old_level = root.level

        try:
            _configure_json_logging(None)
            assert root.level == logging.INFO
        finally:
            root.handlers = old_handlers
            root.level = old_level


class TestCLIJsonLogFormat:
    def test_json_format_flag_accepted(self, tmp_path):
        f = tmp_path / "m.yml"
        f.write_text("spec: flatmachine\nspec_version: '2.5.0'\ndata:\n  states: {}\n")
        result = subprocess.run(
            [PYTHON, "-m", "flatmachines_cli.main", "--log-format", "json", "inspect", str(f)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0

    def test_invalid_format_rejected(self):
        result = subprocess.run(
            [PYTHON, "-m", "flatmachines_cli.main", "--log-format", "xml", "--version"],
            capture_output=True, text=True,
        )
        assert result.returncode != 0

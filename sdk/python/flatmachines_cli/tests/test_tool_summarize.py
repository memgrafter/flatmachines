"""Tests for ToolProcessor._summarize_tool static method."""

import pytest
from flatmachines_cli.processors import ToolProcessor


class TestSummarizeTool:
    def test_bash_with_command(self):
        s = ToolProcessor._summarize_tool("bash", {"command": "ls -la /tmp"})
        assert s == "bash: ls -la /tmp"

    def test_bash_truncated(self):
        long_cmd = "x" * 200
        s = ToolProcessor._summarize_tool("bash", {"command": long_cmd})
        assert len(s) < 200  # Should be shorter than original
        assert s.startswith("bash: ")

    def test_read_with_path(self):
        s = ToolProcessor._summarize_tool("read", {"path": "/home/user/file.py"})
        assert s == "read: /home/user/file.py"

    def test_write_with_path(self):
        s = ToolProcessor._summarize_tool("write", {"path": "/tmp/output.txt"})
        assert "write:" in s
        assert "/tmp/output.txt" in s

    def test_edit_with_path(self):
        s = ToolProcessor._summarize_tool("edit", {"path": "/src/main.py"})
        assert s == "edit: /src/main.py"

    def test_unknown_tool(self):
        s = ToolProcessor._summarize_tool("custom_tool", {"arg": "val"})
        assert s == "custom_tool"

    def test_bash_no_command(self):
        s = ToolProcessor._summarize_tool("bash", {})
        assert s == "bash"

    def test_read_no_path(self):
        s = ToolProcessor._summarize_tool("read", {})
        assert "read:" in s

    def test_none_args(self):
        s = ToolProcessor._summarize_tool("bash", None)
        # Should handle None gracefully
        assert isinstance(s, str)

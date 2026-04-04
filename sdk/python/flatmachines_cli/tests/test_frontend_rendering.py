"""Tests for TerminalFrontend rendering logic."""

import asyncio
import pytest

from flatmachines_cli.bus import DataBus
from flatmachines_cli.frontend import TerminalFrontend, _dim, _bold, _green, _red, _yellow


class TestANSIHelpers:
    def test_dim(self):
        assert "\033[2m" in _dim("test")
        assert "\033[0m" in _dim("test")
        assert "test" in _dim("test")

    def test_bold(self):
        assert "\033[1m" in _bold("test")

    def test_green(self):
        assert "\033[32m" in _green("test")

    def test_red(self):
        assert "\033[31m" in _red("test")

    def test_yellow(self):
        assert "\033[33m" in _yellow("test")

    def test_empty_string(self):
        assert _dim("") == "\033[2m\033[0m"


class TestRenderFrame:
    def test_render_no_bus(self):
        fe = TerminalFrontend()
        fe._bus = None
        fe._render_frame()  # Should not crash

    def test_render_empty_bus(self):
        fe = TerminalFrontend()
        fe._bus = DataBus()
        fe._render_frame()  # Should not crash

    def test_changed_no_previous(self):
        fe = TerminalFrontend()
        assert fe._changed("status", {"status": 1}) is True

    def test_changed_same_version(self):
        fe = TerminalFrontend()
        fe._last_versions = {"status": 1}
        assert fe._changed("status", {"status": 1}) is False

    def test_changed_newer_version(self):
        fe = TerminalFrontend()
        fe._last_versions = {"status": 1}
        assert fe._changed("status", {"status": 2}) is True

    def test_changed_missing_slot(self):
        fe = TerminalFrontend()
        assert fe._changed("nonexistent", {}) is False


class TestRenderContent:
    def test_content_displayed(self, capsys):
        fe = TerminalFrontend()
        bus = DataBus()
        bus.write("content", {"has_content": True, "text": "Agent thinking..."})
        fe._bus = bus
        fe._render_content({"content": 1})
        captured = capsys.readouterr()
        assert "Agent thinking" in captured.out

    def test_content_skips_unchanged(self, capsys):
        fe = TerminalFrontend()
        bus = DataBus()
        bus.write("content", {"has_content": True, "text": "same text"})
        fe._bus = bus
        fe._last_content_text = "same text"
        fe._render_content({"content": 1})
        captured = capsys.readouterr()
        assert "same text" not in captured.out

    def test_content_no_content(self, capsys):
        fe = TerminalFrontend()
        bus = DataBus()
        bus.write("content", {"has_content": False})
        fe._bus = bus
        fe._render_content({"content": 1})
        captured = capsys.readouterr()
        assert captured.out == ""


class TestRenderErrors:
    def test_error_displayed(self, capsys):
        fe = TerminalFrontend()
        bus = DataBus()
        bus.write("error", {"has_error": True, "error_message": "boom", "state": "bad"})
        fe._bus = bus
        fe._render_errors({"error": 1})
        captured = capsys.readouterr()
        assert "boom" in captured.out
        assert "bad" in captured.out

    def test_no_error(self, capsys):
        fe = TerminalFrontend()
        bus = DataBus()
        bus.write("error", {"has_error": False})
        fe._bus = bus
        fe._render_errors({"error": 1})
        captured = capsys.readouterr()
        assert captured.out == ""


class TestRenderStatus:
    def test_done_displayed(self, capsys):
        fe = TerminalFrontend()
        bus = DataBus()
        bus.write("status", {"phase": "done", "elapsed_s": 2.5})
        fe._bus = bus
        fe._render_status({"status": 1})
        captured = capsys.readouterr()
        assert "Done" in captured.out
        assert "2.5s" in captured.out

    def test_done_only_once(self, capsys):
        fe = TerminalFrontend()
        bus = DataBus()
        bus.write("status", {"phase": "done", "elapsed_s": 1.0})
        fe._bus = bus
        fe._render_status({"status": 1})
        captured1 = capsys.readouterr()
        assert "Done" in captured1.out

        # Second call should not print again
        bus.write("status", {"phase": "done", "elapsed_s": 1.0})
        fe._render_status({"status": 2})
        captured2 = capsys.readouterr()
        assert "Done" not in captured2.out


class TestRenderTokens:
    def test_tokens_displayed(self, capsys):
        fe = TerminalFrontend()
        bus = DataBus()
        bus.write("tokens", {"input_tokens": 100, "output_tokens": 50, "total_cost": 0.005})
        fe._bus = bus
        fe._render_tokens({"tokens": 1})
        captured = capsys.readouterr()
        assert "100" in captured.out
        assert "50" in captured.out

    def test_zero_tokens_nothing(self, capsys):
        fe = TerminalFrontend()
        bus = DataBus()
        bus.write("tokens", {"input_tokens": 0, "output_tokens": 0, "total_cost": 0})
        fe._bus = bus
        fe._render_tokens({"tokens": 1})
        captured = capsys.readouterr()
        # No tokens → nothing displayed
        assert captured.out == ""

"""Tests for TerminalFrontend rendering logic and change detection."""

import asyncio
import pytest
from unittest.mock import patch
from flatmachines_cli.frontend import TerminalFrontend
from flatmachines_cli.bus import DataBus


class TestChangeDetection:
    """Test the _changed() method used for incremental rendering."""

    def test_detects_new_slot(self):
        f = TerminalFrontend()
        f._last_versions = {}
        assert f._changed("status", {"status": 1}) is True

    def test_detects_version_change(self):
        f = TerminalFrontend()
        f._last_versions = {"status": 1}
        assert f._changed("status", {"status": 2}) is True

    def test_no_change_same_version(self):
        f = TerminalFrontend()
        f._last_versions = {"status": 2}
        assert f._changed("status", {"status": 2}) is False

    def test_no_change_missing_slot(self):
        f = TerminalFrontend()
        f._last_versions = {}
        assert f._changed("nonexistent", {}) is False


class TestContentRendering:
    @pytest.mark.asyncio
    async def test_content_dedup(self, capsys):
        """Same content text should not be printed twice."""
        bus = DataBus()
        f = TerminalFrontend(fps=100)

        bus.write("content", {"text": "same text", "lines": ["same text"], "has_content": True})

        task = asyncio.ensure_future(f.start(bus))
        await asyncio.sleep(0.05)

        # Write same text with new version
        bus.write("content", {"text": "same text", "lines": ["same text"], "has_content": True})
        await asyncio.sleep(0.05)

        await f.stop()
        await asyncio.sleep(0.02)

        captured = capsys.readouterr()
        # "same text" should only appear once
        assert captured.out.count("same text") == 1

        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_content_empty_not_rendered(self, capsys):
        """Empty content should not produce output."""
        bus = DataBus()
        f = TerminalFrontend(fps=100)

        bus.write("content", {"text": "", "lines": [], "has_content": False})

        task = asyncio.ensure_future(f.start(bus))
        await asyncio.sleep(0.05)
        await f.stop()
        await asyncio.sleep(0.02)

        captured = capsys.readouterr()
        # Should be minimal output
        assert "content" not in captured.out.lower()

        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


class TestToolRendering:
    @pytest.mark.asyncio
    async def test_tool_history_incremental(self, capsys):
        """Tool history should only render new entries."""
        bus = DataBus()
        f = TerminalFrontend(fps=100)

        # First tool
        bus.write("tools", {
            "active": [],
            "last_result": None,
            "history": [{"name": "bash", "is_error": False, "summary": "bash: ls"}],
            "total_calls": 1,
            "error_count": 0,
            "files_modified": [],
        })

        task = asyncio.ensure_future(f.start(bus))
        await asyncio.sleep(0.05)

        # Second tool (append to history)
        bus.write("tools", {
            "active": [],
            "last_result": None,
            "history": [
                {"name": "bash", "is_error": False, "summary": "bash: ls"},
                {"name": "read", "is_error": False, "summary": "read: /tmp/f"},
            ],
            "total_calls": 2,
            "error_count": 0,
            "files_modified": [],
        })

        await asyncio.sleep(0.05)
        await f.stop()
        await asyncio.sleep(0.02)

        captured = capsys.readouterr()
        # Both tool entries should appear
        assert "bash: ls" in captured.out
        assert "read: /tmp/f" in captured.out

        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_tool_error_rendering(self, capsys):
        """Error tools should show red x marker."""
        bus = DataBus()
        f = TerminalFrontend(fps=100)

        bus.write("tools", {
            "active": [],
            "last_result": None,
            "history": [
                {"name": "bash", "is_error": True, "summary": "bash: invalid_cmd"},
            ],
            "total_calls": 1,
            "error_count": 1,
            "files_modified": [],
        })

        task = asyncio.ensure_future(f.start(bus))
        await asyncio.sleep(0.05)
        await f.stop()
        await asyncio.sleep(0.02)

        captured = capsys.readouterr()
        assert "invalid_cmd" in captured.out

        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


class TestTokenRendering:
    @pytest.mark.asyncio
    async def test_token_stats_rendered(self, capsys):
        """Token usage should be rendered when available."""
        bus = DataBus()
        f = TerminalFrontend(fps=100)

        bus.write("tokens", {
            "input_tokens": 500,
            "output_tokens": 200,
            "total_tokens": 700,
            "total_cost": 0.015,
            "turns": 3,
            "tool_calls_count": 5,
        })

        task = asyncio.ensure_future(f.start(bus))
        await asyncio.sleep(0.05)
        await f.stop()
        await asyncio.sleep(0.02)

        captured = capsys.readouterr()
        assert "500" in captured.out
        assert "200" in captured.out
        assert "0.015" in captured.out

        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


class TestStatusRendering:
    @pytest.mark.asyncio
    async def test_done_printed_once(self, capsys):
        """'Done' message should only appear once."""
        bus = DataBus()
        f = TerminalFrontend(fps=100)

        bus.write("status", {
            "machine_name": "test",
            "phase": "done",
            "elapsed_s": 2.5,
        })

        task = asyncio.ensure_future(f.start(bus))
        await asyncio.sleep(0.05)

        # Write again with same phase
        bus.write("status", {
            "machine_name": "test",
            "phase": "done",
            "elapsed_s": 2.6,
        })
        await asyncio.sleep(0.05)

        await f.stop()
        await asyncio.sleep(0.02)

        captured = capsys.readouterr()
        assert captured.out.count("Done") == 1

        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


class TestVersionsChangeDetection:
    """Test the bus.versions() pattern used by frontends."""

    def test_detect_changes_between_snapshots(self):
        bus = DataBus()
        v1 = bus.versions()
        bus.write("a", 1)
        v2 = bus.versions()

        # Detect which slots changed
        changed = {k for k in v2 if v2[k] != v1.get(k, 0)}
        assert changed == {"a"}

    def test_no_false_positives(self):
        bus = DataBus()
        bus.write("a", 1)
        v1 = bus.versions()
        v2 = bus.versions()
        changed = {k for k in v2 if v2[k] != v1.get(k, 0)}
        assert changed == set()

    def test_multiple_changes(self):
        bus = DataBus()
        bus.write("a", 1)
        bus.write("b", 1)
        v1 = bus.versions()
        bus.write("a", 2)
        bus.write("c", 1)
        v2 = bus.versions()
        changed = {k for k in v2 if v2[k] != v1.get(k, 0)}
        assert changed == {"a", "c"}

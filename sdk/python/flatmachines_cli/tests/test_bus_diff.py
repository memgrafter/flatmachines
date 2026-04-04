"""Tests for DataBus.diff() change detection."""

import pytest

from flatmachines_cli.bus import DataBus


class TestBusDiff:
    def test_empty_vs_empty(self):
        bus = DataBus()
        diff = bus.diff({})
        assert diff == {}

    def test_added_slots(self):
        bus = DataBus()
        bus.write("a", 1)
        bus.write("b", 2)
        diff = bus.diff({})
        assert diff == {"a": "added", "b": "added"}

    def test_removed_slots(self):
        bus = DataBus()
        old = {"a": 1, "b": 2}
        diff = bus.diff(old)
        assert diff == {"a": "removed", "b": "removed"}

    def test_changed_slots(self):
        bus = DataBus()
        bus.write("x", "new_value")
        old = {"x": "old_value"}
        diff = bus.diff(old)
        assert diff == {"x": "changed"}

    def test_unchanged_slots(self):
        bus = DataBus()
        bus.write("x", 42)
        old = {"x": 42}
        diff = bus.diff(old)
        assert diff == {"x": "unchanged"}

    def test_mixed_changes(self):
        bus = DataBus()
        bus.write("kept", 1)
        bus.write("changed", "new")
        bus.write("added", True)
        old = {"kept": 1, "changed": "old", "removed": 99}
        diff = bus.diff(old)
        assert diff["kept"] == "unchanged"
        assert diff["changed"] == "changed"
        assert diff["added"] == "added"
        assert diff["removed"] == "removed"

    def test_diff_with_complex_values(self):
        bus = DataBus()
        bus.write("data", {"nested": [1, 2, 3]})
        old = {"data": {"nested": [1, 2, 3]}}
        diff = bus.diff(old)
        assert diff["data"] == "unchanged"

    def test_diff_with_complex_changed(self):
        bus = DataBus()
        bus.write("data", {"nested": [1, 2, 4]})  # Changed from [1,2,3]
        old = {"data": {"nested": [1, 2, 3]}}
        diff = bus.diff(old)
        assert diff["data"] == "changed"

    def test_keys_are_sorted(self):
        bus = DataBus()
        bus.write("z", 1)
        bus.write("a", 2)
        bus.write("m", 3)
        diff = bus.diff({})
        assert list(diff.keys()) == ["a", "m", "z"]

    def test_diff_against_own_snapshot(self):
        """Diffing against own snapshot should show all unchanged."""
        bus = DataBus()
        bus.write("a", 1)
        bus.write("b", 2)
        snap = bus.snapshot()
        diff = bus.diff(snap)
        assert all(v == "unchanged" for v in diff.values())

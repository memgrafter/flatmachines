"""Tests for DataBus and Slot."""

import asyncio
import time
import pytest
from flatmachines_cli.bus import DataBus, Slot, SlotValue


class TestSlot:
    def test_initial_state(self):
        s = Slot("test")
        assert s.name == "test"
        assert s.version == 0
        assert s.has_value is False

    def test_write_increments_version(self):
        s = Slot("s")
        v1 = s.write("hello")
        assert v1 == 1
        assert s.version == 1
        v2 = s.write("world")
        assert v2 == 2
        assert s.version == 2

    def test_read_returns_none_before_write(self):
        s = Slot()
        assert s.read() is None
        assert s.read_data() is None

    def test_read_returns_latest_value(self):
        s = Slot()
        s.write("first")
        s.write("second")
        val = s.read()
        assert isinstance(val, SlotValue)
        assert val.data == "second"
        assert val.version == 2

    def test_read_data_shortcut(self):
        s = Slot()
        s.write(42)
        assert s.read_data() == 42

    def test_read_if_changed_no_change(self):
        s = Slot()
        s.write("x")
        assert s.read_if_changed(1) is None

    def test_read_if_changed_with_change(self):
        s = Slot()
        s.write("x")
        s.write("y")
        val = s.read_if_changed(1)
        assert val is not None
        assert val.data == "y"

    def test_read_if_changed_since_zero(self):
        s = Slot()
        s.write("x")
        val = s.read_if_changed(0)
        assert val is not None
        assert val.data == "x"

    def test_slot_value_timestamp(self):
        s = Slot()
        before = time.monotonic()
        s.write("data")
        after = time.monotonic()
        val = s.read()
        assert before <= val.timestamp <= after

    def test_has_value_after_write(self):
        s = Slot()
        assert s.has_value is False
        s.write(None)
        assert s.has_value is True

    def test_write_none_is_valid(self):
        s = Slot()
        s.write(None)
        assert s.has_value is True
        assert s.version == 1
        assert s.read_data() is None

    def test_write_complex_types(self):
        s = Slot()
        data = {"key": [1, 2, 3], "nested": {"a": True}}
        s.write(data)
        assert s.read_data() == data

    @pytest.mark.asyncio
    async def test_wait_returns_on_write(self):
        s = Slot()
        async def writer():
            await asyncio.sleep(0.01)
            s.write("data")
        asyncio.ensure_future(writer())
        val = await s.wait(timeout=1.0)
        assert val.data == "data"

    @pytest.mark.asyncio
    async def test_wait_timeout_raises(self):
        s = Slot()
        with pytest.raises(asyncio.TimeoutError):
            await s.wait(timeout=0.01)

    @pytest.mark.asyncio
    async def test_wait_timeout_returns_existing_value(self):
        s = Slot()
        s.write("existing")
        val = await s.wait(timeout=0.01)
        assert val.data == "existing"


class TestDataBus:
    def test_empty_bus(self):
        bus = DataBus()
        assert bus.snapshot() == {}
        assert bus.versions() == {}
        assert bus.slot_names() == []

    def test_write_creates_slot(self):
        bus = DataBus()
        v = bus.write("status", {"phase": "running"})
        assert v == 1
        assert "status" in bus.slot_names()

    def test_read_nonexistent_slot(self):
        bus = DataBus()
        assert bus.read("nonexistent") is None
        assert bus.read_data("nonexistent") is None

    def test_read_data(self):
        bus = DataBus()
        bus.write("s", 42)
        assert bus.read_data("s") == 42

    def test_snapshot(self):
        bus = DataBus()
        bus.write("a", 1)
        bus.write("b", 2)
        snap = bus.snapshot()
        assert snap == {"a": 1, "b": 2}

    def test_snapshot_omits_empty_slots(self):
        bus = DataBus()
        bus.slot("empty")
        bus.write("full", "data")
        snap = bus.snapshot()
        assert "empty" not in snap
        assert snap == {"full": "data"}

    def test_snapshot_versioned(self):
        bus = DataBus()
        bus.write("a", 1)
        snap = bus.snapshot_versioned()
        assert "a" in snap
        assert isinstance(snap["a"], SlotValue)
        assert snap["a"].data == 1

    def test_versions(self):
        bus = DataBus()
        bus.write("a", 1)
        bus.write("a", 2)
        bus.write("b", 1)
        vers = bus.versions()
        assert vers["a"] == 2
        assert vers["b"] == 1

    def test_reset_clears_all(self):
        bus = DataBus()
        bus.write("a", 1)
        bus.write("b", 2)
        bus.reset()
        assert bus.snapshot() == {}
        assert bus.slot_names() == []

    def test_slot_returns_same_instance(self):
        bus = DataBus()
        s1 = bus.slot("x")
        s2 = bus.slot("x")
        assert s1 is s2

    def test_overwrite_latest_wins(self):
        bus = DataBus()
        bus.write("s", "old")
        bus.write("s", "new")
        assert bus.read_data("s") == "new"

    def test_many_slots(self):
        bus = DataBus()
        for i in range(100):
            bus.write(f"slot_{i}", i)
        snap = bus.snapshot()
        assert len(snap) == 100
        assert snap["slot_50"] == 50

    def test_snapshot_is_independent_copy(self):
        bus = DataBus()
        bus.write("a", 1)
        snap = bus.snapshot()
        bus.write("a", 999)
        assert snap["a"] == 1

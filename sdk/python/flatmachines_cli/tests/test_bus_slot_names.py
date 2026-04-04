"""Tests for DataBus slot_names and slot management."""

import pytest
from flatmachines_cli.bus import DataBus, Slot


class TestSlotNames:
    def test_empty_bus(self):
        bus = DataBus()
        assert bus.slot_names() == []

    def test_after_write(self):
        bus = DataBus()
        bus.write("a", 1)
        bus.write("b", 2)
        names = bus.slot_names()
        assert "a" in names
        assert "b" in names

    def test_after_slot_creation(self):
        bus = DataBus()
        bus.slot("x")
        assert "x" in bus.slot_names()

    def test_no_duplicates(self):
        bus = DataBus()
        bus.write("a", 1)
        bus.write("a", 2)
        assert bus.slot_names().count("a") == 1

    def test_after_reset(self):
        bus = DataBus()
        bus.write("a", 1)
        bus.reset()
        assert bus.slot_names() == []


class TestSlotProperties:
    def test_name_property(self):
        s = Slot(name="test")
        assert s.name == "test"

    def test_version_increments(self):
        s = Slot(name="test")
        assert s.version == 0
        s.write("a")
        assert s.version == 1
        s.write("b")
        assert s.version == 2

    def test_has_value(self):
        s = Slot(name="test")
        assert not s.has_value
        s.write("x")
        assert s.has_value

    def test_read_data_none_before_write(self):
        s = Slot(name="test")
        assert s.read_data() is None

    def test_read_none_before_write(self):
        s = Slot(name="test")
        assert s.read() is None

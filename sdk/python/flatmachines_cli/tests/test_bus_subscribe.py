"""Tests for DataBus subscribe/unsubscribe push notifications."""

import pytest

from flatmachines_cli.bus import DataBus


class TestSubscribe:
    def test_subscribe_all_writes(self):
        bus = DataBus()
        received = []
        bus.subscribe(lambda name, val: received.append((name, val)))

        bus.write("a", 1)
        bus.write("b", 2)
        assert received == [("a", 1), ("b", 2)]

    def test_subscribe_specific_slot(self):
        bus = DataBus()
        received = []
        bus.subscribe(lambda name, val: received.append(val), slot_name="x")

        bus.write("x", "yes")
        bus.write("y", "no")
        bus.write("x", "again")
        assert received == ["yes", "again"]

    def test_multiple_subscribers(self):
        bus = DataBus()
        r1, r2 = [], []
        bus.subscribe(lambda n, v: r1.append(v))
        bus.subscribe(lambda n, v: r2.append(v))

        bus.write("a", 42)
        assert r1 == [42]
        assert r2 == [42]

    def test_subscriber_exception_ignored(self):
        """Subscriber error should not affect write()."""
        bus = DataBus()
        received = []

        def bad_callback(name, val):
            raise RuntimeError("boom")

        def good_callback(name, val):
            received.append(val)

        bus.subscribe(bad_callback)
        bus.subscribe(good_callback)

        bus.write("a", 1)  # Should not raise
        assert received == [1]

    def test_subscribe_returns_none(self):
        bus = DataBus()
        result = bus.subscribe(lambda n, v: None)
        assert result is None


class TestUnsubscribe:
    def test_unsubscribe_stops_notifications(self):
        bus = DataBus()
        received = []
        cb = lambda n, v: received.append(v)
        bus.subscribe(cb)

        bus.write("a", 1)
        bus.unsubscribe(cb)
        bus.write("a", 2)
        assert received == [1]

    def test_unsubscribe_nonexistent(self):
        """Unsubscribing a non-registered callback should be safe."""
        bus = DataBus()
        bus.unsubscribe(lambda n, v: None)  # Should not raise

    def test_unsubscribe_only_first(self):
        """If same callback registered twice, unsubscribe removes only first."""
        bus = DataBus()
        received = []
        cb = lambda n, v: received.append(v)
        bus.subscribe(cb)
        bus.subscribe(cb)

        bus.write("a", 1)
        assert len(received) == 2

        bus.unsubscribe(cb)
        received.clear()
        bus.write("a", 2)
        assert len(received) == 1  # One remaining subscription


class TestResetClearsSubscribers:
    def test_reset_clears_subscribers(self):
        bus = DataBus()
        received = []
        bus.subscribe(lambda n, v: received.append(v))

        bus.write("a", 1)
        bus.reset()
        bus.write("a", 2)
        assert received == [1]  # Only the pre-reset write

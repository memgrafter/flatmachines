"""Tests for processor backpressure metrics (stats property)."""

import asyncio
import pytest

from flatmachines_cli.bus import DataBus
from flatmachines_cli.processors import StatusProcessor, Processor
from flatmachines_cli import events


class TestProcessorStats:
    def test_initial_stats(self):
        bus = DataBus()
        p = StatusProcessor(bus)
        stats = p.stats
        assert stats["events_processed"] == 0
        assert stats["events_dropped"] == 0
        assert stats["queue_hwm"] == 0
        assert stats["queue_capacity"] == 1024

    @pytest.mark.asyncio
    async def test_events_processed_increments(self):
        bus = DataBus()
        p = StatusProcessor(bus, max_hz=1000)
        p.start()

        p.enqueue(events.state_enter("s1", {"machine": {}}))
        p.enqueue(events.state_enter("s2", {"machine": {}}))
        await asyncio.sleep(0.1)

        p.stop()
        await asyncio.sleep(0.05)

        assert p.stats["events_processed"] >= 2

    @pytest.mark.asyncio
    async def test_queue_hwm_tracks_peak(self):
        """High-water mark should record the peak queue depth."""
        bus = DataBus()
        # Use very slow Hz so events pile up
        p = StatusProcessor(bus, max_hz=1)
        p.start()

        # Send a batch of events
        for i in range(10):
            p.enqueue(events.state_enter(f"s_{i}", {"machine": {}}))

        # Give the processor a moment to start consuming
        await asyncio.sleep(0.05)
        hwm = p.stats["queue_hwm"]
        assert hwm > 0  # Some events should have queued up

        p.stop()
        await asyncio.sleep(0.05)

    def test_drops_tracked(self):
        """When queue is full, drops should be counted."""
        bus = DataBus()

        # Custom processor with tiny queue so we can test drops
        class TinyProcessor(Processor):
            slot_name = "tiny"
            event_types = None
            def process(self, event):
                return {"ok": True}

        p = TinyProcessor(bus, queue_size=2)
        # Don't start the processor — nothing drains
        for i in range(5):
            p.enqueue({"type": "test", "n": i})

        assert p.stats["events_dropped"] >= 3  # At least 3 dropped

    def test_stats_keys(self):
        bus = DataBus()
        p = StatusProcessor(bus)
        keys = set(p.stats.keys())
        assert keys == {
            "events_processed",
            "events_dropped",
            "queue_hwm",
            "queue_size",
            "queue_capacity",
        }

    @pytest.mark.asyncio
    async def test_custom_processor_stats(self):
        """Stats work on custom processor subclasses too."""

        class Counter(Processor):
            slot_name = "counter"
            event_types = None
            def process(self, event):
                return {"count": self._events_processed}

        bus = DataBus()
        p = Counter(bus, max_hz=1000)
        p.start()
        for i in range(5):
            p.enqueue({"type": "test", "n": i})
        await asyncio.sleep(0.1)
        p.stop()
        await asyncio.sleep(0.05)

        assert p.stats["events_processed"] >= 5
        assert p.stats["events_dropped"] == 0

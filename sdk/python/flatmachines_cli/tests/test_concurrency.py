"""Tests for concurrent access patterns in the async pipeline."""

import asyncio
import pytest
from flatmachines_cli.bus import DataBus, Slot
from flatmachines_cli.backend import CLIBackend
from flatmachines_cli.processors import (
    StatusProcessor, TokenProcessor, ToolProcessor,
    ContentProcessor, ErrorProcessor, default_processors,
)
from flatmachines_cli import events


class TestConcurrentSlotAccess:
    """Test slot behavior under concurrent read/write patterns."""

    @pytest.mark.asyncio
    async def test_concurrent_writer_reader(self):
        """One writer, one reader — reader always gets latest."""
        bus = DataBus()
        results = []
        write_count = 100

        async def writer():
            for i in range(write_count):
                bus.write("counter", i)
                await asyncio.sleep(0)  # yield

        async def reader():
            for _ in range(50):
                val = bus.read_data("counter")
                if val is not None:
                    results.append(val)
                await asyncio.sleep(0)

        await asyncio.gather(writer(), reader())

        # Reader should get monotonically increasing values
        for i in range(1, len(results)):
            assert results[i] >= results[i - 1], \
                f"Non-monotonic: {results[i]} < {results[i-1]} at index {i}"

    @pytest.mark.asyncio
    async def test_multiple_concurrent_writers(self):
        """Multiple writers to different slots should not interfere."""
        bus = DataBus()

        async def writer(slot_name, count):
            for i in range(count):
                bus.write(slot_name, i)
                await asyncio.sleep(0)

        await asyncio.gather(
            writer("a", 100),
            writer("b", 100),
            writer("c", 100),
        )

        assert bus.read_data("a") == 99
        assert bus.read_data("b") == 99
        assert bus.read_data("c") == 99

    @pytest.mark.asyncio
    async def test_snapshot_during_writes(self):
        """Snapshot should be consistent (not crash) during active writes."""
        bus = DataBus()
        snapshots = []

        async def writer():
            for i in range(100):
                bus.write("counter", i)
                bus.write("label", f"step_{i}")
                await asyncio.sleep(0)

        async def snapshot_taker():
            for _ in range(50):
                snap = bus.snapshot()
                snapshots.append(snap)
                await asyncio.sleep(0)

        await asyncio.gather(writer(), snapshot_taker())

        # All snapshots should be valid dicts
        for snap in snapshots:
            assert isinstance(snap, dict)


class TestConcurrentProcessors:
    """Test multiple processors running concurrently."""

    @pytest.mark.asyncio
    async def test_all_processors_receive_events(self):
        """All matching processors should get every event."""
        bus = DataBus()
        procs = default_processors(bus)

        # Start all
        for p in procs:
            p.start()

        # Send a machine_start event (goes to status, tokens, tools, content, error)
        evt = events.machine_start({"machine": {"machine_name": "concurrent_test"}})
        for p in procs:
            if p.accepts(evt):
                p.enqueue(evt)

        await asyncio.sleep(0.2)

        # Stop all
        for p in procs:
            p.stop()
        await asyncio.sleep(0.1)

        # Status should have the machine name
        status = bus.read_data("status")
        assert status is not None
        assert status["machine_name"] == "concurrent_test"

    @pytest.mark.asyncio
    async def test_processors_independent(self):
        """A slow processor should not block faster ones."""
        from flatmachines_cli.processors import Processor

        class SlowProcessor(Processor):
            slot_name = "slow"
            event_types = None

            def __init__(self, bus):
                super().__init__(bus, max_hz=1000)
                self.processed = 0

            def process(self, event):
                import time
                time.sleep(0.01)  # Simulate slow processing
                self.processed += 1
                return {"count": self.processed}

        class FastProcessor(Processor):
            slot_name = "fast"
            event_types = None

            def __init__(self, bus):
                super().__init__(bus, max_hz=1000)
                self.processed = 0

            def process(self, event):
                self.processed += 1
                return {"count": self.processed}

        bus = DataBus()
        slow = SlowProcessor(bus)
        fast = FastProcessor(bus)

        slow.start()
        fast.start()

        # Send events
        for i in range(10):
            slow.enqueue({"type": "test"})
            fast.enqueue({"type": "test"})

        await asyncio.sleep(0.5)

        slow.stop()
        fast.stop()
        await asyncio.sleep(0.1)

        fast_data = bus.read_data("fast")
        slow_data = bus.read_data("slow")

        assert fast_data is not None
        assert slow_data is not None
        # Fast should have processed all quickly
        assert fast_data["count"] == 10


class TestBackendConcurrency:
    @pytest.mark.asyncio
    async def test_rapid_emit_burst(self):
        """Backend should handle rapid event bursts without dropping critical data."""
        bus = DataBus()
        procs = [StatusProcessor(bus, max_hz=1000)]
        backend = CLIBackend(bus=bus, processors=procs)
        await backend.start()

        # Rapid burst of state transitions
        backend.emit(events.machine_start({"machine": {"machine_name": "burst"}}))
        for i in range(50):
            backend.emit(events.state_enter(f"s_{i}", {"machine": {"step": i}}))
            backend.emit(events.transition(f"s_{i}", f"s_{i+1}", {}))

        await asyncio.sleep(0.3)
        await backend.stop()

        data = bus.read_data("status")
        assert data is not None
        assert data["machine_name"] == "burst"
        # Should have progressed through many states
        assert data["step"] >= 40  # at least most events processed


class TestSlotWaitConcurrency:
    @pytest.mark.asyncio
    async def test_wait_with_rapid_writes(self):
        """Multiple rapid writes should all wake waiters."""
        s = Slot("rapid")
        values = []

        async def waiter():
            for _ in range(3):
                val = await s.wait(timeout=1.0)
                values.append(val.data)

        async def writer():
            for i in range(3):
                await asyncio.sleep(0.02)
                s.write(i)

        await asyncio.gather(writer(), waiter())
        assert len(values) == 3

    @pytest.mark.asyncio
    async def test_wait_cancellation(self):
        """Cancelling a wait should not corrupt the slot."""
        s = Slot("cancel")

        async def waiter():
            await s.wait(timeout=10.0)

        task = asyncio.ensure_future(waiter())
        await asyncio.sleep(0.01)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # Slot should still work
        s.write("after_cancel")
        assert s.read_data() == "after_cancel"

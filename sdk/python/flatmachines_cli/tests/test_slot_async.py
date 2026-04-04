"""Async tests for Slot.wait() behavior."""

import asyncio
import pytest

from flatmachines_cli.bus import Slot, DataBus


class TestSlotWait:
    @pytest.mark.asyncio
    async def test_wait_returns_written_value(self):
        s = Slot(name="test")

        async def writer():
            await asyncio.sleep(0.01)
            s.write("hello")

        asyncio.ensure_future(writer())
        val = await s.wait(timeout=1.0)
        assert val.data == "hello"

    @pytest.mark.asyncio
    async def test_wait_timeout_no_value(self):
        s = Slot(name="test")
        with pytest.raises(asyncio.TimeoutError):
            await s.wait(timeout=0.01)

    @pytest.mark.asyncio
    async def test_wait_timeout_with_existing_value(self):
        s = Slot(name="test")
        s.write("existing")
        # Wait should return existing value on timeout since value exists
        val = await s.wait(timeout=0.01)
        assert val.data == "existing"

    @pytest.mark.asyncio
    async def test_multiple_waiters(self):
        s = Slot(name="test")
        results = []

        async def waiter(idx):
            val = await s.wait(timeout=1.0)
            results.append((idx, val.data))

        t1 = asyncio.ensure_future(waiter(1))
        t2 = asyncio.ensure_future(waiter(2))
        await asyncio.sleep(0.01)
        s.write("shared")
        await asyncio.sleep(0.05)
        # At least one waiter should get the value
        assert len(results) >= 1
        for idx, data in results:
            assert data == "shared"

    @pytest.mark.asyncio
    async def test_wait_after_write(self):
        s = Slot(name="test")
        s.write("first")
        # Event is set, so wait should return immediately
        val = await s.wait(timeout=0.1)
        assert val.data == "first"

    @pytest.mark.asyncio
    async def test_sequential_waits(self):
        s = Slot(name="test")

        async def write_later(val, delay):
            await asyncio.sleep(delay)
            s.write(val)

        asyncio.ensure_future(write_later("a", 0.01))
        val1 = await s.wait(timeout=1.0)
        assert val1.data == "a"

        asyncio.ensure_future(write_later("b", 0.01))
        val2 = await s.wait(timeout=1.0)
        assert val2.data == "b"


class TestDataBusAsync:
    @pytest.mark.asyncio
    async def test_slot_wait_via_bus(self):
        bus = DataBus()
        s = bus.slot("test")

        async def writer():
            await asyncio.sleep(0.01)
            bus.write("test", "via_bus")

        asyncio.ensure_future(writer())
        val = await s.wait(timeout=1.0)
        assert val.data == "via_bus"

    @pytest.mark.asyncio
    async def test_snapshot_versioned(self):
        bus = DataBus()
        bus.write("a", 1)
        bus.write("b", "two")
        snap = bus.snapshot_versioned()
        assert "a" in snap
        assert snap["a"].data == 1
        assert snap["a"].version == 1
        assert snap["b"].data == "two"

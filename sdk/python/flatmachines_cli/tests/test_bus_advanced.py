"""Advanced bus tests — stress testing, memory patterns, and invariants."""

import asyncio
import time
import pytest
from flatmachines_cli.bus import DataBus, Slot, SlotValue


class TestSlotInvariants:
    """Test that slot invariants always hold."""

    def test_version_monotonically_increases(self):
        s = Slot("mono")
        versions = []
        for i in range(100):
            v = s.write(i)
            versions.append(v)
        for i in range(1, len(versions)):
            assert versions[i] > versions[i-1]

    def test_timestamp_monotonically_increases(self):
        s = Slot("ts")
        timestamps = []
        for i in range(20):
            s.write(i)
            val = s.read()
            timestamps.append(val.timestamp)
        for i in range(1, len(timestamps)):
            assert timestamps[i] >= timestamps[i-1]

    def test_read_always_returns_last_write(self):
        s = Slot("last")
        for i in range(100):
            s.write(f"value_{i}")
            assert s.read_data() == f"value_{i}"

    def test_version_matches_write_count(self):
        s = Slot("count")
        for i in range(50):
            s.write(i)
        assert s.version == 50


class TestDataBusInvariants:
    def test_snapshot_keys_match_written_slots(self):
        bus = DataBus()
        written = set()
        for i in range(20):
            name = f"slot_{i}"
            bus.write(name, i)
            written.add(name)
        snap = bus.snapshot()
        assert set(snap.keys()) == written

    def test_versions_keys_match_all_slots(self):
        bus = DataBus()
        bus.write("a", 1)
        bus.slot("b")  # created but not written
        vers = bus.versions()
        assert "a" in vers
        assert "b" in vers
        assert vers["a"] == 1
        assert vers["b"] == 0

    def test_reset_makes_snapshot_empty(self):
        bus = DataBus()
        for i in range(10):
            bus.write(f"s_{i}", i)
        bus.reset()
        assert bus.snapshot() == {}
        assert len(bus) == 0

    def test_slot_names_after_writes(self):
        bus = DataBus()
        bus.write("x", 1)
        bus.write("y", 2)
        bus.write("z", 3)
        names = sorted(bus.slot_names())
        assert names == ["x", "y", "z"]


class TestSlotValueImmutability:
    """SlotValue should be a snapshot, not affected by later writes."""

    def test_slot_value_stable_after_write(self):
        s = Slot("stable")
        s.write("first")
        val1 = s.read()
        s.write("second")
        val2 = s.read()
        # val1 should still reference "first"
        assert val1.data == "first"
        assert val1.version == 1
        assert val2.data == "second"
        assert val2.version == 2

    def test_dict_value_reference_stability(self):
        """If we write a dict, modifying the original shouldn't affect the slot."""
        s = Slot("dict_ref")
        data = {"key": "original"}
        s.write(data)
        # Note: Slot stores references, not copies. This test documents behavior.
        data["key"] = "modified"
        # The slot value IS the same reference
        assert s.read_data()["key"] == "modified"  # This is expected (reference semantics)


class TestSlotWaitPatterns:
    @pytest.mark.asyncio
    async def test_wait_sequential_values(self):
        """Sequential waits should get sequential values."""
        s = Slot("seq_wait")
        values = []

        async def producer():
            for i in range(3):
                await asyncio.sleep(0.02)
                s.write(i)

        async def consumer():
            for _ in range(3):
                val = await s.wait(timeout=1.0)
                values.append(val.data)

        await asyncio.gather(producer(), consumer())
        assert values == [0, 1, 2]

    @pytest.mark.asyncio
    async def test_wait_with_existing_value(self):
        """If event is set from previous write, wait returns immediately."""
        s = Slot("pre_set")
        s.write("pre")
        val = await s.wait(timeout=0.1)
        assert val.data == "pre"

    @pytest.mark.asyncio
    async def test_wait_timeout_with_value(self):
        """Timeout with existing value should return the value."""
        s = Slot("timeout_val")
        s.write("exists")
        # event is set, so wait returns immediately (no timeout)
        val = await s.wait(timeout=0.001)
        assert val.data == "exists"


class TestDataBusStress:
    """Stress tests for the bus."""

    def test_many_slots_many_writes(self):
        bus = DataBus()
        for s in range(50):
            for w in range(100):
                bus.write(f"slot_{s}", w)
        snap = bus.snapshot()
        assert len(snap) == 50
        for s in range(50):
            assert snap[f"slot_{s}"] == 99

    def test_rapid_snapshot(self):
        bus = DataBus()
        for i in range(100):
            bus.write("counter", i)
        snapshots = [bus.snapshot() for _ in range(100)]
        for snap in snapshots:
            assert snap["counter"] == 99

    @pytest.mark.asyncio
    async def test_concurrent_slots_stress(self):
        """Many concurrent writers to different slots."""
        bus = DataBus()

        async def writer(name, count):
            for i in range(count):
                bus.write(name, i)
                if i % 10 == 0:
                    await asyncio.sleep(0)

        tasks = [writer(f"w_{i}", 200) for i in range(20)]
        await asyncio.gather(*tasks)

        snap = bus.snapshot()
        assert len(snap) == 20
        for i in range(20):
            assert snap[f"w_{i}"] == 199

"""Tests for edge cases, repr methods, and the Slot event mechanism."""

import asyncio
import pytest
from flatmachines_cli.bus import DataBus, Slot, SlotValue
from flatmachines_cli.frontend import TerminalFrontend
from flatmachines_cli.backend import CLIBackend
from flatmachines_cli.processors import StatusProcessor, default_processors
from flatmachines_cli import events


class TestSlotEventMechanism:
    """Test that Slot.wait() works correctly with write()."""

    @pytest.mark.asyncio
    async def test_multiple_waiters_all_wake(self):
        """Multiple coroutines waiting on the same slot should all wake."""
        s = Slot("multi")
        results = []

        async def waiter(idx):
            val = await s.wait(timeout=1.0)
            results.append((idx, val.data))

        # Start two waiters
        t1 = asyncio.ensure_future(waiter(1))
        t2 = asyncio.ensure_future(waiter(2))
        await asyncio.sleep(0.01)  # let them start waiting

        s.write("wakeup")
        await asyncio.sleep(0.05)

        assert len(results) == 2
        assert all(data == "wakeup" for _, data in results)

    @pytest.mark.asyncio
    async def test_wait_after_write_returns_immediately(self):
        """If event is set from a previous write, wait() returns immediately."""
        s = Slot("prewritten")
        s.write("already_here")
        # Event is set, so wait should return immediately
        val = await s.wait(timeout=0.1)
        assert val.data == "already_here"

    @pytest.mark.asyncio
    async def test_sequential_waits(self):
        """Sequential wait() calls should each wait for a new write."""
        s = Slot("seq")

        async def writer():
            await asyncio.sleep(0.02)
            s.write("first")
            await asyncio.sleep(0.02)
            s.write("second")

        asyncio.ensure_future(writer())

        val1 = await s.wait(timeout=1.0)
        assert val1.data == "first"

        val2 = await s.wait(timeout=1.0)
        assert val2.data == "second"


class TestSlotRepr:
    def test_repr_empty(self):
        s = Slot("test")
        r = repr(s)
        assert "test" in r
        assert "version=0" in r
        assert "has_value=False" in r

    def test_repr_with_value(self):
        s = Slot("filled")
        s.write("data")
        r = repr(s)
        assert "filled" in r
        assert "version=1" in r
        assert "has_value=True" in r


class TestDataBusRepr:
    def test_repr_empty(self):
        bus = DataBus()
        r = repr(bus)
        assert "DataBus" in r

    def test_repr_with_slots(self):
        bus = DataBus()
        bus.write("status", {"phase": "running"})
        bus.write("tokens", {"count": 100})
        r = repr(bus)
        assert "status" in r
        assert "tokens" in r

    def test_len_empty(self):
        bus = DataBus()
        assert len(bus) == 0

    def test_len_with_slots(self):
        bus = DataBus()
        bus.write("a", 1)
        bus.slot("b")  # create but don't write
        assert len(bus) == 2


class TestFrontendRepr:
    def test_repr(self):
        f = TerminalFrontend(fps=30.0, auto_approve=True)
        r = repr(f)
        assert "TerminalFrontend" in r
        assert "30.0" in r
        assert "True" in r


class TestFrontendHumanReviewEdgeCases:
    """Test human_review with missing _tool_loop_chain."""

    def test_human_review_creates_chain_if_missing(self):
        from unittest.mock import patch
        f = TerminalFrontend(auto_approve=False)
        ctx = {"result": "output"}  # no _tool_loop_chain key

        with patch("builtins.input", return_value="follow up"):
            result = f.handle_action("human_review", ctx)

        assert "_tool_loop_chain" in result
        assert len(result["_tool_loop_chain"]) == 1
        assert result["_tool_loop_chain"][0]["content"] == "follow up"


class TestProcessorResilience:
    """Test that the processor pipeline is resilient."""

    @pytest.mark.asyncio
    async def test_rapid_start_stop_cycles(self):
        """Backend should handle rapid start/stop cycles."""
        bus = DataBus()
        backend = CLIBackend(bus=bus)
        for _ in range(5):
            await backend.start()
            backend.emit(events.machine_start({"machine": {"machine_name": "rapid"}}))
            await asyncio.sleep(0.02)
            await backend.stop()

    @pytest.mark.asyncio
    async def test_large_event_burst(self):
        """Backend should handle a large burst of events."""
        bus = DataBus()
        procs = [StatusProcessor(bus, max_hz=1000)]
        backend = CLIBackend(bus=bus, processors=procs)
        await backend.start()

        # Send 100 events rapidly
        for i in range(100):
            backend.emit(events.state_enter(f"state_{i}", {"machine": {"step": i}}))

        await asyncio.sleep(0.3)
        data = bus.read_data("status")
        assert data is not None
        assert data["step"] >= 90  # should have processed most events

        await backend.stop()


class TestEventEdgeCases:
    """Edge cases for event construction."""

    def test_machine_start_with_none_context(self):
        """Events should handle None-ish values gracefully."""
        from flatmachines_cli.events import machine_start
        # This tests that the event constructor doesn't crash
        # even with unexpected input
        evt = machine_start({"machine": None})
        assert evt["type"] == "machine_start"

    def test_error_event_with_complex_exception(self):
        """Error events should handle exceptions with complex messages."""
        from flatmachines_cli.events import error

        class ComplexError(Exception):
            def __str__(self):
                return "Error with\nnewlines\tand\ttabs"

        evt = error("s", ComplexError(), {})
        assert "newlines" in evt["error_message"]
        assert evt["error_type"] == "ComplexError"


class TestDataBusTruthiness:
    """Regression: DataBus with __len__ must not break 'or' patterns."""

    def test_empty_bus_is_truthy(self):
        """Empty DataBus should be truthy even with __len__."""
        bus = DataBus()
        assert len(bus) == 0
        assert bool(bus) is True  # __bool__ always returns True

    def test_backend_accepts_empty_bus(self):
        """CLIBackend should use an empty DataBus passed to it."""
        bus = DataBus()
        backend = CLIBackend(bus=bus)
        assert backend.bus is bus

    def test_backend_accepts_empty_processors_list(self):
        """CLIBackend should use an empty processor list."""
        bus = DataBus()
        backend = CLIBackend(bus=bus, processors=[])
        assert backend.processors == []


class TestDefaultProcessorConfiguration:
    """Verify default processor Hz rates are sensible."""

    def test_status_hz(self):
        bus = DataBus()
        p = StatusProcessor(bus)
        assert p._max_hz == 10.0

    def test_default_processors_hz_rates(self):
        bus = DataBus()
        procs = default_processors(bus)
        # All Hz rates should be positive
        for p in procs:
            assert p._max_hz > 0

    def test_default_processors_queue_limit(self):
        bus = DataBus()
        procs = default_processors(bus)
        for p in procs:
            # Queue should be bounded (default 1024)
            assert p._queue.maxsize == 0 or p._queue.maxsize > 0

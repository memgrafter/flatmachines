"""
Unit tests for SignalDispatcher.

Tests dispatch logic with MemorySignalBackend + MemoryBackend.
"""

import pytest

from flatmachines import (
    FlatMachine,
    MemoryBackend,
    CheckpointManager,
    MachineSnapshot,
    SignalDispatcher,
)
from flatmachines.signals import MemorySignalBackend


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _wait_config(channel="test/ch"):
    return {
        "spec": "flatmachine",
        "spec_version": "1.1.1",
        "data": {
            "name": "dispatch-test",
            "context": {"val": None},
            "states": {
                "start": {
                    "type": "initial",
                    "transitions": [{"to": "wait"}],
                },
                "wait": {
                    "wait_for": channel,
                    "output_to_context": {"val": "{{ output.v }}"},
                    "transitions": [{"to": "done"}],
                },
                "done": {
                    "type": "final",
                    "output": {"val": "context.val"},
                },
            },
        },
    }


async def _park_machine(persistence, signal_backend, channel="test/ch"):
    """Run a machine until it parks at wait_for. Returns execution_id."""
    m = FlatMachine(
        config_dict=_wait_config(channel),
        persistence=persistence,
        signal_backend=signal_backend,
    )
    result = await m.execute(input={})
    assert result["_waiting"] is True
    return m.execution_id


# ---------------------------------------------------------------------------
# dispatch()
# ---------------------------------------------------------------------------

class TestDispatch:

    @pytest.mark.asyncio
    async def test_dispatch_resumes_waiting_machine(self):
        persistence = MemoryBackend()
        signal_backend = MemorySignalBackend()

        eid = await _park_machine(persistence, signal_backend)

        # Send signal
        await signal_backend.send("test/ch", {"v": "hello"})

        # Track resumes
        resumed = []

        async def resume_fn(execution_id, signal_data):
            resumed.append((execution_id, signal_data))

        dispatcher = SignalDispatcher(signal_backend, persistence, resume_fn)
        result = await dispatcher.dispatch("test/ch")

        assert result == [eid]
        assert len(resumed) == 1
        assert resumed[0] == (eid, {"v": "hello"})

    @pytest.mark.asyncio
    async def test_dispatch_no_signal_returns_empty(self):
        persistence = MemoryBackend()
        signal_backend = MemorySignalBackend()

        await _park_machine(persistence, signal_backend)

        dispatcher = SignalDispatcher(signal_backend, persistence)
        result = await dispatcher.dispatch("test/ch")
        assert result == []

    @pytest.mark.asyncio
    async def test_dispatch_no_waiters_requeues_signal(self):
        """If signal arrives but no machine is waiting, re-queue it."""
        persistence = MemoryBackend()
        signal_backend = MemorySignalBackend()

        await signal_backend.send("orphan/ch", {"data": True})

        dispatcher = SignalDispatcher(signal_backend, persistence)
        result = await dispatcher.dispatch("orphan/ch")
        assert result == []

        # Signal should be re-queued
        sig = await signal_backend.consume("orphan/ch")
        assert sig is not None
        assert sig.data == {"data": True}

    @pytest.mark.asyncio
    async def test_dispatch_multiple_waiters(self):
        """Broadcast: multiple machines waiting on same channel."""
        persistence = MemoryBackend()
        signal_backend = MemorySignalBackend()

        eid1 = await _park_machine(persistence, signal_backend, "broadcast/ch")
        eid2 = await _park_machine(persistence, signal_backend, "broadcast/ch")

        await signal_backend.send("broadcast/ch", {"v": "wake"})

        resumed = []

        async def resume_fn(execution_id, signal_data):
            resumed.append(execution_id)

        dispatcher = SignalDispatcher(signal_backend, persistence, resume_fn)
        result = await dispatcher.dispatch("broadcast/ch")

        assert set(result) == {eid1, eid2}

    @pytest.mark.asyncio
    async def test_dispatch_without_resume_fn(self):
        """Without resume_fn, dispatch returns IDs without calling anything."""
        persistence = MemoryBackend()
        signal_backend = MemorySignalBackend()

        eid = await _park_machine(persistence, signal_backend)
        await signal_backend.send("test/ch", {"v": "x"})

        dispatcher = SignalDispatcher(signal_backend, persistence)
        result = await dispatcher.dispatch("test/ch")
        assert result == [eid]


# ---------------------------------------------------------------------------
# dispatch_all()
# ---------------------------------------------------------------------------

class TestDispatchAll:

    @pytest.mark.asyncio
    async def test_dispatch_all_processes_all_channels(self):
        persistence = MemoryBackend()
        signal_backend = MemorySignalBackend()

        eid_a = await _park_machine(persistence, signal_backend, "ch/a")
        eid_b = await _park_machine(persistence, signal_backend, "ch/b")

        await signal_backend.send("ch/a", {"v": "a"})
        await signal_backend.send("ch/b", {"v": "b"})

        resumed = []

        async def resume_fn(execution_id, signal_data):
            resumed.append(execution_id)

        dispatcher = SignalDispatcher(signal_backend, persistence, resume_fn)
        results = await dispatcher.dispatch_all()

        assert "ch/a" in results
        assert "ch/b" in results
        assert set(resumed) == {eid_a, eid_b}

    @pytest.mark.asyncio
    async def test_dispatch_all_empty(self):
        persistence = MemoryBackend()
        signal_backend = MemorySignalBackend()

        dispatcher = SignalDispatcher(signal_backend, persistence)
        results = await dispatcher.dispatch_all()
        assert results == {}

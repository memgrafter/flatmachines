"""
Unit tests for wait_for state handling in FlatMachine.

Tests:
- Machine pauses at wait_for with no signal → returns _waiting
- Machine resumes when signal is available → continues
- Signal data flows through output_to_context
- Checkpoint records waiting_channel
- Transitions after wait_for state work correctly
"""

import pytest

from flatmachines import (
    FlatMachine,
    MemoryBackend,
    CheckpointManager,
    MachineSnapshot,
    WaitingForSignal,
)
from flatmachines.signals import MemorySignalBackend


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _wait_for_config(channel="test/channel", timeout=0):
    """Minimal machine config with a wait_for state."""
    return {
        "spec": "flatmachine",
        "spec_version": "1.1.1",
        "data": {
            "name": "wait-test",
            "context": {
                "task_id": "input.task_id",
                "result": None,
            },
            "states": {
                "start": {
                    "type": "initial",
                    "transitions": [{"to": "wait_state"}],
                },
                "wait_state": {
                    "wait_for": channel,
                    "timeout": timeout,
                    "output_to_context": {
                        "result": "{{ output.value }}",
                    },
                    "transitions": [
                        {"condition": "context.result == 'approved'", "to": "approved"},
                        {"to": "rejected"},
                    ],
                },
                "approved": {
                    "type": "final",
                    "output": {
                        "status": "approved",
                        "result": "context.result",
                    },
                },
                "rejected": {
                    "type": "final",
                    "output": {
                        "status": "rejected",
                        "result": "context.result",
                    },
                },
            },
        },
    }


def _templated_channel_config():
    """Machine config with Jinja2 template in wait_for."""
    return {
        "spec": "flatmachine",
        "spec_version": "1.1.1",
        "data": {
            "name": "template-wait-test",
            "context": {
                "task_id": "input.task_id",
                "approved": None,
            },
            "states": {
                "start": {
                    "type": "initial",
                    "transitions": [{"to": "wait_state"}],
                },
                "wait_state": {
                    "wait_for": "approval/{{ context.task_id }}",
                    "output_to_context": {
                        "approved": "{{ output.approved }}",
                    },
                    "transitions": [
                        {"to": "done"},
                    ],
                },
                "done": {
                    "type": "final",
                    "output": {
                        "approved": "context.approved",
                        "task_id": "context.task_id",
                    },
                },
            },
        },
    }


# ---------------------------------------------------------------------------
# Pausing at wait_for
# ---------------------------------------------------------------------------

class TestWaitForPause:

    @pytest.mark.asyncio
    async def test_pauses_with_no_signal(self):
        """Machine should checkpoint and return _waiting when no signal."""
        signal_backend = MemorySignalBackend()
        machine = FlatMachine(
            config_dict=_wait_for_config(),
            persistence=MemoryBackend(),
            signal_backend=signal_backend,
        )
        result = await machine.execute(input={"task_id": "t-1"})
        assert result["_waiting"] is True
        assert result["_channel"] == "test/channel"

    @pytest.mark.asyncio
    async def test_pauses_without_signal_backend(self):
        """Machine should pause even without signal_backend (None)."""
        machine = FlatMachine(
            config_dict=_wait_for_config(),
            persistence=MemoryBackend(),
            signal_backend=None,
        )
        result = await machine.execute(input={"task_id": "t-1"})
        assert result["_waiting"] is True

    @pytest.mark.asyncio
    async def test_checkpoint_has_waiting_channel(self):
        """Checkpoint should record the waiting_channel."""
        persistence = MemoryBackend()
        signal_backend = MemorySignalBackend()
        machine = FlatMachine(
            config_dict=_wait_for_config(),
            persistence=persistence,
            signal_backend=signal_backend,
        )
        await machine.execute(input={"task_id": "t-1"})

        mgr = CheckpointManager(persistence, machine.execution_id)
        snapshot = await mgr.load_latest()
        assert snapshot is not None
        assert snapshot.waiting_channel == "test/channel"
        assert snapshot.current_state == "wait_state"

    @pytest.mark.asyncio
    async def test_templated_channel(self):
        """wait_for with Jinja2 template should render correctly."""
        signal_backend = MemorySignalBackend()
        machine = FlatMachine(
            config_dict=_templated_channel_config(),
            persistence=MemoryBackend(),
            signal_backend=signal_backend,
        )
        result = await machine.execute(input={"task_id": "task-42"})
        assert result["_waiting"] is True
        assert result["_channel"] == "approval/task-42"


# ---------------------------------------------------------------------------
# Resuming with signal
# ---------------------------------------------------------------------------

class TestWaitForResume:

    @pytest.mark.asyncio
    async def test_resumes_on_signal(self):
        """Signal pre-loaded → machine should consume and continue."""
        signal_backend = MemorySignalBackend()
        await signal_backend.send("test/channel", {"value": "approved"})

        machine = FlatMachine(
            config_dict=_wait_for_config(),
            persistence=MemoryBackend(),
            signal_backend=signal_backend,
        )
        result = await machine.execute(input={"task_id": "t-1"})
        assert result["status"] == "approved"
        assert result["result"] == "approved"

    @pytest.mark.asyncio
    async def test_transitions_after_signal(self):
        """Signal with non-approved value → rejected path."""
        signal_backend = MemorySignalBackend()
        await signal_backend.send("test/channel", {"value": "denied"})

        machine = FlatMachine(
            config_dict=_wait_for_config(),
            persistence=MemoryBackend(),
            signal_backend=signal_backend,
        )
        result = await machine.execute(input={"task_id": "t-1"})
        assert result["status"] == "rejected"
        assert result["result"] == "denied"

    @pytest.mark.asyncio
    async def test_resume_from_checkpoint(self):
        """Pause → send signal → resume from checkpoint."""
        persistence = MemoryBackend()
        signal_backend = MemorySignalBackend()

        # First run: pause
        m1 = FlatMachine(
            config_dict=_wait_for_config(),
            persistence=persistence,
            signal_backend=signal_backend,
        )
        result1 = await m1.execute(input={"task_id": "t-1"})
        assert result1["_waiting"] is True
        eid = m1.execution_id

        # Signal arrives
        await signal_backend.send("test/channel", {"value": "approved"})

        # Resume
        m2 = FlatMachine(
            config_dict=_wait_for_config(),
            persistence=persistence,
            signal_backend=signal_backend,
        )
        result2 = await m2.execute(resume_from=eid)
        assert result2["status"] == "approved"

    @pytest.mark.asyncio
    async def test_resume_templated_channel(self):
        """Pause with template channel → send signal → resume."""
        persistence = MemoryBackend()
        signal_backend = MemorySignalBackend()

        m1 = FlatMachine(
            config_dict=_templated_channel_config(),
            persistence=persistence,
            signal_backend=signal_backend,
        )
        result1 = await m1.execute(input={"task_id": "task-99"})
        assert result1["_waiting"] is True
        assert result1["_channel"] == "approval/task-99"
        eid = m1.execution_id

        await signal_backend.send("approval/task-99", {"approved": True})

        m2 = FlatMachine(
            config_dict=_templated_channel_config(),
            persistence=persistence,
            signal_backend=signal_backend,
        )
        result2 = await m2.execute(resume_from=eid)
        assert result2["task_id"] == "task-99"
        assert result2["approved"] == "True"  # Jinja renders to string


# ---------------------------------------------------------------------------
# Signal data → output_to_context
# ---------------------------------------------------------------------------

class TestSignalDataMapping:

    @pytest.mark.asyncio
    async def test_output_to_context_mapping(self):
        """Signal data should be accessible via output.* in templates."""
        signal_backend = MemorySignalBackend()
        await signal_backend.send("test/channel", {"value": "hello"})

        machine = FlatMachine(
            config_dict=_wait_for_config(),
            persistence=MemoryBackend(),
            signal_backend=signal_backend,
        )
        result = await machine.execute(input={"task_id": "t-1"})
        assert result["result"] == "hello"

    @pytest.mark.asyncio
    async def test_signal_consumed_only_once(self):
        """After consumption, signal should be gone."""
        signal_backend = MemorySignalBackend()
        await signal_backend.send("test/channel", {"value": "approved"})

        machine = FlatMachine(
            config_dict=_wait_for_config(),
            persistence=MemoryBackend(),
            signal_backend=signal_backend,
        )
        await machine.execute(input={"task_id": "t-1"})

        # Signal should be consumed
        assert await signal_backend.consume("test/channel") is None


# ---------------------------------------------------------------------------
# Persistence filtering by waiting_channel
# ---------------------------------------------------------------------------

class TestWaitingChannelFilter:

    @pytest.mark.asyncio
    async def test_list_by_waiting_channel(self):
        """list_execution_ids(waiting_channel=...) finds waiting machines."""
        persistence = MemoryBackend()
        signal_backend = MemorySignalBackend()

        # Park two machines on different channels
        m1 = FlatMachine(
            config_dict=_wait_for_config("channel/a"),
            persistence=persistence,
            signal_backend=signal_backend,
        )
        await m1.execute(input={"task_id": "t-1"})

        m2 = FlatMachine(
            config_dict=_wait_for_config("channel/b"),
            persistence=persistence,
            signal_backend=signal_backend,
        )
        await m2.execute(input={"task_id": "t-2"})

        ids_a = await persistence.list_execution_ids(waiting_channel="channel/a")
        ids_b = await persistence.list_execution_ids(waiting_channel="channel/b")

        assert len(ids_a) == 1
        assert len(ids_b) == 1
        assert ids_a[0] != ids_b[0]

    @pytest.mark.asyncio
    async def test_no_match_returns_empty(self):
        persistence = MemoryBackend()
        signal_backend = MemorySignalBackend()

        m = FlatMachine(
            config_dict=_wait_for_config("channel/x"),
            persistence=persistence,
            signal_backend=signal_backend,
        )
        await m.execute(input={"task_id": "t-1"})

        ids = await persistence.list_execution_ids(waiting_channel="channel/y")
        assert ids == []


# ---------------------------------------------------------------------------
# WaitingForSignal exception
# ---------------------------------------------------------------------------

class TestWaitingForSignalException:

    def test_has_channel(self):
        exc = WaitingForSignal("test/ch")
        assert exc.channel == "test/ch"
        assert "test/ch" in str(exc)

    def test_importable_from_init(self):
        from flatmachines import WaitingForSignal as WFS
        assert WFS is WaitingForSignal

"""
Integration tests for FlatMachine lifecycle features.

Tests:
1. Machine-level on_error   — default error handler for all states
2. persistence.resume       — auto-retry from checkpoint on unhandled errors
3. list_executions()        — load snapshots by execution ID
4. cleanup_executions()     — remove old checkpoint data
"""

import asyncio
import os
import shutil
import pytest
from datetime import timedelta

from flatmachines import (
    FlatMachine,
    MachineHooks,
    LocalFileBackend,
    MemoryBackend,
)
from flatmachines.lifecycle import (
    list_executions,
    cleanup_executions,
)
from flatmachines.persistence import CheckpointManager, MachineSnapshot


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class CounterHooks(MachineHooks):
    """Hooks that increment a counter and optionally crash."""

    def __init__(self, crash_at: int = None, crash_count: int = 1):
        self.crash_at = crash_at
        self.crash_count = crash_count
        self._crashes = 0

    def on_action(self, action_name, context):
        if action_name == "increment":
            context["count"] = context.get("count", 0) + 1
            if (
                self.crash_at
                and context["count"] == self.crash_at
                and self._crashes < self.crash_count
            ):
                self._crashes += 1
                raise RuntimeError(f"Simulated crash at count {self.crash_at}")
        elif action_name == "handle_error":
            context["error_handled"] = True
        return context


def counter_config(**overrides):
    """Simple counter machine config. Pass overrides to merge into data."""
    config = {
        "spec": "flatmachine",
        "spec_version": "0.1.0",
        "data": {
            "name": "counter",
            "context": {"count": 0},
            "persistence": {"enabled": True, "backend": "local"},
            "states": {
                "start": {
                    "type": "initial",
                    "transitions": [{"to": "count_up"}],
                },
                "count_up": {
                    "action": "increment",
                    "transitions": [
                        {"condition": "context.count >= 5", "to": "end"},
                        {"to": "count_up"},
                    ],
                },
                "end": {
                    "type": "final",
                    "output": {"final_count": "{{ context.count }}"},
                },
            },
        },
    }
    config["data"].update(overrides)
    return config


@pytest.fixture(autouse=True)
def cleanup():
    """Clean up checkpoint and lock directories before and after tests."""
    for d in [".checkpoints", ".locks"]:
        if os.path.exists(d):
            shutil.rmtree(d)
    yield
    for d in [".checkpoints", ".locks"]:
        if os.path.exists(d):
            shutil.rmtree(d)


# ---------------------------------------------------------------------------
# Machine-level on_error tests
# ---------------------------------------------------------------------------

class TestMachineLevelOnError:

    @pytest.mark.asyncio
    async def test_machine_on_error_catches_state_without_own_handler(self):
        """Machine-level on_error handles errors from states with no on_error."""
        config = counter_config(
            on_error="error_handler",
            states={
                "start": {
                    "type": "initial",
                    "transitions": [{"to": "count_up"}],
                },
                "count_up": {
                    "action": "increment",
                    # No state-level on_error — machine-level catches it
                    "transitions": [
                        {"condition": "context.count >= 5", "to": "end"},
                        {"to": "count_up"},
                    ],
                },
                "error_handler": {
                    "action": "handle_error",
                    "transitions": [{"to": "error_end"}],
                },
                "error_end": {
                    "type": "final",
                    "output": {
                        "error": "{{ context.last_error }}",
                        "handled": "{{ context.error_handled }}",
                    },
                },
                "end": {
                    "type": "final",
                    "output": {"final_count": "{{ context.count }}"},
                },
            },
        )

        hooks = CounterHooks(crash_at=3, crash_count=999)
        machine = FlatMachine(config_dict=config, hooks=hooks)
        result = await machine.execute(input={})

        assert "Simulated crash" in result["error"]
        assert result["handled"] == "True"

    @pytest.mark.asyncio
    async def test_state_on_error_overrides_machine_level(self):
        """State-level on_error takes precedence over machine-level."""
        config = counter_config(
            on_error="machine_handler",
            states={
                "start": {
                    "type": "initial",
                    "transitions": [{"to": "count_up"}],
                },
                "count_up": {
                    "action": "increment",
                    "on_error": "state_handler",  # overrides machine-level
                    "transitions": [
                        {"condition": "context.count >= 5", "to": "end"},
                        {"to": "count_up"},
                    ],
                },
                "state_handler": {
                    "type": "final",
                    "output": {"handler": "state"},
                },
                "machine_handler": {
                    "type": "final",
                    "output": {"handler": "machine"},
                },
                "end": {
                    "type": "final",
                    "output": {"final_count": "{{ context.count }}"},
                },
            },
        )

        hooks = CounterHooks(crash_at=3, crash_count=999)
        machine = FlatMachine(config_dict=config, hooks=hooks)
        result = await machine.execute(input={})

        assert result["handler"] == "state"

    @pytest.mark.asyncio
    async def test_machine_on_error_granular_format(self):
        """Machine-level on_error with {ErrorType: state} format."""
        config = counter_config(
            on_error={"RuntimeError": "runtime_handler", "default": "generic_handler"},
            states={
                "start": {
                    "type": "initial",
                    "transitions": [{"to": "count_up"}],
                },
                "count_up": {
                    "action": "increment",
                    "transitions": [
                        {"condition": "context.count >= 5", "to": "end"},
                        {"to": "count_up"},
                    ],
                },
                "runtime_handler": {
                    "type": "final",
                    "output": {"handler": "runtime"},
                },
                "generic_handler": {
                    "type": "final",
                    "output": {"handler": "generic"},
                },
                "end": {
                    "type": "final",
                    "output": {"final_count": "{{ context.count }}"},
                },
            },
        )

        hooks = CounterHooks(crash_at=3, crash_count=999)
        machine = FlatMachine(config_dict=config, hooks=hooks)
        result = await machine.execute(input={})

        assert result["handler"] == "runtime"

    @pytest.mark.asyncio
    async def test_no_machine_on_error_propagates(self):
        """Without machine-level on_error, exceptions propagate as before."""
        config = counter_config()
        hooks = CounterHooks(crash_at=3, crash_count=999)
        machine = FlatMachine(config_dict=config, hooks=hooks)

        with pytest.raises(RuntimeError, match="Simulated crash"):
            await machine.execute(input={})

    @pytest.mark.asyncio
    async def test_machine_on_error_no_effect_when_no_errors(self):
        """Machine-level on_error doesn't interfere with normal execution."""
        config = counter_config(on_error="error_handler")
        # Add the error_handler state just in case
        config["data"]["states"]["error_handler"] = {
            "type": "final",
            "output": {"handler": "error"},
        }

        hooks = CounterHooks()  # no crashes
        machine = FlatMachine(config_dict=config, hooks=hooks)
        result = await machine.execute(input={})

        assert int(result["final_count"]) == 5


# ---------------------------------------------------------------------------
# persistence.resume tests
# ---------------------------------------------------------------------------

class TestPersistenceResume:

    @pytest.mark.asyncio
    async def test_resume_retries_from_checkpoint(self):
        """persistence.resume auto-retries and resumes from checkpoint."""
        config = counter_config(
            persistence={
                "enabled": True,
                "backend": "local",
                "resume": {
                    "max_retries": 2,
                    "backoffs": [0.01],
                    "jitter": 0.0,
                },
            },
        )

        # crash_count=1: crash once at count 3, then succeed on retry
        hooks = CounterHooks(crash_at=3, crash_count=1)
        machine = FlatMachine(config_dict=config, hooks=hooks)
        result = await machine.execute(input={})

        assert int(result["final_count"]) == 5

    @pytest.mark.asyncio
    async def test_resume_exhausts_retries(self):
        """All retries exhausted raises the last error."""
        config = counter_config(
            persistence={
                "enabled": True,
                "backend": "local",
                "resume": {
                    "max_retries": 1,
                    "backoffs": [0.01],
                    "jitter": 0.0,
                },
            },
        )

        # crash_count=10: always crashes
        hooks = CounterHooks(crash_at=3, crash_count=10)
        machine = FlatMachine(config_dict=config, hooks=hooks)

        with pytest.raises(RuntimeError, match="Simulated crash"):
            await machine.execute(input={})

    @pytest.mark.asyncio
    async def test_resume_disabled_by_default(self):
        """Without persistence.resume, errors propagate immediately."""
        config = counter_config()
        hooks = CounterHooks(crash_at=3, crash_count=1)
        machine = FlatMachine(config_dict=config, hooks=hooks)

        # Should crash without retry even though crash_count=1
        with pytest.raises(RuntimeError, match="Simulated crash"):
            await machine.execute(input={})

    @pytest.mark.asyncio
    async def test_resume_with_machine_on_error(self):
        """persistence.resume and machine-level on_error work together.

        on_error handles application errors (routes to recovery state).
        resume handles infrastructure errors that escape the state graph.
        """
        config = counter_config(
            on_error="error_handler",
            persistence={
                "enabled": True,
                "backend": "local",
                "resume": {
                    "max_retries": 2,
                    "backoffs": [0.01],
                    "jitter": 0.0,
                },
            },
            states={
                "start": {
                    "type": "initial",
                    "transitions": [{"to": "count_up"}],
                },
                "count_up": {
                    "action": "increment",
                    # State has NO on_error → machine-level catches it
                    "transitions": [
                        {"condition": "context.count >= 5", "to": "end"},
                        {"to": "count_up"},
                    ],
                },
                "error_handler": {
                    "action": "handle_error",
                    "transitions": [{"to": "error_end"}],
                },
                "error_end": {
                    "type": "final",
                    "output": {
                        "error": "{{ context.last_error }}",
                        "handled": "{{ context.error_handled }}",
                    },
                },
                "end": {
                    "type": "final",
                    "output": {"final_count": "{{ context.count }}"},
                },
            },
        )

        # Machine-level on_error should catch this — resume not needed
        hooks = CounterHooks(crash_at=3, crash_count=999)
        machine = FlatMachine(config_dict=config, hooks=hooks)
        result = await machine.execute(input={})

        assert result["handled"] == "True"


# ---------------------------------------------------------------------------
# list_executions tests
# ---------------------------------------------------------------------------

class TestListExecutions:

    @pytest.mark.asyncio
    async def test_returns_snapshots_for_completed_runs(self):
        backend = LocalFileBackend()
        m1 = FlatMachine(
            config_dict=counter_config(), hooks=CounterHooks(), persistence=backend,
        )
        m2 = FlatMachine(
            config_dict=counter_config(), hooks=CounterHooks(), persistence=backend,
        )
        await m1.execute(input={})
        await m2.execute(input={})

        snaps = await list_executions(
            backend, [m1.execution_id, m2.execution_id],
        )
        assert len(snaps) == 2
        assert all(s.event == "machine_end" for s in snaps)

    @pytest.mark.asyncio
    async def test_skips_missing_ids(self):
        backend = LocalFileBackend()
        m = FlatMachine(
            config_dict=counter_config(), hooks=CounterHooks(), persistence=backend,
        )
        await m.execute(input={})

        snaps = await list_executions(
            backend, [m.execution_id, "nonexistent-id"],
        )
        assert len(snaps) == 1
        assert snaps[0].execution_id == m.execution_id

    @pytest.mark.asyncio
    async def test_sorted_newest_first(self):
        backend = MemoryBackend()
        snap_old = MachineSnapshot(
            execution_id="old", machine_name="counter",
            spec_version="0.1.0", current_state="end", context={},
            step=5, event="machine_end",
            created_at="2024-01-01T00:00:00+00:00",
        )
        snap_new = MachineSnapshot(
            execution_id="new", machine_name="counter",
            spec_version="0.1.0", current_state="end", context={},
            step=5, event="machine_end",
            created_at="2025-06-01T00:00:00+00:00",
        )
        await CheckpointManager(backend, "old").save_checkpoint(snap_old)
        await CheckpointManager(backend, "new").save_checkpoint(snap_new)

        snaps = await list_executions(backend, ["old", "new"])
        assert snaps[0].execution_id == "new"
        assert snaps[1].execution_id == "old"

    @pytest.mark.asyncio
    async def test_empty_list(self):
        backend = MemoryBackend()
        snaps = await list_executions(backend, [])
        assert snaps == []


# ---------------------------------------------------------------------------
# cleanup_executions tests
# ---------------------------------------------------------------------------

class TestCleanupExecutions:

    @pytest.mark.asyncio
    async def test_removes_all_when_no_filter(self):
        backend = LocalFileBackend()
        m = FlatMachine(
            config_dict=counter_config(), hooks=CounterHooks(), persistence=backend,
        )
        await m.execute(input={})

        removed = await cleanup_executions(backend, [m.execution_id])
        assert m.execution_id in removed

        snap = await CheckpointManager(backend, m.execution_id).load_latest()
        assert snap is None

    @pytest.mark.asyncio
    async def test_older_than_skips_recent(self):
        backend = LocalFileBackend()
        m = FlatMachine(
            config_dict=counter_config(), hooks=CounterHooks(), persistence=backend,
        )
        await m.execute(input={})

        removed = await cleanup_executions(
            backend, [m.execution_id], older_than=timedelta(days=1),
        )
        assert removed == []

        snap = await CheckpointManager(backend, m.execution_id).load_latest()
        assert snap is not None

    @pytest.mark.asyncio
    async def test_older_than_removes_old(self):
        backend = MemoryBackend()
        snap = MachineSnapshot(
            execution_id="ancient", machine_name="counter",
            spec_version="0.1.0", current_state="end", context={},
            step=1, event="machine_end",
            created_at="2020-01-01T00:00:00+00:00",
        )
        await CheckpointManager(backend, "ancient").save_checkpoint(snap)

        removed = await cleanup_executions(
            backend, ["ancient"], older_than=timedelta(days=1),
        )
        assert "ancient" in removed

    @pytest.mark.asyncio
    async def test_memory_backend_cleanup(self):
        backend = MemoryBackend()
        snap = MachineSnapshot(
            execution_id="mem-1", machine_name="counter",
            spec_version="0.1.0", current_state="end", context={},
            step=1, event="machine_end",
        )
        await CheckpointManager(backend, "mem-1").save_checkpoint(snap)

        removed = await cleanup_executions(backend, ["mem-1"])
        assert "mem-1" in removed

        remaining = [k for k in backend._store if k.startswith("mem-1/")]
        assert remaining == []

    @pytest.mark.asyncio
    async def test_local_backend_removes_directory(self):
        backend = LocalFileBackend()
        m = FlatMachine(
            config_dict=counter_config(), hooks=CounterHooks(), persistence=backend,
        )
        await m.execute(input={})
        exec_dir = backend.base_dir / m.execution_id
        assert exec_dir.exists()

        await cleanup_executions(backend, [m.execution_id])
        assert not exec_dir.exists()

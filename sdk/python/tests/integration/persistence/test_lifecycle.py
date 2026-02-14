"""
Integration tests for FlatMachine lifecycle helpers.

Tests:
1. resilient_run()       — auto-retry with checkpoint resume
2. list_executions()     — load snapshots by execution ID
3. cleanup_executions()  — remove old checkpoint data
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
    resilient_run,
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
        return context


def counter_config():
    """Simple counter machine config with persistence enabled."""
    return {
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
# resilient_run tests
# ---------------------------------------------------------------------------

class TestResilientRun:

    @pytest.mark.asyncio
    async def test_success_no_retries(self):
        result = await resilient_run(
            config_dict=counter_config(),
            hooks=CounterHooks(),
            input={},
        )
        assert int(result["final_count"]) == 5

    @pytest.mark.asyncio
    async def test_retry_recovers_from_transient_failure(self):
        # Shared hooks: crash once at count 3, then succeed on retry
        hooks = CounterHooks(crash_at=3, crash_count=1)
        result = await resilient_run(
            config_dict=counter_config(),
            hooks=hooks,
            input={},
            max_retries=2,
            retry_delay=0.01,
        )
        assert int(result["final_count"]) == 5

    @pytest.mark.asyncio
    async def test_exhausts_retries_then_raises(self):
        with pytest.raises(RuntimeError, match="Simulated crash"):
            await resilient_run(
                config_dict=counter_config(),
                # crash_count=10 → always crashes
                hooks_factory=lambda: CounterHooks(crash_at=3, crash_count=10),
                input={},
                max_retries=1,
                retry_delay=0.01,
            )

    @pytest.mark.asyncio
    async def test_hooks_factory_gets_fresh_hooks(self):
        call_count = 0

        def factory():
            nonlocal call_count
            call_count += 1
            return CounterHooks()

        await resilient_run(
            config_dict=counter_config(),
            hooks_factory=factory,
            input={},
            max_retries=0,
        )
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_with_memory_backend(self):
        config = counter_config()
        config["data"]["persistence"]["backend"] = "memory"
        result = await resilient_run(
            config_dict=config,
            hooks=CounterHooks(),
            input={},
            backend=MemoryBackend(),
        )
        assert int(result["final_count"]) == 5


# ---------------------------------------------------------------------------
# list_executions tests
# ---------------------------------------------------------------------------

class TestListExecutions:

    @pytest.mark.asyncio
    async def test_returns_snapshots_for_completed_runs(self):
        backend = LocalFileBackend()
        # Run two machines
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
        # Manually save two snapshots with known timestamps
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

        # Snapshot should be gone
        snap = await CheckpointManager(backend, m.execution_id).load_latest()
        assert snap is None

    @pytest.mark.asyncio
    async def test_older_than_skips_recent(self):
        backend = LocalFileBackend()
        m = FlatMachine(
            config_dict=counter_config(), hooks=CounterHooks(), persistence=backend,
        )
        await m.execute(input={})

        # Just ran — should NOT be removed with a 1-day cutoff
        removed = await cleanup_executions(
            backend, [m.execution_id], older_than=timedelta(days=1),
        )
        assert removed == []

        # Snapshot should still exist
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

        # All keys for this execution should be gone
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

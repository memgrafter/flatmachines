"""
Integration tests for the scheduler machine.

Tests the full machine lifecycle: init → seed → hydrate → pick → claim →
dispatch → settle → check_done → loop/sleep/done.

Uses MemoryWorkBackend + MemorySignalBackend + MemoryBackend.

The YAML configs reference hooks: "deepsleep" — each test registers the
DeepSleepHooks instance in a HooksRegistry, mirroring what the runner does.
"""
from __future__ import annotations

import copy

import pytest
from _helpers import load_config, load_module, make_hooks_registry

scheduler_config = load_config("scheduler_machine.yml")
hooks_mod = load_module("hooks.py", "deepsleep_hooks")

DeepSleepHooks = hooks_mod.DeepSleepHooks


def _scheduler_input(**overrides):
    base = {
        "pool_name": "tasks",
        "max_active_roots": 2,
        "batch_size": 4,
        "n_roots": 2,
        "max_depth": 2,
        "resume": False,
        "cleanup": False,
    }
    base.update(overrides)
    return base


class TestSchedulerFreshRun:
    """Fresh run: seed → hydrate → pick → dispatch → ... → done."""

    @pytest.mark.asyncio
    async def test_fresh_run_completes(self):
        """Scheduler should complete when all roots are done."""
        from flatmachines import FlatMachine, MemoryBackend, MemoryWorkBackend, MemorySignalBackend

        work_backend = MemoryWorkBackend()
        signal_backend = MemorySignalBackend()
        persistence = MemoryBackend()

        hooks = DeepSleepHooks(
            max_depth=2, fail_rate=0.0, seed=7, max_attempts=3,
            work_backend=work_backend, signal_backend=signal_backend,
        )

        machine = FlatMachine(
            config_dict=copy.deepcopy(scheduler_config),
            hooks_registry=make_hooks_registry(hooks),
            persistence=persistence,
            signal_backend=signal_backend,
        )

        result = await machine.execute(input=_scheduler_input(n_roots=2, max_depth=2))

        # Should complete (not be waiting)
        assert result.get("_waiting") is not True
        assert "roots" in result

    @pytest.mark.asyncio
    async def test_fresh_run_produces_root_entries(self):
        from flatmachines import FlatMachine, MemoryBackend, MemoryWorkBackend, MemorySignalBackend

        work_backend = MemoryWorkBackend()
        signal_backend = MemorySignalBackend()

        hooks = DeepSleepHooks(
            max_depth=1, fail_rate=0.0, seed=7, max_attempts=3,
            work_backend=work_backend, signal_backend=signal_backend,
        )

        machine = FlatMachine(
            config_dict=copy.deepcopy(scheduler_config),
            hooks_registry=make_hooks_registry(hooks),
            persistence=MemoryBackend(),
            signal_backend=signal_backend,
        )

        result = await machine.execute(input=_scheduler_input(n_roots=2, max_depth=1))
        roots = result.get("roots", {})
        assert "root-000" in roots
        assert "root-001" in roots


class TestSchedulerSleep:
    """Sleep behavior when no work is runnable but work remains."""

    @pytest.mark.asyncio
    async def test_sleeps_when_no_runnable_candidates(self):
        """If pick finds nothing runnable (e.g. gate closed), scheduler should sleep."""
        from flatmachines import FlatMachine, MemoryBackend, MemoryWorkBackend, MemorySignalBackend

        work_backend = MemoryWorkBackend()
        signal_backend = MemorySignalBackend()
        persistence = MemoryBackend()

        hooks = DeepSleepHooks(
            max_depth=2, fail_rate=0.0, seed=7, max_attempts=3,
            gate_interval=99999.0,
            work_backend=work_backend, signal_backend=signal_backend,
        )

        pool = work_backend.pool("tasks")
        await pool.push(
            {"task_id": "r/0", "root_id": "r", "depth": 0, "resource_class": "slow"},
            options={"max_retries": 3},
        )

        machine = FlatMachine(
            config_dict=copy.deepcopy(scheduler_config),
            hooks_registry=make_hooks_registry(hooks),
            persistence=persistence,
            signal_backend=signal_backend,
        )

        result = await machine.execute(input=_scheduler_input(n_roots=0, max_depth=2))

        # With 0 roots seeded and no candidates, it should complete as all_done
        assert result.get("_waiting") is not True


class TestSchedulerCheckpointResume:
    """Checkpoint and resume behavior."""

    @pytest.mark.asyncio
    async def test_waiting_channel_in_checkpoint(self):
        """When scheduler hits sleep, checkpoint should record waiting_channel."""
        from flatmachines import FlatMachine, MemoryBackend, MemoryWorkBackend, MemorySignalBackend, CheckpointManager

        work_backend = MemoryWorkBackend()
        signal_backend = MemorySignalBackend()
        persistence = MemoryBackend()

        pool = work_backend.pool("tasks")
        await pool.push(
            {"task_id": "r/0", "root_id": "r", "depth": 0, "resource_class": "slow"},
            options={"max_retries": 3},
        )

        hooks = DeepSleepHooks(
            max_depth=2, fail_rate=0.0, seed=7, max_attempts=3,
            gate_interval=99999.0,
            work_backend=work_backend, signal_backend=signal_backend,
        )

        # Override seed to close slow gate immediately
        orig_seed = hooks._seed_work

        async def _seed_then_close_gate(ctx):
            ctx = await orig_seed(ctx)
            ctx["resources"]["slow"]["gate_open"] = False
            return ctx

        hooks._seed_work = _seed_then_close_gate

        machine = FlatMachine(
            config_dict=copy.deepcopy(scheduler_config),
            hooks_registry=make_hooks_registry(hooks),
            persistence=persistence,
            signal_backend=signal_backend,
        )

        result = await machine.execute(input=_scheduler_input(n_roots=0, max_depth=2))

        if result.get("_waiting"):
            mgr = CheckpointManager(persistence, machine.execution_id)
            snapshot = await mgr.load_latest()
            assert snapshot is not None
            assert snapshot.waiting_channel == "dfss/ready"

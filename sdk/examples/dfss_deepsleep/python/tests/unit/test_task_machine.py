"""Unit tests for the task runner machine."""
from __future__ import annotations

import copy

import pytest
from _helpers import load_config, load_module, make_hooks_registry

task_config = load_config("task_machine.yml")
hooks_mod = load_module("hooks.py", "deepsleep_hooks")

DeepSleepHooks = hooks_mod.DeepSleepHooks


class TestTaskMachine:

    @pytest.mark.asyncio
    async def test_task_runs_to_completion(self):
        from flatmachines import FlatMachine, MemoryBackend

        hooks = DeepSleepHooks(max_depth=3, fail_rate=0.0, seed=42)
        machine = FlatMachine(
            config_dict=copy.deepcopy(task_config),
            hooks_registry=make_hooks_registry(hooks),
            persistence=MemoryBackend(),
        )

        result = await machine.execute(input={
            "task_id": "r/0",
            "root_id": "r",
            "depth": 0,
            "resource_class": "fast",
        })

        assert result["task_id"] == "r/0"
        assert result["result"] == "ok:r/0"
        assert isinstance(result["children"], list)

    @pytest.mark.asyncio
    async def test_leaf_task_no_children(self):
        from flatmachines import FlatMachine, MemoryBackend

        hooks = DeepSleepHooks(max_depth=2, fail_rate=0.0, seed=42)
        machine = FlatMachine(
            config_dict=copy.deepcopy(task_config),
            hooks_registry=make_hooks_registry(hooks),
            persistence=MemoryBackend(),
        )

        result = await machine.execute(input={
            "task_id": "r/0",
            "root_id": "r",
            "depth": 2,
            "resource_class": "fast",
        })

        assert result["children"] == []

    @pytest.mark.asyncio
    async def test_task_error_goes_to_error_exit(self):
        from flatmachines import FlatMachine, MemoryBackend

        hooks = DeepSleepHooks(max_depth=3, fail_rate=1.0, seed=1)
        machine = FlatMachine(
            config_dict=copy.deepcopy(task_config),
            hooks_registry=make_hooks_registry(hooks),
            persistence=MemoryBackend(),
        )

        result = await machine.execute(input={
            "task_id": "r/0",
            "root_id": "r",
            "depth": 0,
            "resource_class": "fast",
        })

        assert "error" in result
        assert result["task_id"] == "r/0"

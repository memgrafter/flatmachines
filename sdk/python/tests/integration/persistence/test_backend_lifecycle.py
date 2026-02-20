"""
Integration: list_execution_ids / delete_execution through real machine runs.
"""

import os
import shutil
import pytest

from flatmachines import FlatMachine, MachineHooks, LocalFileBackend, MemoryBackend, CheckpointManager


class CounterHooks(MachineHooks):
    def on_action(self, action_name, context):
        if action_name == "increment":
            context["count"] = context.get("count", 0) + 1
        return context


COUNTER_CONFIG = {
    "spec": "flatmachine",
    "spec_version": "0.1.0",
    "data": {
        "name": "counter",
        "context": {"count": 0},
        "persistence": {"enabled": True, "backend": "local"},
        "states": {
            "start": {"type": "initial", "transitions": [{"to": "count_up"}]},
            "count_up": {
                "action": "increment",
                "transitions": [
                    {"condition": "context.count >= 3", "to": "end"},
                    {"to": "count_up"},
                ],
            },
            "end": {"type": "final", "output": {"final_count": "{{ context.count }}"}},
        },
    },
}


@pytest.fixture(autouse=True)
def cleanup():
    for d in [".checkpoints", ".locks"]:
        if os.path.exists(d):
            shutil.rmtree(d)
    yield
    for d in [".checkpoints", ".locks"]:
        if os.path.exists(d):
            shutil.rmtree(d)


class TestBackendLifecycleIntegration:

    @pytest.mark.asyncio
    async def test_list_after_runs(self):
        backend = LocalFileBackend()
        m1 = FlatMachine(config_dict=COUNTER_CONFIG, hooks=CounterHooks(), persistence=backend)
        m2 = FlatMachine(config_dict=COUNTER_CONFIG, hooks=CounterHooks(), persistence=backend)
        await m1.execute(input={})
        await m2.execute(input={})

        ids = await backend.list_execution_ids()
        assert set(ids) == {m1.execution_id, m2.execution_id}

    @pytest.mark.asyncio
    async def test_delete_after_run(self):
        backend = LocalFileBackend()
        m1 = FlatMachine(config_dict=COUNTER_CONFIG, hooks=CounterHooks(), persistence=backend)
        m2 = FlatMachine(config_dict=COUNTER_CONFIG, hooks=CounterHooks(), persistence=backend)
        await m1.execute(input={})
        await m2.execute(input={})

        await backend.delete_execution(m1.execution_id)

        ids = await backend.list_execution_ids()
        assert ids == [m2.execution_id]
        assert await CheckpointManager(backend, m1.execution_id).load_latest() is None
        assert await CheckpointManager(backend, m2.execution_id).load_latest() is not None

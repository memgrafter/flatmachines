"""
Unit and integration tests for clone_snapshot.

Unit tests:
1. Clone rewrites execution_id, created_at, parent_execution_id
2. Clone drops pending_launches
3. Clone preserves current_state, context, step, tool_loop_state, waiting_channel
4. Clone is persisted and loadable via CheckpointManager(new_id).load_latest()

Integration test:
5. Self-differentiating clone: parent and clone hit same state, transition
   differently based on context.machine.execution_id
"""

import uuid
from datetime import datetime, timezone

import pytest

from flatmachines import (
    FlatMachine,
    MemoryBackend,
    CheckpointManager,
    MachineHooks,
    MachineSnapshot,
    HooksRegistry,
    clone_snapshot,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _machine_with_state_hooks(config, hooks: MachineHooks, **kwargs):
    cfg = {**config, "data": {**config["data"], "states": {}}}
    for name, state in config["data"]["states"].items():
        cfg["data"]["states"][name] = {**state, "hooks": "test-hooks"}

    registry = HooksRegistry()
    registry.register("test-hooks", lambda: hooks)
    return FlatMachine(config_dict=cfg, hooks_registry=registry, **kwargs)


def _make_snapshot(**overrides) -> MachineSnapshot:
    """Build a MachineSnapshot with sensible defaults, overridable."""
    defaults = dict(
        execution_id="source-exec-001",
        machine_name="test-machine",
        spec_version="2.0.0",
        current_state="middle",
        context={"score": 42, "items": [1, 2, 3]},
        step=5,
        created_at="2025-01-01T00:00:00+00:00",
        event="state_enter",
        output=None,
        total_api_calls=3,
        total_cost=0.05,
        parent_execution_id=None,
        pending_launches=[{"machine": "child", "id": "child-001"}],
        waiting_channel=None,
        tool_loop_state={"chain": ["a", "b"], "turns": 2, "tool_calls_count": 4, "loop_cost": 0.01},
    )
    defaults.update(overrides)
    return MachineSnapshot(**defaults)


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------

class TestCloneRewritesIdentity:

    @pytest.mark.asyncio
    async def test_execution_id_rewritten(self):
        persistence = MemoryBackend()
        source = _make_snapshot()
        cloned = await clone_snapshot(source, "new-exec-999", persistence)

        assert cloned.execution_id == "new-exec-999"
        assert source.execution_id == "source-exec-001"  # source unchanged

    @pytest.mark.asyncio
    async def test_created_at_is_fresh(self):
        persistence = MemoryBackend()
        source = _make_snapshot(created_at="2020-01-01T00:00:00+00:00")
        before = datetime.now(timezone.utc)
        cloned = await clone_snapshot(source, "new-exec", persistence)
        after = datetime.now(timezone.utc)

        cloned_time = datetime.fromisoformat(cloned.created_at)
        assert before <= cloned_time <= after
        assert cloned.created_at != source.created_at

    @pytest.mark.asyncio
    async def test_parent_execution_id_set_to_source(self):
        persistence = MemoryBackend()
        source = _make_snapshot(parent_execution_id="grandparent-000")
        cloned = await clone_snapshot(source, "new-exec", persistence)

        assert cloned.parent_execution_id == "source-exec-001"


class TestCloneDropsPendingLaunches:

    @pytest.mark.asyncio
    async def test_pending_launches_dropped(self):
        persistence = MemoryBackend()
        source = _make_snapshot(
            pending_launches=[{"machine": "child", "id": "child-001"}],
        )
        cloned = await clone_snapshot(source, "new-exec", persistence)

        assert cloned.pending_launches is None

    @pytest.mark.asyncio
    async def test_source_pending_launches_unchanged(self):
        persistence = MemoryBackend()
        source = _make_snapshot(
            pending_launches=[{"machine": "child", "id": "child-001"}],
        )
        await clone_snapshot(source, "new-exec", persistence)

        assert source.pending_launches == [{"machine": "child", "id": "child-001"}]


class TestClonePreservesState:

    @pytest.mark.asyncio
    async def test_current_state_preserved(self):
        persistence = MemoryBackend()
        source = _make_snapshot(current_state="processing")
        cloned = await clone_snapshot(source, "new-exec", persistence)

        assert cloned.current_state == "processing"

    @pytest.mark.asyncio
    async def test_context_preserved(self):
        persistence = MemoryBackend()
        ctx = {"score": 42, "nested": {"a": 1}, "items": [1, 2]}
        source = _make_snapshot(context=ctx)
        cloned = await clone_snapshot(source, "new-exec", persistence)

        assert cloned.context == ctx

    @pytest.mark.asyncio
    async def test_step_preserved(self):
        persistence = MemoryBackend()
        source = _make_snapshot(step=17)
        cloned = await clone_snapshot(source, "new-exec", persistence)

        assert cloned.step == 17

    @pytest.mark.asyncio
    async def test_tool_loop_state_preserved(self):
        persistence = MemoryBackend()
        tls = {"chain": ["x"], "turns": 3, "tool_calls_count": 7, "loop_cost": 0.02}
        source = _make_snapshot(tool_loop_state=tls)
        cloned = await clone_snapshot(source, "new-exec", persistence)

        assert cloned.tool_loop_state == tls

    @pytest.mark.asyncio
    async def test_waiting_channel_preserved(self):
        persistence = MemoryBackend()
        source = _make_snapshot(waiting_channel="approval/task-42")
        cloned = await clone_snapshot(source, "new-exec", persistence)

        assert cloned.waiting_channel == "approval/task-42"

    @pytest.mark.asyncio
    async def test_event_preserved(self):
        persistence = MemoryBackend()
        source = _make_snapshot(event="state_exit")
        cloned = await clone_snapshot(source, "new-exec", persistence)

        assert cloned.event == "state_exit"

    @pytest.mark.asyncio
    async def test_output_preserved(self):
        persistence = MemoryBackend()
        source = _make_snapshot(output={"result": "done"})
        cloned = await clone_snapshot(source, "new-exec", persistence)

        assert cloned.output == {"result": "done"}

    @pytest.mark.asyncio
    async def test_totals_preserved(self):
        persistence = MemoryBackend()
        source = _make_snapshot(total_api_calls=10, total_cost=1.23)
        cloned = await clone_snapshot(source, "new-exec", persistence)

        assert cloned.total_api_calls == 10
        assert cloned.total_cost == 1.23

    @pytest.mark.asyncio
    async def test_machine_name_preserved(self):
        persistence = MemoryBackend()
        source = _make_snapshot(machine_name="my-pipeline")
        cloned = await clone_snapshot(source, "new-exec", persistence)

        assert cloned.machine_name == "my-pipeline"

    @pytest.mark.asyncio
    async def test_spec_version_preserved(self):
        persistence = MemoryBackend()
        source = _make_snapshot(spec_version="2.0.0")
        cloned = await clone_snapshot(source, "new-exec", persistence)

        assert cloned.spec_version == "2.0.0"


class TestClonePersisted:

    @pytest.mark.asyncio
    async def test_loadable_via_checkpoint_manager(self):
        persistence = MemoryBackend()
        source = _make_snapshot(context={"key": "value"}, current_state="middle")
        new_id = "clone-loadable-001"
        await clone_snapshot(source, new_id, persistence)

        mgr = CheckpointManager(persistence, new_id)
        loaded = await mgr.load_latest()

        assert loaded is not None
        assert loaded.execution_id == new_id
        assert loaded.context == {"key": "value"}
        assert loaded.current_state == "middle"
        assert loaded.parent_execution_id == "source-exec-001"
        assert loaded.pending_launches is None


# ---------------------------------------------------------------------------
# Integration test — self-differentiating clone
# ---------------------------------------------------------------------------

class TestSelfDifferentiatingClone:

    @pytest.mark.asyncio
    async def test_parent_and_clone_take_different_branches(self):
        """
        Run a machine to a guard state that captures execution_id into
        context.source_id. Snapshot at that point. Clone the snapshot
        with a new ID. Resume both. The parent's context.machine.execution_id
        matches source_id → takes 'parent_branch'. The clone's doesn't →
        takes 'clone_branch'.
        """
        persistence = MemoryBackend()

        # Hook: at the capture state (before wait), save execution_id
        class CaptureSourceIdHook(MachineHooks):
            def on_state_enter(self, state_name, context):
                if state_name == "capture":
                    context["source_id"] = context["machine"]["execution_id"]
                return context

        config = {
            "spec": "flatmachine",
            "spec_version": "2.0.0",
            "data": {
                "name": "clone-test",
                "context": {},
                "agents": {},
                "states": {
                    "start": {
                        "type": "initial",
                        "transitions": [{"to": "capture"}],
                    },
                    "capture": {
                        "transitions": [{"to": "guard"}],
                    },
                    "guard": {
                        "wait_for": "clone/signal",
                        "transitions": [
                            {
                                "condition": "context.machine.execution_id == context.source_id",
                                "to": "parent_branch",
                            },
                            {"to": "clone_branch"},
                        ],
                    },
                    "parent_branch": {
                        "type": "final",
                        "output": {"branch": "parent"},
                    },
                    "clone_branch": {
                        "type": "final",
                        "output": {"branch": "clone"},
                    },
                },
            },
        }

        from flatmachines.signals import MemorySignalBackend
        signal_backend = MemorySignalBackend()

        # Run the source machine until it waits at the guard state
        source_machine = _machine_with_state_hooks(
            config,
            CaptureSourceIdHook(),
            persistence=persistence,
            signal_backend=signal_backend,
        )
        source_id = source_machine.execution_id
        result1 = await source_machine.execute(input={})
        assert result1.get("_waiting") is True

        # Load the waiting snapshot and clone it
        source_mgr = CheckpointManager(persistence, source_id)
        snapshot = await source_mgr.load_latest()
        clone_id = str(uuid.uuid4())
        await clone_snapshot(snapshot, clone_id, persistence)

        # Send signal so both can resume (consume is destructive, need one each)
        await signal_backend.send("clone/signal", {"go": True})
        await signal_backend.send("clone/signal", {"go": True})

        # Resume parent — should take parent_branch
        parent_machine = _machine_with_state_hooks(
            config,
            CaptureSourceIdHook(),
            persistence=persistence,
            signal_backend=signal_backend,
        )
        parent_result = await parent_machine.execute(resume_from=source_id)
        assert parent_result == {"branch": "parent"}

        # Resume clone — should take clone_branch
        clone_machine = _machine_with_state_hooks(
            config,
            CaptureSourceIdHook(),
            persistence=persistence,
            signal_backend=signal_backend,
        )
        clone_result = await clone_machine.execute(resume_from=clone_id)
        assert clone_result == {"branch": "clone"}

"""
Integration tests for wait_for lifecycle: pause → signal → resume → complete.

Tests the full flow across process boundaries (simulated via separate
FlatMachine instances with shared persistence + signal backends).
"""

import os
import shutil
import pytest

from flatmachines import (
    FlatMachine,
    MachineHooks,
    MemoryBackend,
    LocalFileBackend,
    SQLiteCheckpointBackend,
    CheckpointManager,
    SignalDispatcher,
    HooksRegistry,
)
from flatmachines.signals import MemorySignalBackend


# ---------------------------------------------------------------------------
# Hooks
# ---------------------------------------------------------------------------

class ApprovalHooks(MachineHooks):
    """Hooks for an approval-gated workflow."""

    def on_action(self, state_name, action_name, context):
        if action_name == "prepare":
            context["prepared"] = True
            context["task_id"] = context.get("task_id", "unknown")
        elif action_name == "finalize":
            context["finalized"] = True
            # Jinja renders bools to strings: True → "True", False → "False"
            context["final_status"] = (
                "approved" if context.get("approved") == "True" else "rejected"
            )
        return context


def _machine_with_approval_hooks(config, hooks, **kwargs):
    cfg = {**config, "data": {**config["data"], "states": {}}}
    for name, state in config["data"]["states"].items():
        new_state = dict(state)
        if "action" in new_state:
            new_state["hooks"] = "approval-hooks"
        cfg["data"]["states"][name] = new_state
    registry = HooksRegistry()
    registry.register("approval-hooks", lambda: hooks)
    return FlatMachine(config_dict=cfg, hooks_registry=registry, **kwargs)


def approval_config():
    """Machine: prepare → wait for approval → finalize."""
    return {
        "spec": "flatmachine",
        "spec_version": "1.1.1",
        "data": {
            "name": "approval-workflow",
            "context": {
                "task_id": "input.task_id",
                "prepared": False,
                "approved": None,
                "reviewer": None,
                "finalized": False,
                "final_status": None,
            },
            "states": {
                "start": {
                    "type": "initial",
                    "transitions": [{"to": "prepare"}],
                },
                "prepare": {
                    "action": "prepare",
                    "transitions": [{"to": "wait_for_approval"}],
                },
                "wait_for_approval": {
                    "wait_for": "approval/{{ context.task_id }}",
                    "timeout": 86400,
                    "output_to_context": {
                        "approved": "{{ output.approved }}",
                        "reviewer": "{{ output.reviewer }}",
                    },
                    "transitions": [
                        {"condition": "context.approved == 'True'", "to": "finalize"},
                        {"to": "rejected"},
                    ],
                },
                "finalize": {
                    "action": "finalize",
                    "transitions": [{"to": "done"}],
                },
                "rejected": {
                    "action": "finalize",
                    "transitions": [{"to": "done"}],
                },
                "done": {
                    "type": "final",
                    "output": {
                        "task_id": "context.task_id",
                        "final_status": "context.final_status",
                        "reviewer": "context.reviewer",
                    },
                },
            },
        },
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def cleanup():
    for d in [".checkpoints", ".locks"]:
        if os.path.exists(d):
            shutil.rmtree(d)
    yield
    for d in [".checkpoints", ".locks"]:
        if os.path.exists(d):
            shutil.rmtree(d)


@pytest.fixture(params=["memory", "local", "sqlite"])
def persistence(request, tmp_path):
    if request.param == "memory":
        return MemoryBackend()
    elif request.param == "local":
        return LocalFileBackend()
    return SQLiteCheckpointBackend(db_path=str(tmp_path / "test.sqlite"))


# ---------------------------------------------------------------------------
# Full lifecycle: pause → signal → resume → complete
# ---------------------------------------------------------------------------

class TestApprovalLifecycle:
    """End-to-end approval workflow across all persistence backends."""

    @pytest.mark.asyncio
    async def test_approve(self, persistence):
        signal_backend = MemorySignalBackend()
        hooks = ApprovalHooks()

        m1 = _machine_with_approval_hooks(
            approval_config(),
            hooks,
            persistence=persistence,
            signal_backend=signal_backend,
        )
        result1 = await m1.execute(input={"task_id": "PR-42"})

        assert result1["_waiting"] is True
        assert result1["_channel"] == "approval/PR-42"
        eid = m1.execution_id

        mgr = CheckpointManager(persistence, eid)
        snapshot = await mgr.load_latest()
        assert snapshot.waiting_channel == "approval/PR-42"
        assert snapshot.context["prepared"] is True

        await signal_backend.send(
            "approval/PR-42",
            {"approved": True, "reviewer": "alice"},
        )

        m2 = _machine_with_approval_hooks(
            approval_config(),
            ApprovalHooks(),
            persistence=persistence,
            signal_backend=signal_backend,
        )
        result2 = await m2.execute(resume_from=eid)

        assert result2["task_id"] == "PR-42"
        assert result2["final_status"] == "approved"
        assert result2["reviewer"] == "alice"

    @pytest.mark.asyncio
    async def test_reject(self, persistence):
        signal_backend = MemorySignalBackend()

        m1 = _machine_with_approval_hooks(
            approval_config(),
            ApprovalHooks(),
            persistence=persistence,
            signal_backend=signal_backend,
        )
        result1 = await m1.execute(input={"task_id": "PR-99"})
        eid = m1.execution_id

        await signal_backend.send(
            "approval/PR-99",
            {"approved": False, "reviewer": "bob"},
        )

        m2 = _machine_with_approval_hooks(
            approval_config(),
            ApprovalHooks(),
            persistence=persistence,
            signal_backend=signal_backend,
        )
        result2 = await m2.execute(resume_from=eid)

        assert result2["final_status"] == "rejected"
        assert result2["reviewer"] == "bob"


# ---------------------------------------------------------------------------
# Dispatcher-mediated resume
# ---------------------------------------------------------------------------

class TestDispatcherResume:
    """Test the full dispatcher flow: signal → find waiters → resume."""

    @pytest.mark.asyncio
    async def test_dispatcher_finds_and_resumes(self, persistence):
        signal_backend = MemorySignalBackend()

        m1 = _machine_with_approval_hooks(
            approval_config(),
            ApprovalHooks(),
            persistence=persistence,
            signal_backend=signal_backend,
        )
        await m1.execute(input={"task_id": "D-1"})
        eid = m1.execution_id

        await signal_backend.send("approval/D-1", {"approved": True, "reviewer": "eve"})

        results = {}

        async def resume_fn(execution_id, signal_data):
            m = _machine_with_approval_hooks(
                approval_config(),
                ApprovalHooks(),
                persistence=persistence,
                signal_backend=signal_backend,
            )
            results[execution_id] = await m.execute(resume_from=execution_id)

        dispatcher = SignalDispatcher(signal_backend, persistence, resume_fn)
        resumed = await dispatcher.dispatch("approval/D-1")

        assert resumed == [eid]
        assert results[eid]["final_status"] == "approved"
        assert results[eid]["reviewer"] == "eve"


# ---------------------------------------------------------------------------
# Broadcast: multiple machines on same channel
# ---------------------------------------------------------------------------

class TestBroadcastSignal:
    """Multiple machines waiting on the same channel (quota pattern)."""

    @pytest.mark.asyncio
    async def test_broadcast_wakes_all(self, persistence):
        signal_backend = MemorySignalBackend()

        def quota_config():
            return {
                "spec": "flatmachine",
                "spec_version": "1.1.1",
                "data": {
                    "name": "quota-consumer",
                    "context": {"quota_token": None},
                    "states": {
                        "start": {
                            "type": "initial",
                            "transitions": [{"to": "wait_quota"}],
                        },
                        "wait_quota": {
                            "wait_for": "quota/openai",
                            "output_to_context": {
                                "quota_token": "{{ output.token }}",
                            },
                            "transitions": [{"to": "done"}],
                        },
                        "done": {
                            "type": "final",
                            "output": {"token": "context.quota_token"},
                        },
                    },
                },
            }

        eids = []
        for _ in range(3):
            m = FlatMachine(
                config_dict=quota_config(),
                persistence=persistence,
                signal_backend=signal_backend,
            )
            result = await m.execute(input={})
            assert result["_waiting"] is True
            eids.append(m.execution_id)

        waiting = await persistence.list_execution_ids(waiting_channel="quota/openai")
        assert set(waiting) == set(eids)

        await signal_backend.send("quota/openai", {"token": "tk-abc"})

        resumed_ids = []

        async def resume_fn(execution_id, signal_data):
            resumed_ids.append(execution_id)

        dispatcher = SignalDispatcher(signal_backend, persistence, resume_fn)
        result = await dispatcher.dispatch("quota/openai")

        assert set(result) == set(eids)
        assert len(resumed_ids) == 3


# ---------------------------------------------------------------------------
# Crash during wait_for → resume still works
# ---------------------------------------------------------------------------

class TestCrashRecovery:
    """Simulate process crash while machine is waiting."""

    @pytest.mark.asyncio
    async def test_crash_after_checkpoint_resume_works(self, persistence):
        signal_backend = MemorySignalBackend()

        m1 = _machine_with_approval_hooks(
            approval_config(),
            ApprovalHooks(),
            persistence=persistence,
            signal_backend=signal_backend,
        )
        result1 = await m1.execute(input={"task_id": "crash-1"})
        eid = m1.execution_id
        assert result1["_waiting"] is True

        del m1

        await signal_backend.send(
            "approval/crash-1",
            {"approved": True, "reviewer": "recovery"},
        )

        m2 = _machine_with_approval_hooks(
            approval_config(),
            ApprovalHooks(),
            persistence=persistence,
            signal_backend=signal_backend,
        )
        result2 = await m2.execute(resume_from=eid)

        assert result2["final_status"] == "approved"
        assert result2["reviewer"] == "recovery"


# ---------------------------------------------------------------------------
# Signal pre-loaded (no pause needed)
# ---------------------------------------------------------------------------

class TestPreloadedSignal:
    """Signal sent before machine reaches wait_for — no pause."""

    @pytest.mark.asyncio
    async def test_preloaded_signal_skips_pause(self, persistence):
        signal_backend = MemorySignalBackend()

        await signal_backend.send(
            "approval/fast-1",
            {"approved": True, "reviewer": "eager"},
        )

        m = _machine_with_approval_hooks(
            approval_config(),
            ApprovalHooks(),
            persistence=persistence,
            signal_backend=signal_backend,
        )
        result = await m.execute(input={"task_id": "fast-1"})

        assert "_waiting" not in result or result.get("_waiting") is not True
        assert result["final_status"] == "approved"
        assert result["reviewer"] == "eager"

"""
Integration tests for signal dispatch runtime: send_and_notify + dispatch_signals.

Tests the full producer → dispatcher → resume flow across persistence backends,
including the CLI entrypoint's programmatic API (run_once, run_listen).
"""

import asyncio
import os
import shutil
import tempfile
import pytest

from flatmachines import (
    FlatMachine,
    MachineHooks,
    MemoryBackend,
    LocalFileBackend,
    SQLiteCheckpointBackend,
    SignalDispatcher,
    send_and_notify,
)
from flatmachines.signals import (
    MemorySignalBackend,
    SQLiteSignalBackend,
    NoOpTrigger,
    FileTrigger,
    SocketTrigger,
)
from flatmachines.dispatch_signals import run_once, run_listen


# ---------------------------------------------------------------------------
# Configs
# ---------------------------------------------------------------------------

def approval_config(channel="approval/{{ context.task_id }}"):
    return {
        "spec": "flatmachine",
        "spec_version": "1.1.1",
        "data": {
            "name": "dispatch-test",
            "context": {
                "task_id": "input.task_id",
                "approved": None,
            },
            "states": {
                "start": {
                    "type": "initial",
                    "transitions": [{"to": "wait"}],
                },
                "wait": {
                    "wait_for": channel,
                    "output_to_context": {
                        "approved": "{{ output.approved }}",
                    },
                    "transitions": [
                        {"condition": "context.approved == 'True'", "to": "yes"},
                        {"to": "no"},
                    ],
                },
                "yes": {
                    "type": "final",
                    "output": {"status": "approved", "task_id": "context.task_id"},
                },
                "no": {
                    "type": "final",
                    "output": {"status": "rejected", "task_id": "context.task_id"},
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
    return SQLiteCheckpointBackend(db_path=str(tmp_path / "ckpt.sqlite"))


@pytest.fixture(params=["memory", "sqlite"])
def signal_backend(request, tmp_path):
    if request.param == "memory":
        return MemorySignalBackend()
    return SQLiteSignalBackend(db_path=str(tmp_path / "signals.sqlite"))


# ---------------------------------------------------------------------------
# send_and_notify → dispatcher.dispatch_all → resume
# ---------------------------------------------------------------------------

class TestSendAndNotifyLifecycle:
    """Full lifecycle using the composite send_and_notify helper."""

    @pytest.mark.asyncio
    async def test_send_notify_dispatch_resume(self, persistence, signal_backend):
        """Park machine → send_and_notify → run_once → machine completes."""
        trigger = NoOpTrigger()

        # Park
        m1 = FlatMachine(
            config_dict=approval_config(),
            persistence=persistence,
            signal_backend=signal_backend,
        )
        result1 = await m1.execute(input={"task_id": "sn-1"})
        assert result1["_waiting"] is True
        eid = m1.execution_id

        # Send via composite helper
        sig_id = await send_and_notify(
            signal_backend, trigger, "approval/sn-1", {"approved": True}
        )
        assert isinstance(sig_id, str)

        # Dispatch via run_once
        results = {}

        async def resume_fn(execution_id, signal_data):
            m = FlatMachine(
                config_dict=approval_config(),
                persistence=persistence,
                signal_backend=signal_backend,
            )
            results[execution_id] = await m.execute(resume_from=execution_id)

        dispatched = await run_once(signal_backend, persistence, resume_fn=resume_fn)

        assert eid in dispatched.get("approval/sn-1", [])
        assert results[eid]["status"] == "approved"

    @pytest.mark.asyncio
    async def test_file_trigger_touched_on_send(self, persistence, signal_backend, tmp_path):
        """send_and_notify with FileTrigger creates the trigger file."""
        trigger = FileTrigger(base_path=str(tmp_path / "triggers"))

        m1 = FlatMachine(
            config_dict=approval_config(),
            persistence=persistence,
            signal_backend=signal_backend,
        )
        await m1.execute(input={"task_id": "ft-1"})

        await send_and_notify(
            signal_backend, trigger, "approval/ft-1", {"approved": True}
        )

        assert (tmp_path / "triggers" / "trigger").exists()

    @pytest.mark.asyncio
    async def test_signal_durable_when_trigger_fails(self, persistence, signal_backend):
        """Signal persists and dispatches even when trigger raises."""

        class BrokenTrigger:
            async def notify(self, channel):
                raise OSError("trigger is broken")

        m1 = FlatMachine(
            config_dict=approval_config(),
            persistence=persistence,
            signal_backend=signal_backend,
        )
        result1 = await m1.execute(input={"task_id": "bt-1"})
        eid = m1.execution_id

        # send_and_notify should not raise
        sig_id = await send_and_notify(
            signal_backend, BrokenTrigger(), "approval/bt-1", {"approved": True}
        )
        assert isinstance(sig_id, str)

        # Signal is still durable — dispatch works
        results = {}

        async def resume_fn(execution_id, signal_data):
            m = FlatMachine(
                config_dict=approval_config(),
                persistence=persistence,
                signal_backend=signal_backend,
            )
            results[execution_id] = await m.execute(resume_from=execution_id)

        await run_once(signal_backend, persistence, resume_fn=resume_fn)
        assert results[eid]["status"] == "approved"


# ---------------------------------------------------------------------------
# run_once: multiple machines, multiple channels
# ---------------------------------------------------------------------------

class TestRunOnceMultiChannel:
    """run_once drains all pending channels in one pass."""

    @pytest.mark.asyncio
    async def test_drains_all_channels(self, persistence, signal_backend):
        trigger = NoOpTrigger()

        eids = {}
        for task_id in ["mc-1", "mc-2", "mc-3"]:
            m = FlatMachine(
                config_dict=approval_config(),
                persistence=persistence,
                signal_backend=signal_backend,
            )
            await m.execute(input={"task_id": task_id})
            eids[task_id] = m.execution_id

        # Send signals on all three channels
        for task_id in ["mc-1", "mc-2", "mc-3"]:
            await send_and_notify(
                signal_backend, trigger,
                f"approval/{task_id}", {"approved": True},
            )

        results = {}

        async def resume_fn(execution_id, signal_data):
            m = FlatMachine(
                config_dict=approval_config(),
                persistence=persistence,
                signal_backend=signal_backend,
            )
            results[execution_id] = await m.execute(resume_from=execution_id)

        dispatched = await run_once(signal_backend, persistence, resume_fn=resume_fn)

        assert len(dispatched) == 3
        for task_id, eid in eids.items():
            assert results[eid]["status"] == "approved"
            assert results[eid]["task_id"] == task_id


# ---------------------------------------------------------------------------
# run_listen: socket trigger → dispatch
# ---------------------------------------------------------------------------

class TestRunListenWithSocketTrigger:
    """End-to-end: send_and_notify with SocketTrigger → run_listen dispatches."""

    @pytest.mark.asyncio
    async def test_socket_trigger_wakes_listener(self):
        tmp_dir = tempfile.mkdtemp(prefix="fm_")
        sock_path = os.path.join(tmp_dir, "d.sock")

        persistence = MemoryBackend()
        signal_backend = MemorySignalBackend()

        # Park a machine
        m = FlatMachine(
            config_dict=approval_config("test/sock"),
            persistence=persistence,
            signal_backend=signal_backend,
        )
        await m.execute(input={"task_id": "sk-1"})
        eid = m.execution_id

        resumed = []

        async def resume_fn(execution_id, signal_data):
            resumed.append(execution_id)

        stop = asyncio.Event()

        # Start listener
        listen_task = asyncio.create_task(
            run_listen(
                signal_backend, persistence,
                socket_path=sock_path,
                resume_fn=resume_fn,
                stop_event=stop,
            )
        )

        # Wait for socket to bind
        for _ in range(50):
            if os.path.exists(sock_path):
                break
            await asyncio.sleep(0.02)

        # Producer: send signal + socket trigger
        trigger = SocketTrigger(socket_path=sock_path)
        await send_and_notify(signal_backend, trigger, "test/sock", {"approved": True})

        # Give listener time to dispatch
        await asyncio.sleep(0.3)

        stop.set()
        try:
            await asyncio.wait_for(listen_task, timeout=3.0)
        except asyncio.TimeoutError:
            listen_task.cancel()

        assert eid in resumed

        if os.path.exists(sock_path):
            os.unlink(sock_path)
        os.rmdir(tmp_dir)

    @pytest.mark.asyncio
    async def test_listen_drains_pending_then_accepts_triggers(self):
        """Pending signals dispatched on startup, then live triggers work too."""
        tmp_dir = tempfile.mkdtemp(prefix="fm_")
        sock_path = os.path.join(tmp_dir, "d.sock")

        persistence = MemoryBackend()
        signal_backend = MemorySignalBackend()

        # Park two machines
        m1 = FlatMachine(
            config_dict=approval_config("pre/ch"),
            persistence=persistence,
            signal_backend=signal_backend,
        )
        await m1.execute(input={"task_id": "pre-1"})
        eid_pre = m1.execution_id

        m2 = FlatMachine(
            config_dict=approval_config("live/ch"),
            persistence=persistence,
            signal_backend=signal_backend,
        )
        await m2.execute(input={"task_id": "live-1"})
        eid_live = m2.execution_id

        # Pre-load signal (will be drained on startup)
        await signal_backend.send("pre/ch", {"approved": True})

        resumed = []

        async def resume_fn(execution_id, signal_data):
            resumed.append(execution_id)

        stop = asyncio.Event()

        listen_task = asyncio.create_task(
            run_listen(
                signal_backend, persistence,
                socket_path=sock_path,
                resume_fn=resume_fn,
                stop_event=stop,
            )
        )

        # Wait for socket + drain
        for _ in range(50):
            if os.path.exists(sock_path):
                break
            await asyncio.sleep(0.02)
        await asyncio.sleep(0.2)

        # Pre-loaded signal should already be dispatched
        assert eid_pre in resumed

        # Now send a live trigger
        trigger = SocketTrigger(socket_path=sock_path)
        await send_and_notify(signal_backend, trigger, "live/ch", {"approved": True})
        await asyncio.sleep(0.3)

        assert eid_live in resumed

        stop.set()
        try:
            await asyncio.wait_for(listen_task, timeout=3.0)
        except asyncio.TimeoutError:
            listen_task.cancel()

        if os.path.exists(sock_path):
            os.unlink(sock_path)
        os.rmdir(tmp_dir)


# ---------------------------------------------------------------------------
# SQLite signal + SQLite persistence (shared db)
# ---------------------------------------------------------------------------

class TestSQLiteSharedDB:
    """Signal and persistence backends sharing the same SQLite database."""

    @pytest.mark.asyncio
    async def test_shared_sqlite_lifecycle(self, tmp_path):
        db_path = str(tmp_path / "shared.sqlite")
        signal_backend = SQLiteSignalBackend(db_path=db_path)
        persistence = SQLiteCheckpointBackend(db_path=db_path)
        trigger = NoOpTrigger()

        # Park
        m1 = FlatMachine(
            config_dict=approval_config(),
            persistence=persistence,
            signal_backend=signal_backend,
        )
        result1 = await m1.execute(input={"task_id": "shared-1"})
        assert result1["_waiting"] is True
        eid = m1.execution_id

        # Send
        await send_and_notify(signal_backend, trigger, "approval/shared-1", {"approved": True})

        # Dispatch
        results = {}

        async def resume_fn(execution_id, signal_data):
            m = FlatMachine(
                config_dict=approval_config(),
                persistence=persistence,
                signal_backend=signal_backend,
            )
            results[execution_id] = await m.execute(resume_from=execution_id)

        dispatched = await run_once(signal_backend, persistence, resume_fn=resume_fn)

        assert eid in dispatched.get("approval/shared-1", [])
        assert results[eid]["status"] == "approved"

    @pytest.mark.asyncio
    async def test_separate_sqlite_dbs(self, tmp_path):
        """Signal and persistence in separate SQLite files."""
        signal_backend = SQLiteSignalBackend(db_path=str(tmp_path / "sigs.sqlite"))
        persistence = SQLiteCheckpointBackend(db_path=str(tmp_path / "ckpts.sqlite"))
        trigger = NoOpTrigger()

        m1 = FlatMachine(
            config_dict=approval_config(),
            persistence=persistence,
            signal_backend=signal_backend,
        )
        await m1.execute(input={"task_id": "sep-1"})
        eid = m1.execution_id

        await send_and_notify(signal_backend, trigger, "approval/sep-1", {"approved": False})

        results = {}

        async def resume_fn(execution_id, signal_data):
            m = FlatMachine(
                config_dict=approval_config(),
                persistence=persistence,
                signal_backend=signal_backend,
            )
            results[execution_id] = await m.execute(resume_from=execution_id)

        await run_once(signal_backend, persistence, resume_fn=resume_fn)

        assert results[eid]["status"] == "rejected"

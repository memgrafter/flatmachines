"""
Integration tests for SocketTrigger + SignalDispatcher end-to-end.

Tests the UDS datagram flow: send signal → SocketTrigger.notify() →
dispatcher.listen() receives → dispatch() resumes machine.
"""

import asyncio
import os
import socket
import tempfile
import pytest

from flatmachines import (
    FlatMachine,
    MemoryBackend,
    SignalDispatcher,
)
from flatmachines.signals import MemorySignalBackend, SocketTrigger


def simple_wait_config(channel="test/ch"):
    return {
        "spec": "flatmachine",
        "spec_version": "1.1.1",
        "data": {
            "name": "socket-test",
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


class TestSocketTriggerIntegration:
    """End-to-end: SocketTrigger sends datagram, dispatcher receives and dispatches."""

    @pytest.mark.asyncio
    async def test_trigger_notify_reaches_listener(self):
        """SocketTrigger.notify() → UDS → dispatcher receives channel name."""
        # Short path for macOS AF_UNIX limit
        tmp_dir = tempfile.mkdtemp(prefix="fm_")
        sock_path = os.path.join(tmp_dir, "t.sock")

        # Bind listener (simulating dispatcher)
        server = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        server.bind(sock_path)
        server.setblocking(False)

        try:
            trigger = SocketTrigger(socket_path=sock_path)

            # Send multiple channel notifications
            await trigger.notify("approval/task-1")
            await trigger.notify("quota/openai")

            # Verify both received
            data1 = server.recv(4096)
            data2 = server.recv(4096)

            received = {data1.decode("utf-8"), data2.decode("utf-8")}
            assert received == {"approval/task-1", "quota/openai"}
        finally:
            server.close()
            os.unlink(sock_path)
            os.rmdir(tmp_dir)

    @pytest.mark.asyncio
    async def test_signal_send_with_trigger(self):
        """Full flow: send signal + trigger → dispatcher dispatch."""
        persistence = MemoryBackend()
        signal_backend = MemorySignalBackend()

        # Park a machine
        m = FlatMachine(
            config_dict=simple_wait_config("test/ch"),
            persistence=persistence,
            signal_backend=signal_backend,
        )
        result = await m.execute(input={})
        assert result["_waiting"] is True
        eid = m.execution_id

        # Simulate what a real sender does: write signal + fire trigger
        await signal_backend.send("test/ch", {"v": "triggered"})

        # Dispatcher processes (in real deployment, trigger wakes dispatcher)
        resumed = []

        async def resume_fn(execution_id, signal_data):
            m2 = FlatMachine(
                config_dict=simple_wait_config("test/ch"),
                persistence=persistence,
                signal_backend=signal_backend,
            )
            result = await m2.execute(resume_from=execution_id)
            resumed.append(result)

        dispatcher = SignalDispatcher(signal_backend, persistence, resume_fn)
        await dispatcher.dispatch("test/ch")

        assert len(resumed) == 1
        assert resumed[0].get("val") == "triggered"

    @pytest.mark.asyncio
    async def test_trigger_silent_when_no_listener(self):
        """SocketTrigger silently ignores when no dispatcher is running."""
        trigger = SocketTrigger(socket_path="/tmp/flatmachines_nonexistent_test.sock")

        # Should not raise
        await trigger.notify("any/channel")
        await trigger.notify("another/channel")


class TestDispatcherListenLoop:
    """Test the dispatcher's listen() method with real UDS."""

    @pytest.mark.asyncio
    async def test_listen_dispatches_on_trigger(self):
        """dispatcher.listen() receives datagram and calls dispatch()."""
        tmp_dir = tempfile.mkdtemp(prefix="fm_")
        sock_path = os.path.join(tmp_dir, "d.sock")

        persistence = MemoryBackend()
        signal_backend = MemorySignalBackend()

        # Park a machine
        m = FlatMachine(
            config_dict=simple_wait_config("wake/me"),
            persistence=persistence,
            signal_backend=signal_backend,
        )
        await m.execute(input={})
        eid = m.execution_id

        # Pre-load signal
        await signal_backend.send("wake/me", {"v": "awake"})

        resumed = []

        async def resume_fn(execution_id, signal_data):
            resumed.append(execution_id)

        dispatcher = SignalDispatcher(signal_backend, persistence, resume_fn)

        stop = asyncio.Event()

        # Start listener in background
        listen_task = asyncio.create_task(
            dispatcher.listen(socket_path=sock_path, stop_event=stop)
        )

        # Wait for socket to be ready
        for _ in range(50):
            if os.path.exists(sock_path):
                break
            await asyncio.sleep(0.02)

        # Send trigger
        trigger = SocketTrigger(socket_path=sock_path)
        await trigger.notify("wake/me")

        # Give dispatcher time to process
        await asyncio.sleep(0.2)

        stop.set()
        try:
            await asyncio.wait_for(listen_task, timeout=3.0)
        except asyncio.TimeoutError:
            listen_task.cancel()

        assert eid in resumed

        # Cleanup
        if os.path.exists(sock_path):
            os.unlink(sock_path)
        os.rmdir(tmp_dir)

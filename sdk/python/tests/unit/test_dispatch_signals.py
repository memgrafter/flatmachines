"""
Unit tests for the dispatch_signals runtime entrypoint.

Tests the programmatic API (run_once, run_listen) and CLI argument parsing.
"""

import asyncio
import pytest

from flatmachines.signals import MemorySignalBackend
from flatmachines.persistence import MemoryBackend, CheckpointManager, MachineSnapshot
from flatmachines.dispatch_signals import run_once, run_listen, _build_parser, _async_main


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _park_machine(
    persistence: MemoryBackend,
    execution_id: str,
    waiting_channel: str,
    machine_name: str = "test-machine",
) -> None:
    """Create a checkpoint that looks like a machine waiting on a channel."""
    snapshot = MachineSnapshot(
        execution_id=execution_id,
        machine_name=machine_name,
        spec_version="2.0.0",
        current_state="wait_state",
        context={"task_id": "t-1"},
        step=1,
        event="waiting",
        waiting_channel=waiting_channel,
    )
    mgr = CheckpointManager(persistence, execution_id)
    await mgr.save_checkpoint(snapshot)


# ---------------------------------------------------------------------------
# run_once
# ---------------------------------------------------------------------------

class TestRunOnce:

    @pytest.mark.asyncio
    async def test_no_signals_returns_empty(self):
        signals = MemorySignalBackend()
        persistence = MemoryBackend()

        results = await run_once(signals, persistence)
        assert results == {}

    @pytest.mark.asyncio
    async def test_dispatches_pending_signal(self):
        signals = MemorySignalBackend()
        persistence = MemoryBackend()

        # Park a machine waiting on "approval/t-1"
        await _park_machine(persistence, "exec-001", "approval/t-1")

        # Send a signal
        await signals.send("approval/t-1", {"approved": True})

        # Track resumes
        resumed = []

        async def track_resume(eid, data):
            resumed.append((eid, data))

        results = await run_once(signals, persistence, resume_fn=track_resume)

        assert "approval/t-1" in results
        assert "exec-001" in results["approval/t-1"]
        assert len(resumed) == 1
        assert resumed[0][0] == "exec-001"

    @pytest.mark.asyncio
    async def test_dispatches_multiple_channels(self):
        signals = MemorySignalBackend()
        persistence = MemoryBackend()

        await _park_machine(persistence, "exec-a", "channel/a")
        await _park_machine(persistence, "exec-b", "channel/b")

        await signals.send("channel/a", {"from": "a"})
        await signals.send("channel/b", {"from": "b"})

        resumed = []

        async def track_resume(eid, data):
            resumed.append(eid)

        results = await run_once(signals, persistence, resume_fn=track_resume)

        assert len(results) == 2
        assert set(resumed) == {"exec-a", "exec-b"}

    @pytest.mark.asyncio
    async def test_signal_with_no_waiter_requeued(self):
        """Signal on a channel with no waiting machine is re-queued."""
        signals = MemorySignalBackend()
        persistence = MemoryBackend()

        await signals.send("orphan/channel", {"lonely": True})

        results = await run_once(signals, persistence)

        # No machines resumed
        assert results == {}

        # Signal was re-queued by the dispatcher
        sig = await signals.consume("orphan/channel")
        assert sig is not None
        assert sig.data == {"lonely": True}


# ---------------------------------------------------------------------------
# run_listen
# ---------------------------------------------------------------------------

class TestRunListen:

    @pytest.mark.asyncio
    async def test_drains_pending_before_listen(self):
        """run_listen should dispatch pending signals before entering listen loop."""
        signals = MemorySignalBackend()
        persistence = MemoryBackend()

        await _park_machine(persistence, "exec-pre", "pre/channel")
        await signals.send("pre/channel", {"pre": True})

        resumed = []

        async def track_resume(eid, data):
            resumed.append(eid)

        # Stop immediately after drain
        stop = asyncio.Event()
        stop.set()

        await run_listen(
            signals,
            persistence,
            resume_fn=track_resume,
            stop_event=stop,
        )

        assert "exec-pre" in resumed

    @pytest.mark.asyncio
    async def test_stops_on_event(self):
        """Listen mode exits when stop_event is set."""
        import tempfile
        import os

        signals = MemorySignalBackend()
        persistence = MemoryBackend()

        stop = asyncio.Event()

        # Use a temp dir for a short socket path (macOS 104-char limit)
        tmp_dir = tempfile.mkdtemp(prefix="fm_")
        sock_path = os.path.join(tmp_dir, "t.sock")

        async def stop_soon():
            await asyncio.sleep(0.3)
            stop.set()

        try:
            stop_task = asyncio.create_task(stop_soon())
            await run_listen(
                signals,
                persistence,
                socket_path=sock_path,
                stop_event=stop,
            )
            await stop_task
        finally:
            # Cleanup
            if os.path.exists(sock_path):
                os.unlink(sock_path)
            os.rmdir(tmp_dir)


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------

class TestCLIParsing:

    def test_once_mode(self):
        parser = _build_parser()
        args = parser.parse_args(["--once"])
        assert args.once is True
        assert args.listen is False

    def test_listen_mode(self):
        parser = _build_parser()
        args = parser.parse_args(["--listen"])
        assert args.listen is True
        assert args.once is False

    def test_once_and_listen_mutually_exclusive(self):
        parser = _build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["--once", "--listen"])

    def test_requires_mode(self):
        parser = _build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([])

    def test_defaults(self):
        parser = _build_parser()
        args = parser.parse_args(["--once"])
        assert args.signal_backend == "sqlite"
        assert args.db_path == "flatmachines.sqlite"
        assert args.persistence_backend == "sqlite"
        assert args.socket_path == "/tmp/flatmachines/trigger.sock"

    def test_custom_backends(self):
        parser = _build_parser()
        args = parser.parse_args([
            "--once",
            "--signal-backend", "memory",
            "--persistence-backend", "local",
            "--checkpoints-dir", "/tmp/ckpts",
        ])
        assert args.signal_backend == "memory"
        assert args.persistence_backend == "local"
        assert args.checkpoints_dir == "/tmp/ckpts"

    def test_custom_socket_path(self):
        parser = _build_parser()
        args = parser.parse_args([
            "--listen",
            "--socket-path", "/var/run/fm.sock",
        ])
        assert args.socket_path == "/var/run/fm.sock"

    def test_verbose_and_quiet(self):
        parser = _build_parser()
        args = parser.parse_args(["--once", "-v"])
        assert args.verbose is True

        args = parser.parse_args(["--once", "-q"])
        assert args.quiet is True


class TestCLIRuntime:

    @pytest.mark.asyncio
    async def test_requires_resume_strategy_by_default(self):
        parser = _build_parser()
        args = parser.parse_args([
            "--once",
            "--signal-backend", "memory",
            "--persistence-backend", "memory",
        ])

        exit_code = await _async_main(args)
        assert exit_code == 2

    @pytest.mark.asyncio
    async def test_allow_noop_resume_escape_hatch(self):
        parser = _build_parser()
        args = parser.parse_args([
            "--once",
            "--allow-noop-resume",
            "--signal-backend", "memory",
            "--persistence-backend", "memory",
        ])

        exit_code = await _async_main(args)
        assert exit_code == 0

    @pytest.mark.asyncio
    async def test_config_store_resumer_via_cli(self):
        parser = _build_parser()
        args = parser.parse_args([
            "--once",
            "--resumer", "config-store",
            "--signal-backend", "memory",
            "--persistence-backend", "memory",
        ])

        exit_code = await _async_main(args)
        assert exit_code == 0

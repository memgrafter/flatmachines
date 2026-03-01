"""
Unit tests for SignalBackend and TriggerBackend implementations.

Parametrized over Memory and SQLite signal backends.
"""

import pytest
import os

from flatmachines.signals import (
    Signal,
    SignalBackend,
    TriggerBackend,
    MemorySignalBackend,
    SQLiteSignalBackend,
    NoOpTrigger,
    FileTrigger,
    SocketTrigger,
    create_signal_backend,
    create_trigger_backend,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(params=["memory", "sqlite"])
def signal_backend(request, tmp_path):
    if request.param == "memory":
        return MemorySignalBackend()
    return SQLiteSignalBackend(db_path=str(tmp_path / "test_signals.sqlite"))


# ---------------------------------------------------------------------------
# SignalBackend — send / consume / peek / channels
# ---------------------------------------------------------------------------

class TestSignalSendConsume:

    @pytest.mark.asyncio
    async def test_send_returns_id(self, signal_backend):
        sig_id = await signal_backend.send("ch/1", {"hello": "world"})
        assert isinstance(sig_id, str)
        assert len(sig_id) > 0

    @pytest.mark.asyncio
    async def test_send_and_consume(self, signal_backend):
        await signal_backend.send("ch/1", {"key": "value"})
        sig = await signal_backend.consume("ch/1")
        assert sig is not None
        assert sig.channel == "ch/1"
        assert sig.data == {"key": "value"}
        assert isinstance(sig.id, str)
        assert isinstance(sig.created_at, str)

    @pytest.mark.asyncio
    async def test_consume_empty_returns_none(self, signal_backend):
        assert await signal_backend.consume("nonexistent") is None

    @pytest.mark.asyncio
    async def test_consume_is_atomic(self, signal_backend):
        """Send one signal, consume twice — second should be None."""
        await signal_backend.send("ch/1", {"only": "one"})
        first = await signal_backend.consume("ch/1")
        second = await signal_backend.consume("ch/1")
        assert first is not None
        assert second is None

    @pytest.mark.asyncio
    async def test_fifo_ordering(self, signal_backend):
        """Signals consumed in send order."""
        await signal_backend.send("ch/1", {"seq": 1})
        await signal_backend.send("ch/1", {"seq": 2})
        await signal_backend.send("ch/1", {"seq": 3})

        s1 = await signal_backend.consume("ch/1")
        s2 = await signal_backend.consume("ch/1")
        s3 = await signal_backend.consume("ch/1")

        assert s1.data == {"seq": 1}
        assert s2.data == {"seq": 2}
        assert s3.data == {"seq": 3}
        assert await signal_backend.consume("ch/1") is None

    @pytest.mark.asyncio
    async def test_multiple_channels_independent(self, signal_backend):
        await signal_backend.send("alpha", {"from": "alpha"})
        await signal_backend.send("beta", {"from": "beta"})

        sig_a = await signal_backend.consume("alpha")
        sig_b = await signal_backend.consume("beta")

        assert sig_a.data == {"from": "alpha"}
        assert sig_b.data == {"from": "beta"}

    @pytest.mark.asyncio
    async def test_consume_does_not_affect_other_channels(self, signal_backend):
        await signal_backend.send("keep", {"stay": True})
        await signal_backend.send("take", {"go": True})

        await signal_backend.consume("take")

        sig = await signal_backend.consume("keep")
        assert sig is not None
        assert sig.data == {"stay": True}


class TestSignalPeek:

    @pytest.mark.asyncio
    async def test_peek_returns_signals(self, signal_backend):
        await signal_backend.send("ch/1", {"a": 1})
        await signal_backend.send("ch/1", {"b": 2})

        peeked = await signal_backend.peek("ch/1")
        assert len(peeked) == 2
        assert peeked[0].data == {"a": 1}
        assert peeked[1].data == {"b": 2}

    @pytest.mark.asyncio
    async def test_peek_does_not_consume(self, signal_backend):
        await signal_backend.send("ch/1", {"persist": True})

        await signal_backend.peek("ch/1")
        await signal_backend.peek("ch/1")

        sig = await signal_backend.consume("ch/1")
        assert sig is not None
        assert sig.data == {"persist": True}

    @pytest.mark.asyncio
    async def test_peek_empty_returns_empty_list(self, signal_backend):
        assert await signal_backend.peek("empty") == []


class TestSignalChannels:

    @pytest.mark.asyncio
    async def test_channels_lists_pending(self, signal_backend):
        await signal_backend.send("alpha", {})
        await signal_backend.send("beta", {})

        channels = await signal_backend.channels()
        assert set(channels) == {"alpha", "beta"}

    @pytest.mark.asyncio
    async def test_channels_empty_after_consume(self, signal_backend):
        await signal_backend.send("ch/1", {})
        await signal_backend.consume("ch/1")

        channels = await signal_backend.channels()
        assert "ch/1" not in channels

    @pytest.mark.asyncio
    async def test_channels_empty_when_none(self, signal_backend):
        assert await signal_backend.channels() == []

    @pytest.mark.asyncio
    async def test_channels_sorted(self, signal_backend):
        await signal_backend.send("charlie", {})
        await signal_backend.send("alpha", {})
        await signal_backend.send("bravo", {})

        assert await signal_backend.channels() == ["alpha", "bravo", "charlie"]


class TestSignalDataTypes:

    @pytest.mark.asyncio
    async def test_string_data(self, signal_backend):
        await signal_backend.send("ch", "just a string")
        sig = await signal_backend.consume("ch")
        assert sig.data == "just a string"

    @pytest.mark.asyncio
    async def test_nested_dict_data(self, signal_backend):
        data = {"outer": {"inner": [1, 2, 3]}}
        await signal_backend.send("ch", data)
        sig = await signal_backend.consume("ch")
        assert sig.data == data

    @pytest.mark.asyncio
    async def test_null_data(self, signal_backend):
        await signal_backend.send("ch", None)
        sig = await signal_backend.consume("ch")
        assert sig.data is None

    @pytest.mark.asyncio
    async def test_list_data(self, signal_backend):
        await signal_backend.send("ch", [1, "two", 3.0])
        sig = await signal_backend.consume("ch")
        assert sig.data == [1, "two", 3.0]


# ---------------------------------------------------------------------------
# TriggerBackend implementations
# ---------------------------------------------------------------------------

class TestNoOpTrigger:

    @pytest.mark.asyncio
    async def test_notify_does_not_raise(self):
        trigger = NoOpTrigger()
        await trigger.notify("any/channel")  # should not raise


class TestFileTrigger:

    @pytest.mark.asyncio
    async def test_creates_trigger_file(self, tmp_path):
        trigger = FileTrigger(base_path=str(tmp_path))
        await trigger.notify("some/channel")

        trigger_file = tmp_path / "trigger"
        assert trigger_file.exists()

    @pytest.mark.asyncio
    async def test_idempotent(self, tmp_path):
        trigger = FileTrigger(base_path=str(tmp_path))
        await trigger.notify("ch1")
        await trigger.notify("ch2")
        # Still just one trigger file
        assert (tmp_path / "trigger").exists()


class TestSocketTrigger:

    @pytest.mark.asyncio
    async def test_no_listener_does_not_raise(self, tmp_path):
        """If no dispatcher is listening, silently ignores."""
        trigger = SocketTrigger(socket_path=str(tmp_path / "nonexistent.sock"))
        await trigger.notify("any/channel")  # should not raise

    @pytest.mark.asyncio
    async def test_sends_to_listener(self):
        """SocketTrigger sends channel name as datagram."""
        import socket as sock_mod
        import tempfile

        # Use short path to avoid macOS AF_UNIX 104-char limit
        tmp_dir = tempfile.mkdtemp(prefix="fm_")
        sock_path = os.path.join(tmp_dir, "t.sock")

        server = sock_mod.socket(sock_mod.AF_UNIX, sock_mod.SOCK_DGRAM)
        server.bind(sock_path)
        server.setblocking(False)

        try:
            trigger = SocketTrigger(socket_path=sock_path)
            await trigger.notify("test/channel")

            data = server.recv(4096)
            assert data.decode("utf-8") == "test/channel"
        finally:
            server.close()
            os.unlink(sock_path)
            os.rmdir(tmp_dir)


# ---------------------------------------------------------------------------
# Factory functions
# ---------------------------------------------------------------------------

class TestFactories:

    def test_create_memory_signal(self):
        backend = create_signal_backend("memory")
        assert isinstance(backend, MemorySignalBackend)

    def test_create_sqlite_signal(self, tmp_path):
        backend = create_signal_backend("sqlite", db_path=str(tmp_path / "test.sqlite"))
        assert isinstance(backend, SQLiteSignalBackend)

    def test_create_unknown_signal_raises(self):
        with pytest.raises(ValueError, match="Unknown"):
            create_signal_backend("redis")

    def test_create_noop_trigger(self):
        trigger = create_trigger_backend("none")
        assert isinstance(trigger, NoOpTrigger)

    def test_create_file_trigger(self, tmp_path):
        trigger = create_trigger_backend("file", base_path=str(tmp_path))
        assert isinstance(trigger, FileTrigger)

    def test_create_socket_trigger(self):
        trigger = create_trigger_backend("socket", socket_path="/tmp/test.sock")
        assert isinstance(trigger, SocketTrigger)

    def test_create_unknown_trigger_raises(self):
        with pytest.raises(ValueError, match="Unknown"):
            create_trigger_backend("webhook")


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------

class TestProtocol:

    def test_memory_is_signal_backend(self):
        assert isinstance(MemorySignalBackend(), SignalBackend)

    def test_sqlite_is_signal_backend(self, tmp_path):
        backend = SQLiteSignalBackend(db_path=str(tmp_path / "test.sqlite"))
        assert isinstance(backend, SignalBackend)

    def test_noop_is_trigger_backend(self):
        assert isinstance(NoOpTrigger(), TriggerBackend)

    def test_file_is_trigger_backend(self, tmp_path):
        assert isinstance(FileTrigger(base_path=str(tmp_path)), TriggerBackend)

    def test_socket_is_trigger_backend(self):
        assert isinstance(SocketTrigger(), TriggerBackend)

    def test_exports_from_init(self):
        """Top-level flatmachines imports work."""
        from flatmachines import (
            Signal,
            SignalBackend,
            TriggerBackend,
            MemorySignalBackend,
            SQLiteSignalBackend,
            NoOpTrigger,
            FileTrigger,
            SocketTrigger,
            create_signal_backend,
            create_trigger_backend,
        )

"""
Unit tests for signals_helpers — composition helpers over signal/trigger backends.
"""

import pytest

from flatmachines.signals import (
    MemorySignalBackend,
    SQLiteSignalBackend,
    NoOpTrigger,
    FileTrigger,
    TriggerBackend,
)
from flatmachines.signals_helpers import send_and_notify


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(params=["memory", "sqlite"])
def signal_backend(request, tmp_path):
    if request.param == "memory":
        return MemorySignalBackend()
    return SQLiteSignalBackend(db_path=str(tmp_path / "test_helpers.sqlite"))


# ---------------------------------------------------------------------------
# send_and_notify
# ---------------------------------------------------------------------------

class TestSendAndNotify:

    @pytest.mark.asyncio
    async def test_returns_signal_id(self, signal_backend):
        trigger = NoOpTrigger()
        sig_id = await send_and_notify(signal_backend, trigger, "ch/1", {"key": "val"})
        assert isinstance(sig_id, str)
        assert len(sig_id) > 0

    @pytest.mark.asyncio
    async def test_signal_is_persisted(self, signal_backend):
        trigger = NoOpTrigger()
        await send_and_notify(signal_backend, trigger, "ch/1", {"persisted": True})

        sig = await signal_backend.consume("ch/1")
        assert sig is not None
        assert sig.data == {"persisted": True}

    @pytest.mark.asyncio
    async def test_trigger_is_called(self, signal_backend, tmp_path):
        trigger = FileTrigger(base_path=str(tmp_path))
        await send_and_notify(signal_backend, trigger, "ch/1", {})

        assert (tmp_path / "trigger").exists()

    @pytest.mark.asyncio
    async def test_signal_durable_when_trigger_fails(self, signal_backend):
        """Signal must persist even if trigger.notify raises."""

        class FailingTrigger:
            async def notify(self, channel: str) -> None:
                raise ConnectionError("trigger is down")

        trigger = FailingTrigger()
        sig_id = await send_and_notify(signal_backend, trigger, "ch/1", {"safe": True})

        # Signal should still be consumable
        assert isinstance(sig_id, str)
        sig = await signal_backend.consume("ch/1")
        assert sig is not None
        assert sig.data == {"safe": True}

    @pytest.mark.asyncio
    async def test_multiple_channels(self, signal_backend):
        trigger = NoOpTrigger()
        id_a = await send_and_notify(signal_backend, trigger, "alpha", {"from": "a"})
        id_b = await send_and_notify(signal_backend, trigger, "beta", {"from": "b"})

        assert id_a != id_b

        sig_a = await signal_backend.consume("alpha")
        sig_b = await signal_backend.consume("beta")
        assert sig_a.data == {"from": "a"}
        assert sig_b.data == {"from": "b"}

    @pytest.mark.asyncio
    async def test_fifo_ordering_preserved(self, signal_backend):
        trigger = NoOpTrigger()
        await send_and_notify(signal_backend, trigger, "ch", {"seq": 1})
        await send_and_notify(signal_backend, trigger, "ch", {"seq": 2})
        await send_and_notify(signal_backend, trigger, "ch", {"seq": 3})

        s1 = await signal_backend.consume("ch")
        s2 = await signal_backend.consume("ch")
        s3 = await signal_backend.consume("ch")
        assert s1.data == {"seq": 1}
        assert s2.data == {"seq": 2}
        assert s3.data == {"seq": 3}


# ---------------------------------------------------------------------------
# Import from top-level package
# ---------------------------------------------------------------------------

class TestExports:

    def test_importable_from_flatmachines(self):
        from flatmachines import send_and_notify as sn
        assert sn is send_and_notify

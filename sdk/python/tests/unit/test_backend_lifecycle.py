"""
Unit tests for PersistenceBackend.list_execution_ids() and .delete_execution().

Tests the backend contract directly — no FlatMachine, no CheckpointManager.
"""

import os
import shutil
import pytest

from flatmachines import LocalFileBackend, MemoryBackend, SQLiteCheckpointBackend


@pytest.fixture(autouse=True)
def cleanup():
    for d in [".checkpoints"]:
        if os.path.exists(d):
            shutil.rmtree(d)
    yield
    for d in [".checkpoints"]:
        if os.path.exists(d):
            shutil.rmtree(d)


async def _write_checkpoint(backend, execution_id: str, step: int = 1, event: str = "execute"):
    """Write a fake checkpoint directly to the backend."""
    key = f"{execution_id}/step_{step:06d}_{event}.json"
    await backend.save(key, b'{"fake": true}')
    # Update latest pointer (mirrors CheckpointManager convention)
    await backend.save(f"{execution_id}/latest", key.encode())


@pytest.fixture(params=["local", "memory", "sqlite"])
def backend(request, tmp_path):
    if request.param == "local":
        return LocalFileBackend()
    elif request.param == "sqlite":
        return SQLiteCheckpointBackend(db_path=str(tmp_path / "test.sqlite"))
    return MemoryBackend()


# ---------------------------------------------------------------------------
# list_execution_ids
# ---------------------------------------------------------------------------

class TestListExecutionIds:

    @pytest.mark.asyncio
    async def test_empty(self, backend):
        assert await backend.list_execution_ids() == []

    @pytest.mark.asyncio
    async def test_single(self, backend):
        await _write_checkpoint(backend, "exec-a")
        assert await backend.list_execution_ids() == ["exec-a"]

    @pytest.mark.asyncio
    async def test_multiple(self, backend):
        await _write_checkpoint(backend, "exec-a")
        await _write_checkpoint(backend, "exec-b")
        assert set(await backend.list_execution_ids()) == {"exec-a", "exec-b"}

    @pytest.mark.asyncio
    async def test_sorted(self, backend):
        await _write_checkpoint(backend, "charlie")
        await _write_checkpoint(backend, "alpha")
        await _write_checkpoint(backend, "bravo")
        assert await backend.list_execution_ids() == ["alpha", "bravo", "charlie"]

    @pytest.mark.asyncio
    async def test_deduplicates_multiple_steps(self, backend):
        await _write_checkpoint(backend, "exec-1", step=1, event="state_enter")
        await _write_checkpoint(backend, "exec-1", step=1, event="execute")
        await _write_checkpoint(backend, "exec-1", step=2, event="state_enter")
        assert await backend.list_execution_ids() == ["exec-1"]


# ---------------------------------------------------------------------------
# delete_execution
# ---------------------------------------------------------------------------

class TestDeleteExecution:

    @pytest.mark.asyncio
    async def test_removes_latest_pointer(self, backend):
        await _write_checkpoint(backend, "doomed")
        await backend.delete_execution("doomed")
        assert await backend.load("doomed/latest") is None

    @pytest.mark.asyncio
    async def test_removes_step_files(self, backend):
        await _write_checkpoint(backend, "doomed", step=1)
        await _write_checkpoint(backend, "doomed", step=2)
        await backend.delete_execution("doomed")
        assert await backend.load("doomed/step_000001_execute.json") is None
        assert await backend.load("doomed/step_000002_execute.json") is None

    @pytest.mark.asyncio
    async def test_gone_from_list(self, backend):
        await _write_checkpoint(backend, "keep")
        await _write_checkpoint(backend, "remove")
        await backend.delete_execution("remove")
        assert await backend.list_execution_ids() == ["keep"]

    @pytest.mark.asyncio
    async def test_other_executions_untouched(self, backend):
        await _write_checkpoint(backend, "safe")
        await _write_checkpoint(backend, "doomed")
        await backend.delete_execution("doomed")
        assert await backend.load("safe/latest") is not None

    @pytest.mark.asyncio
    async def test_nonexistent_is_noop(self, backend):
        await backend.delete_execution("ghost")  # should not raise

    @pytest.mark.asyncio
    async def test_idempotent(self, backend):
        await _write_checkpoint(backend, "once")
        await backend.delete_execution("once")
        await backend.delete_execution("once")  # second call is fine

"""Unit tests for SQLiteCheckpointBackend."""

import sqlite3
import pytest

from flatmachines import SQLiteCheckpointBackend


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test_checkpoints.sqlite")


@pytest.fixture
def backend(db_path):
    return SQLiteCheckpointBackend(db_path=db_path)


# ---------------------------------------------------------------------------
# Basic save / load / delete
# ---------------------------------------------------------------------------

class TestBasicOperations:

    @pytest.mark.asyncio
    async def test_save_and_load(self, backend):
        await backend.save("exec-1/step_000001_execute.json", b'{"hello": true}')
        result = await backend.load("exec-1/step_000001_execute.json")
        assert result == b'{"hello": true}'

    @pytest.mark.asyncio
    async def test_load_missing_returns_none(self, backend):
        assert await backend.load("nonexistent/key") is None

    @pytest.mark.asyncio
    async def test_delete(self, backend):
        await backend.save("exec-1/step_000001_execute.json", b'{"x": 1}')
        await backend.delete("exec-1/step_000001_execute.json")
        assert await backend.load("exec-1/step_000001_execute.json") is None

    @pytest.mark.asyncio
    async def test_delete_missing_is_noop(self, backend):
        await backend.delete("ghost/key")  # no raise

    @pytest.mark.asyncio
    async def test_overwrite(self, backend):
        await backend.save("exec-1/step_000001_execute.json", b'{"v": 1}')
        await backend.save("exec-1/step_000001_execute.json", b'{"v": 2}')
        result = await backend.load("exec-1/step_000001_execute.json")
        assert result == b'{"v": 2}'


# ---------------------------------------------------------------------------
# Latest pointer (stored in machine_latest table)
# ---------------------------------------------------------------------------

class TestLatestPointer:

    @pytest.mark.asyncio
    async def test_save_and_load_latest(self, backend):
        pointer = b"exec-1/step_000001_execute.json"
        await backend.save("exec-1/latest", pointer)
        assert await backend.load("exec-1/latest") == pointer

    @pytest.mark.asyncio
    async def test_latest_updates_on_overwrite(self, backend):
        await backend.save("exec-1/latest", b"exec-1/step_000001_execute.json")
        await backend.save("exec-1/latest", b"exec-1/step_000002_execute.json")
        assert await backend.load("exec-1/latest") == b"exec-1/step_000002_execute.json"

    @pytest.mark.asyncio
    async def test_delete_latest(self, backend):
        await backend.save("exec-1/latest", b"exec-1/step_000001_execute.json")
        await backend.delete("exec-1/latest")
        assert await backend.load("exec-1/latest") is None


# ---------------------------------------------------------------------------
# list_execution_ids
# ---------------------------------------------------------------------------

class TestListExecutionIds:

    @pytest.mark.asyncio
    async def test_empty(self, backend):
        assert await backend.list_execution_ids() == []

    @pytest.mark.asyncio
    async def test_returns_distinct_ids(self, backend):
        await backend.save("exec-a/step_000001_execute.json", b'{}')
        await backend.save("exec-a/step_000002_execute.json", b'{}')
        await backend.save("exec-b/step_000001_execute.json", b'{}')
        assert set(await backend.list_execution_ids()) == {"exec-a", "exec-b"}

    @pytest.mark.asyncio
    async def test_sorted(self, backend):
        await backend.save("charlie/step_000001_execute.json", b'{}')
        await backend.save("alpha/step_000001_execute.json", b'{}')
        assert await backend.list_execution_ids() == ["alpha", "charlie"]


# ---------------------------------------------------------------------------
# delete_execution
# ---------------------------------------------------------------------------

class TestDeleteExecution:

    @pytest.mark.asyncio
    async def test_removes_all_checkpoints(self, backend):
        await backend.save("doomed/step_000001_execute.json", b'{}')
        await backend.save("doomed/step_000002_execute.json", b'{}')
        await backend.save("doomed/latest", b"doomed/step_000002_execute.json")
        await backend.delete_execution("doomed")
        assert await backend.load("doomed/step_000001_execute.json") is None
        assert await backend.load("doomed/latest") is None

    @pytest.mark.asyncio
    async def test_other_executions_untouched(self, backend):
        await backend.save("safe/step_000001_execute.json", b'{"safe": true}')
        await backend.save("doomed/step_000001_execute.json", b'{}')
        await backend.delete_execution("doomed")
        assert await backend.load("safe/step_000001_execute.json") == b'{"safe": true}'

    @pytest.mark.asyncio
    async def test_nonexistent_is_noop(self, backend):
        await backend.delete_execution("ghost")

    @pytest.mark.asyncio
    async def test_gone_from_list(self, backend):
        await backend.save("keep/step_000001_execute.json", b'{}')
        await backend.save("remove/step_000001_execute.json", b'{}')
        await backend.delete_execution("remove")
        assert await backend.list_execution_ids() == ["keep"]


# ---------------------------------------------------------------------------
# Schema / init
# ---------------------------------------------------------------------------

class TestSchemaCreation:

    def test_creates_tables_on_init(self, db_path):
        backend = SQLiteCheckpointBackend(db_path=db_path)
        conn = sqlite3.connect(db_path)
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        assert "machine_checkpoints" in tables
        assert "machine_latest" in tables

    def test_wal_mode(self, db_path):
        backend = SQLiteCheckpointBackend(db_path=db_path)
        conn = sqlite3.connect(db_path)
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"

    def test_idempotent_init(self, db_path):
        """Creating two backends on the same DB doesn't fail."""
        b1 = SQLiteCheckpointBackend(db_path=db_path)
        b2 = SQLiteCheckpointBackend(db_path=db_path)


# ---------------------------------------------------------------------------
# Key validation
# ---------------------------------------------------------------------------

class TestKeyValidation:

    @pytest.mark.asyncio
    async def test_rejects_path_traversal(self, backend):
        with pytest.raises(ValueError):
            await backend.save("../etc/passwd", b"bad")

    @pytest.mark.asyncio
    async def test_rejects_absolute_path(self, backend):
        with pytest.raises(ValueError):
            await backend.save("/etc/passwd", b"bad")

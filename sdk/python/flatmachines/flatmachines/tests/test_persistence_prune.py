"""Tests for persistence module prune methods and _EPOCH sentinel constant."""
import json
from datetime import datetime, timezone, timedelta

import pytest

from ..persistence import (
    _EPOCH,
    MemoryBackend,
    LocalFileBackend,
    SQLiteCheckpointBackend,
)




def _make_snapshot_bytes(created_at: str) -> bytes:
    """Return a minimal snapshot JSON blob with a given created_at timestamp."""
    return json.dumps({
        "execution_id": "x",
        "machine_name": "test",
        "spec_version": "4.1.0",
        "current_state": "done",
        "context": {},
        "step": 1,
        "created_at": created_at,
        "event": "machine_end",
    }).encode("utf-8")


def _populate_memory(memory: MemoryBackend, *timestamps: str) -> None:
    """Populate MemoryBackend with one execution per timestamp."""
    for i, ts in enumerate(timestamps):
        eid = f"exec_{i:03d}"
        dummy_snapshot = _make_snapshot_bytes(ts)
        latest_key = f"{eid}/step_000001_machine_end.json"
        memory._store[latest_key] = dummy_snapshot
        memory._store[f"{eid}/latest"] = latest_key.encode("utf-8")


# ---------------------------------------------------------------------------
# _EPOCH constant
# ---------------------------------------------------------------------------

class TestEpochConstant:
    def test_is_datetime(self):
        assert isinstance(_EPOCH, datetime)

    def test_is_utc_aware(self):
        assert _EPOCH.tzinfo is timezone.utc

    def test_is_minimum_value(self):
        assert _EPOCH == datetime.min.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# MemoryBackend.prune — max_count=0 (remove all)
# ---------------------------------------------------------------------------

class TestPruneMemoryBackendMaxCount:
    pytestmark = pytest.mark.asyncio

    @pytest.fixture
    def populated_backend(self):
        b = MemoryBackend()
        now = datetime.now(timezone.utc)
        _populate_memory(b, *(now.isoformat() for _ in range(5)))
        return b

    async def test_removes_all_when_max_count_zero(self, populated_backend):
        deleted = await populated_backend.prune(max_count=0)
        assert deleted == 5
        assert len(populated_backend._store) == 0

    async def test_max_count_zero_on_empty_backend(self):
        b = MemoryBackend()
        deleted = await b.prune(max_count=0)
        assert deleted == 0

    async def test_removes_none_when_max_count_ge_count(self, populated_backend):
        deleted = await populated_backend.prune(max_count=10)
        assert deleted == 0
        assert len(populated_backend._store) == 10  # 5 latest + 5 snapshots


# ---------------------------------------------------------------------------
# MemoryBackend.prune — max_age_seconds
# ---------------------------------------------------------------------------

class TestPruneMemoryBackendAge:
    pytestmark = pytest.mark.asyncio

    @pytest.fixture
    def backend(self):
        b = MemoryBackend()
        now = datetime.now(timezone.utc)
        _populate_memory(
            b,
            (now - timedelta(hours=2)).isoformat(),  # old
            (now - timedelta(hours=1)).isoformat(),  # old
            now.isoformat(),                         # recent
        )
        return b

    async def test_removes_old_executions(self, backend):
        deleted = await backend.prune(max_age_seconds=1800)  # 30 min
        assert deleted == 2

    async def test_keeps_recent_executions(self, backend):
        await backend.prune(max_age_seconds=1800)
        # exec_002 is the recent one — its latest pointer must survive
        assert "exec_002/latest" in backend._store

    async def test_keeps_all_when_age_is_large(self, backend):
        deleted = await backend.prune(max_age_seconds=86400)  # 1 day
        assert deleted == 0


# ---------------------------------------------------------------------------
# MemoryBackend.prune — combined age + count
# ---------------------------------------------------------------------------

class TestPruneMemoryBackendCombined:
    pytestmark = pytest.mark.asyncio

    async def test_age_then_count(self):
        b = MemoryBackend()
        now = datetime.now(timezone.utc)
        _populate_memory(
            b,
            (now - timedelta(hours=3)).isoformat(),  # exec_000 — old
            (now - timedelta(hours=2)).isoformat(),  # exec_001 — old
            (now - timedelta(minutes=5)).isoformat(), # exec_002 — recent
            now.isoformat(),                          # exec_003 — recent
        )
        # Age: cut at 1 hour → removes exec_000, exec_001
        # Then max_count=1 → keeps exec_003 only (the most recent)
        deleted = await b.prune(max_age_seconds=3600, max_count=1)
        assert deleted == 3
        assert "exec_003/latest" in b._store
        assert all(f"exec_{i:03d}/latest" not in b._store for i in (0, 1, 2))


# ---------------------------------------------------------------------------
# MemoryBackend.prune — missing data edge cases
# ---------------------------------------------------------------------------

class TestPruneMemoryBackendEdgeCases:
    pytestmark = pytest.mark.asyncio

    async def test_missing_latest_pointer(self):
        b = MemoryBackend()
        b._store["orphan/step_000001_test.json"] = _make_snapshot_bytes(
            datetime.now(timezone.utc).isoformat()
        )
        # No /latest pointer → _EPOCH fallback for that execution
        deleted = await b.prune(max_count=0)
        assert deleted == 1

    async def test_corrupted_snapshot(self):
        b = MemoryBackend()
        b._store["corrupt/latest"] = b"garbage_key"
        b._store["garbage_key"] = b"not-json"
        deleted = await b.prune(max_count=0)
        assert deleted == 1  # found via latest ptr, json fails → _EPOCH fallback → selectable


# ---------------------------------------------------------------------------
# LocalFileBackend.prune — basic scenarios
# ---------------------------------------------------------------------------

class TestPruneLocalFileBackend:
    pytestmark = pytest.mark.asyncio

    @pytest.fixture
    def backend(self, tmp_path):
        return LocalFileBackend(base_dir=str(tmp_path / ".checkpoints"))

    async def _save_execution(self, backend, eid: str, created_at: str):
        """Save a minimal execution to LocalFileBackend."""
        snapshot_bytes = _make_snapshot_bytes(created_at)
        key = f"{eid}/step_000001_machine_end.json"
        await backend.save(key, snapshot_bytes)
        await backend.save(f"{eid}/latest", key.encode("utf-8"))

    async def test_prune_max_count_zero_removes_all(self, backend):
        now = datetime.now(timezone.utc).isoformat()
        await self._save_execution(backend, "alpha", now)
        await self._save_execution(backend, "beta", now)

        deleted = await backend.prune(max_count=0)
        assert deleted == 2

    async def test_prune_age_removes_old(self, backend):
        now = datetime.now(timezone.utc)
        await self._save_execution(backend, "old", (now - timedelta(hours=2)).isoformat())
        await self._save_execution(backend, "new", now.isoformat())

        deleted = await backend.prune(max_age_seconds=3600)
        assert deleted == 1
        assert not (backend.base_dir / "old").exists()
        assert (backend.base_dir / "new").exists()

    async def test_prune_empty(self, backend):
        deleted = await backend.prune(max_count=0)
        assert deleted == 0


# ---------------------------------------------------------------------------
# SQLiteCheckpointBackend.prune — basic scenarios
# ---------------------------------------------------------------------------

class TestPruneSQLiteBackend:
    pytestmark = pytest.mark.asyncio

    @pytest.fixture
    def backend(self, tmp_path):
        return SQLiteCheckpointBackend(db_path=str(tmp_path / "test.sqlite"))

    async def _save_execution(self, backend, eid: str, created_at: str):
        """Save a minimal execution to SQLiteCheckpointBackend."""
        snapshot_bytes = _make_snapshot_bytes(created_at)
        key = f"{eid}/step_000001_machine_end.json"
        await backend.save(key, snapshot_bytes)
        await backend.save(f"{eid}/latest", key.encode("utf-8"))

    async def test_prune_max_count_zero_removes_all(self, backend):
        now = datetime.now(timezone.utc).isoformat()
        await self._save_execution(backend, "exec_a", now)
        await self._save_execution(backend, "exec_b", now)

        deleted = await backend.prune(max_count=0)
        assert deleted == 2

    async def test_prune_age_removes_old(self, backend):
        now = datetime.now(timezone.utc)
        await self._save_execution(backend, "old", (now - timedelta(hours=2)).isoformat())
        await self._save_execution(backend, "recent", now.isoformat())

        deleted = await backend.prune(max_age_seconds=3600)
        assert deleted == 1

    async def test_prune_empty(self, backend):
        deleted = await backend.prune(max_count=0)
        assert deleted == 0

    async def test_prune_max_age_only_keeps_newer(self, backend):
        now = datetime.now(timezone.utc)
        await self._save_execution(backend, "old", (now - timedelta(hours=3)).isoformat())
        await self._save_execution(backend, "recent", now.isoformat())

        deleted = await backend.prune(max_age_seconds=7200)
        assert deleted == 1

        ids = await backend.list_execution_ids()
        assert ids == ["recent"]


# ---------------------------------------------------------------------------
# _select_executions_to_prune  (testable helper)
# ---------------------------------------------------------------------------

class TestSelectExecutionsToPrune:
    def _helper(self, *, max_age_seconds=None, max_count=None):
        from ..persistence import _select_executions_to_prune
        now = datetime.now(timezone.utc)
        executions = {
            "old": now - timedelta(hours=3),
            "mid": now - timedelta(hours=1),
            "new": now,
        }
        return _select_executions_to_prune(
            executions,
            max_age_seconds=max_age_seconds,
            max_count=max_count,
        )

    def test_age_removes_old(self):
        deleted = self._helper(max_age_seconds=7200)
        assert deleted == {"old"}

    def test_count_removes_oldest(self):
        deleted = self._helper(max_count=2)
        assert deleted == {"old"}

    def test_count_zero_removes_all(self):
        deleted = self._helper(max_count=0)
        assert deleted == {"old", "mid", "new"}

    def test_age_and_count(self):
        now = datetime.now(timezone.utc)
        from ..persistence import _select_executions_to_prune
        executions = {
            "v_old": now - timedelta(hours=5),
            "old_a": now - timedelta(hours=3),
            "old_b": now - timedelta(hours=2),
            "mid": now - timedelta(minutes=30),
            "new_a": now - timedelta(minutes=5),
            "new_b": now,
        }
        # Age cutoff at 1 hour → removes v_old, old_a, old_b (3)
        # Then max_count=2 → among mid, new_a, new_b → keeps new_a, new_b → removes mid
        deleted = _select_executions_to_prune(
            executions,
            max_age_seconds=3600,
            max_count=2,
        )
        assert len(deleted) == 4
        assert "new_a" not in deleted
        assert "new_b" not in deleted

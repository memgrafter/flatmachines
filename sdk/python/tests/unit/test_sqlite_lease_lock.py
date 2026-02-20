"""Unit tests for SQLiteLeaseLock."""

import asyncio
import sqlite3
import time
import pytest

from flatmachines import SQLiteLeaseLock


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test_leases.sqlite")


def make_lock(db_path, owner_id="owner-1", ttl=10, renew=3):
    return SQLiteLeaseLock(
        db_path=db_path,
        owner_id=owner_id,
        ttl_seconds=ttl,
        renew_interval_seconds=renew,
    )


# ---------------------------------------------------------------------------
# Acquire / release
# ---------------------------------------------------------------------------

class TestAcquireRelease:

    @pytest.mark.asyncio
    async def test_acquire_returns_true(self, db_path):
        lock = make_lock(db_path)
        assert await lock.acquire("exec-1") is True
        await lock.release("exec-1")

    @pytest.mark.asyncio
    async def test_same_owner_can_reacquire(self, db_path):
        lock = make_lock(db_path)
        assert await lock.acquire("exec-1") is True
        assert await lock.acquire("exec-1") is True
        await lock.release("exec-1")

    @pytest.mark.asyncio
    async def test_different_owner_blocked(self, db_path):
        lock_a = make_lock(db_path, owner_id="owner-a", ttl=300)
        lock_b = make_lock(db_path, owner_id="owner-b", ttl=300)
        assert await lock_a.acquire("exec-1") is True
        assert await lock_b.acquire("exec-1") is False
        await lock_a.release("exec-1")

    @pytest.mark.asyncio
    async def test_release_allows_other_owner(self, db_path):
        lock_a = make_lock(db_path, owner_id="owner-a")
        lock_b = make_lock(db_path, owner_id="owner-b")
        await lock_a.acquire("exec-1")
        await lock_a.release("exec-1")
        assert await lock_b.acquire("exec-1") is True
        await lock_b.release("exec-1")

    @pytest.mark.asyncio
    async def test_release_nonexistent_is_safe(self, db_path):
        lock = make_lock(db_path)
        await lock.release("ghost")  # no raise


# ---------------------------------------------------------------------------
# Lease expiry
# ---------------------------------------------------------------------------

class TestLeaseExpiry:

    @pytest.mark.asyncio
    async def test_expired_lease_can_be_stolen(self, db_path):
        lock_a = make_lock(db_path, owner_id="owner-a", ttl=30)
        assert await lock_a.acquire("exec-1") is True

        # Stop heartbeat so lease doesn't renew
        task = lock_a._heartbeat_tasks.pop("exec-1", None)
        stop = lock_a._heartbeat_stops.pop("exec-1", None)
        if stop:
            stop.set()
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # Manually expire the lease
        conn = sqlite3.connect(db_path)
        conn.execute(
            "UPDATE execution_leases SET lease_until = ? WHERE execution_id = ?",
            (int(time.time()) - 10, "exec-1"),
        )
        conn.commit()
        conn.close()

        lock_b = make_lock(db_path, owner_id="owner-b")
        assert await lock_b.acquire("exec-1") is True
        await lock_b.release("exec-1")


# ---------------------------------------------------------------------------
# Fencing token
# ---------------------------------------------------------------------------

class TestFencingToken:

    @pytest.mark.asyncio
    async def test_fencing_token_increments(self, db_path):
        lock = make_lock(db_path)
        await lock.acquire("exec-1")

        # Stop heartbeat, then expire the lease row (don't release — that deletes it)
        task = lock._heartbeat_tasks.pop("exec-1", None)
        stop = lock._heartbeat_stops.pop("exec-1", None)
        if stop:
            stop.set()
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        conn = sqlite3.connect(db_path)
        conn.execute(
            "UPDATE execution_leases SET lease_until = ?",
            (int(time.time()) - 10,),
        )
        conn.commit()
        conn.close()

        # Re-acquire hits ON CONFLICT → fencing_token increments
        await lock.acquire("exec-1")
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT fencing_token FROM execution_leases WHERE execution_id = ?",
            ("exec-1",),
        ).fetchone()
        assert row["fencing_token"] >= 2
        conn.close()
        await lock.release("exec-1")


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

class TestSchemaCreation:

    def test_creates_table(self, db_path):
        lock = make_lock(db_path)
        conn = sqlite3.connect(db_path)
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        assert "execution_leases" in tables

    def test_idempotent_init(self, db_path):
        """Two locks on same DB don't fail."""
        l1 = make_lock(db_path, owner_id="a")
        l2 = make_lock(db_path, owner_id="b")


# ---------------------------------------------------------------------------
# Multiple keys
# ---------------------------------------------------------------------------

class TestMultipleKeys:

    @pytest.mark.asyncio
    async def test_independent_locks(self, db_path):
        lock = make_lock(db_path)
        assert await lock.acquire("exec-1") is True
        assert await lock.acquire("exec-2") is True
        await lock.release("exec-1")
        await lock.release("exec-2")

    @pytest.mark.asyncio
    async def test_release_one_doesnt_affect_other(self, db_path):
        lock = make_lock(db_path)
        await lock.acquire("exec-1")
        await lock.acquire("exec-2")
        await lock.release("exec-1")
        # exec-2 still held — different owner can't take it
        lock_b = make_lock(db_path, owner_id="other")
        assert await lock_b.acquire("exec-2") is False
        await lock.release("exec-2")

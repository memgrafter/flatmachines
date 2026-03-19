"""
Unit tests for ConfigStore implementations.

Tests MemoryConfigStore, LocalFileConfigStore, SQLiteConfigStore,
and the SQLiteCheckpointBackend.config_store integration.
"""

import pytest
import tempfile
import os

from flatmachines import (
    MemoryConfigStore,
    LocalFileConfigStore,
    SQLiteCheckpointBackend,
    config_hash,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def memory_store():
    return MemoryConfigStore()


@pytest.fixture
def file_store(tmp_path):
    return LocalFileConfigStore(base_dir=str(tmp_path))


@pytest.fixture
def sqlite_store(tmp_path):
    backend = SQLiteCheckpointBackend(db_path=str(tmp_path / "test.sqlite"))
    return backend.config_store


SAMPLE_CONFIG = """\
spec: flatmachine
spec_version: "2.1.0"
data:
  name: test-machine
  states:
    start:
      type: initial
      transitions: [{to: done}]
    done:
      type: final
      output: {}
"""


# ---------------------------------------------------------------------------
# Parametrized tests across all backends
# ---------------------------------------------------------------------------

@pytest.fixture(params=["memory", "file", "sqlite"])
def store(request, tmp_path):
    if request.param == "memory":
        return MemoryConfigStore()
    elif request.param == "file":
        return LocalFileConfigStore(base_dir=str(tmp_path / "configs"))
    else:
        backend = SQLiteCheckpointBackend(db_path=str(tmp_path / "test.sqlite"))
        return backend.config_store


class TestConfigStoreContract:
    """Tests that apply to all ConfigStore implementations."""

    @pytest.mark.asyncio
    async def test_put_returns_hash(self, store):
        h = await store.put(SAMPLE_CONFIG)
        assert h == config_hash(SAMPLE_CONFIG)

    @pytest.mark.asyncio
    async def test_get_returns_content(self, store):
        h = await store.put(SAMPLE_CONFIG)
        raw = await store.get(h)
        assert raw == SAMPLE_CONFIG

    @pytest.mark.asyncio
    async def test_get_missing_returns_none(self, store):
        assert await store.get("0" * 64) is None

    @pytest.mark.asyncio
    async def test_put_idempotent(self, store):
        h1 = await store.put(SAMPLE_CONFIG)
        h2 = await store.put(SAMPLE_CONFIG)
        assert h1 == h2

    @pytest.mark.asyncio
    async def test_different_configs_different_hashes(self, store):
        h1 = await store.put("config-a")
        h2 = await store.put("config-b")
        assert h1 != h2
        assert await store.get(h1) == "config-a"
        assert await store.get(h2) == "config-b"

    @pytest.mark.asyncio
    async def test_delete(self, store):
        h = await store.put(SAMPLE_CONFIG)
        await store.delete(h)
        assert await store.get(h) is None

    @pytest.mark.asyncio
    async def test_delete_missing_is_noop(self, store):
        # Should not raise
        await store.delete("0" * 64)


# ---------------------------------------------------------------------------
# SQLiteCheckpointBackend.config_store integration
# ---------------------------------------------------------------------------

class TestSQLiteConfigStoreIntegration:

    def test_config_store_property(self, tmp_path):
        backend = SQLiteCheckpointBackend(db_path=str(tmp_path / "test.sqlite"))
        store = backend.config_store
        assert store is not None
        # Same instance on repeated access
        assert backend.config_store is store

    @pytest.mark.asyncio
    async def test_config_store_shares_db(self, tmp_path):
        """Config store uses the same SQLite database as checkpoints."""
        db_path = str(tmp_path / "shared.sqlite")
        backend = SQLiteCheckpointBackend(db_path=db_path)
        store = backend.config_store

        h = await store.put(SAMPLE_CONFIG)

        # Verify the table exists in the same database
        import sqlite3
        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT config_raw FROM machine_configs WHERE config_hash = ?",
            (h,),
        ).fetchone()
        conn.close()

        assert row is not None
        assert row[0] == SAMPLE_CONFIG

    @pytest.mark.asyncio
    async def test_sqlite_stores_metadata(self, tmp_path):
        """SQLiteConfigStore extracts machine_name and spec_version."""
        db_path = str(tmp_path / "meta.sqlite")
        backend = SQLiteCheckpointBackend(db_path=db_path)
        store = backend.config_store

        h = await store.put(SAMPLE_CONFIG)

        import sqlite3
        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT machine_name, spec_version FROM machine_configs WHERE config_hash = ?",
            (h,),
        ).fetchone()
        conn.close()

        assert row[0] == "test-machine"
        assert row[1] == "2.1.0"

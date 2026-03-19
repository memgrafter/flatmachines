"""Unit tests for declarative SQLite persistence configuration.

Validates that `backend: sqlite` in machine config correctly initializes
SQLiteCheckpointBackend, SQLiteLeaseLock, and auto-wires config_store —
without requiring imperative runner injection.
"""

import sqlite3
import pytest

from flatmachines import FlatMachine, SQLiteCheckpointBackend, SQLiteLeaseLock
from flatmachines.persistence import MemoryBackend, LocalFileBackend
from flatmachines.locking import NoOpLock, LocalFileLock


def _minimal_machine_config(persistence_config=None):
    """Build a minimal valid machine config with optional persistence block."""
    config = {
        "spec": "flatmachine",
        "spec_version": "2.2.1",
        "data": {
            "name": "test-sqlite-persistence",
            "states": {
                "start": {
                    "type": "initial",
                    "transitions": [{"to": "done"}],
                },
                "done": {
                    "type": "final",
                    "output": {"result": "ok"},
                },
            },
        },
    }
    if persistence_config is not None:
        config["data"]["persistence"] = persistence_config
    return config


# ---------------------------------------------------------------------------
# 1. backend: sqlite → SQLiteCheckpointBackend
# ---------------------------------------------------------------------------


class TestSqliteBackendInitialization:

    def test_persistence_config_sqlite_initializes_sqlite_backend(self, tmp_path):
        db = str(tmp_path / "state.db")
        config = _minimal_machine_config({
            "enabled": True,
            "backend": "sqlite",
            "db_path": db,
        })
        machine = FlatMachine(config_dict=config)
        assert isinstance(machine.persistence, SQLiteCheckpointBackend)
        assert machine.persistence.db_path == str((tmp_path / "state.db").resolve())

    def test_persistence_config_sqlite_default_db_path(self):
        """When db_path is omitted, a sensible default is used."""
        config = _minimal_machine_config({
            "enabled": True,
            "backend": "sqlite",
        })
        machine = FlatMachine(config_dict=config)
        assert isinstance(machine.persistence, SQLiteCheckpointBackend)
        assert "flatmachines.sqlite" in machine.persistence.db_path


# ---------------------------------------------------------------------------
# 2. backend: sqlite → SQLiteLeaseLock
# ---------------------------------------------------------------------------


class TestSqliteAutoLock:

    def test_persistence_config_sqlite_auto_lock_is_sqlite_lease(self, tmp_path):
        db = str(tmp_path / "state.db")
        config = _minimal_machine_config({
            "enabled": True,
            "backend": "sqlite",
            "db_path": db,
        })
        machine = FlatMachine(config_dict=config)
        assert isinstance(machine.lock, SQLiteLeaseLock)

    def test_sqlite_lock_uses_same_db_path(self, tmp_path):
        db = str(tmp_path / "state.db")
        config = _minimal_machine_config({
            "enabled": True,
            "backend": "sqlite",
            "db_path": db,
        })
        machine = FlatMachine(config_dict=config)
        resolved = str((tmp_path / "state.db").resolve())
        assert machine.lock.db_path == resolved


# ---------------------------------------------------------------------------
# 3. backend: sqlite actually writes to DB, not local files
# ---------------------------------------------------------------------------


class TestSqliteWritesToDb:

    @pytest.mark.asyncio
    async def test_persistence_config_sqlite_writes_to_db_not_local_files(self, tmp_path):
        db = str(tmp_path / "state.db")
        config = _minimal_machine_config({
            "enabled": True,
            "backend": "sqlite",
            "db_path": db,
        })
        machine = FlatMachine(config_dict=config)

        # Write a checkpoint directly through the persistence backend
        await machine.persistence.save(
            "test-exec/step_000001_execute.json",
            b'{"test": true}',
        )

        # Verify it's in SQLite
        conn = sqlite3.connect(db)
        rows = conn.execute(
            "SELECT checkpoint_key FROM machine_checkpoints"
        ).fetchall()
        conn.close()
        assert len(rows) == 1
        assert rows[0][0] == "test-exec/step_000001_execute.json"

        # Verify no .checkpoints directory was created
        checkpoints_dir = tmp_path / ".checkpoints"
        assert not checkpoints_dir.exists()


# ---------------------------------------------------------------------------
# 4. Unknown backend raises exception
# ---------------------------------------------------------------------------


class TestUnknownBackendRaises:

    def test_unknown_backend_raises_exception(self):
        config = _minimal_machine_config({
            "enabled": True,
            "backend": "redis",
        })
        with pytest.raises(ValueError, match="Unknown persistence backend 'redis'"):
            FlatMachine(config_dict=config)

    def test_unknown_backend_raises_with_custom_name(self):
        config = _minimal_machine_config({
            "enabled": True,
            "backend": "dynamodb",
        })
        with pytest.raises(ValueError, match="Unknown persistence backend 'dynamodb'"):
            FlatMachine(config_dict=config)


# ---------------------------------------------------------------------------
# 5. Auto-wire config_store from SQLite persistence
# ---------------------------------------------------------------------------


class TestSqliteAutoConfigStore:

    def test_sqlite_persistence_auto_config_store_wired(self, tmp_path):
        db = str(tmp_path / "state.db")
        config = _minimal_machine_config({
            "enabled": True,
            "backend": "sqlite",
            "db_path": db,
        })
        machine = FlatMachine(config_dict=config)
        assert machine._config_store is not None
        assert machine._config_store is machine.persistence.config_store

    def test_explicit_config_store_not_overwritten(self, tmp_path):
        """If caller passes config_store explicitly, don't replace it."""
        from flatmachines.persistence import MemoryConfigStore

        db = str(tmp_path / "state.db")
        explicit_store = MemoryConfigStore()
        config = _minimal_machine_config({
            "enabled": True,
            "backend": "sqlite",
            "db_path": db,
        })
        machine = FlatMachine(config_dict=config, config_store=explicit_store)
        assert machine._config_store is explicit_store


# ---------------------------------------------------------------------------
# Sanity: existing backends still work
# ---------------------------------------------------------------------------


class TestExistingBackendsUnchanged:

    def test_local_backend_still_works(self):
        config = _minimal_machine_config({
            "enabled": True,
            "backend": "local",
        })
        machine = FlatMachine(config_dict=config)
        assert isinstance(machine.persistence, LocalFileBackend)
        assert isinstance(machine.lock, LocalFileLock)

    def test_memory_backend_still_works(self):
        config = _minimal_machine_config({
            "enabled": True,
            "backend": "memory",
        })
        machine = FlatMachine(config_dict=config)
        assert isinstance(machine.persistence, MemoryBackend)
        assert isinstance(machine.lock, NoOpLock)

import json
import fcntl
import asyncio
import logging
import shutil
import sqlite3
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, List
from dataclasses import dataclass, asdict, field
from pathlib import Path
from datetime import datetime, timezone
import aiofiles

logger = logging.getLogger(__name__)

@dataclass
class MachineSnapshot:
    """Wire format for machine checkpoints."""
    execution_id: str
    machine_name: str
    spec_version: str
    current_state: str
    context: Dict[str, Any]
    step: int
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    event: Optional[str] = None  # The event that triggered this checkpoint (machine_start, etc)
    output: Optional[Dict[str, Any]] = None  # Output if captured at state_exit/machine_end
    total_api_calls: Optional[int] = None  # Cumulative API calls
    total_cost: Optional[float] = None  # Cumulative cost
    # Lineage (v0.4.0)
    parent_execution_id: Optional[str] = None  # ID of launcher machine if this was launched
    # Outbox pattern (v0.4.0)
    pending_launches: Optional[List[Dict[str, Any]]] = None  # LaunchIntent dicts awaiting completion
    # External signals (v1.2.0)
    waiting_channel: Optional[str] = None  # Signal channel this machine is blocked on

class PersistenceBackend(ABC):
    """Abstract storage backend for checkpoints."""
    
    @abstractmethod
    async def save(self, key: str, value: bytes) -> None:
        pass
    
    @abstractmethod
    async def load(self, key: str) -> Optional[bytes]:
        pass
    
    @abstractmethod
    async def delete(self, key: str) -> None:
        pass

    @abstractmethod
    async def list_execution_ids(
        self,
        *,
        event: Optional[str] = None,
        waiting_channel: Optional[str] = None,
    ) -> List[str]:
        """Return execution IDs that have checkpoint data.

        Args:
            event: If provided, only return IDs whose latest checkpoint
                   has this event value (e.g., "machine_end" for completed).
            waiting_channel: If provided, only return IDs whose latest checkpoint
                   has this waiting_channel value (e.g., "approval/task-001").
            If both are None, return all execution IDs.
        """
        pass

    @abstractmethod
    async def delete_execution(self, execution_id: str) -> None:
        """Remove all checkpoint data for an execution."""
        pass

class LocalFileBackend(PersistenceBackend):
    """File-based persistence backend."""

    def __init__(self, base_dir: str = ".checkpoints"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _validate_key(self, key: str) -> None:
        """Validate key to prevent path traversal attacks."""
        if '..' in key or key.startswith('/'):
            raise ValueError(f"Invalid checkpoint key: {key}")

    async def save(self, key: str, value: bytes) -> None:
        self._validate_key(key)
        path = self.base_dir / key
        path.parent.mkdir(parents=True, exist_ok=True)

        # Write to temp file first for atomicity
        temp_path = path.parent / f".{path.name}.tmp"
        async with aiofiles.open(temp_path, 'wb') as f:
            await f.write(value)

        # Atomic rename (safe on POSIX and Windows)
        temp_path.replace(path)

    async def load(self, key: str) -> Optional[bytes]:
        self._validate_key(key)
        path = self.base_dir / key
        if not path.exists():
            return None
        async with aiofiles.open(path, 'rb') as f:
            return await f.read()

    async def delete(self, key: str) -> None:
        self._validate_key(key)
        path = self.base_dir / key
        path.unlink(missing_ok=True)

    async def list_execution_ids(
        self,
        *,
        event: Optional[str] = None,
        waiting_channel: Optional[str] = None,
    ) -> List[str]:
        all_ids = sorted(
            d.name for d in self.base_dir.iterdir()
            if d.is_dir() and not d.name.startswith(".")
        )
        if event is None and waiting_channel is None:
            return all_ids
        # Filter by loading the latest snapshot for each execution
        matched = []
        for eid in all_ids:
            ptr_bytes = await self.load(f"{eid}/latest")
            if not ptr_bytes:
                continue
            key = ptr_bytes.decode("utf-8")
            data_bytes = await self.load(key)
            if not data_bytes:
                continue
            try:
                snapshot = json.loads(data_bytes.decode("utf-8"))
                if not isinstance(snapshot, dict):
                    continue
                if event is not None and snapshot.get("event") != event:
                    continue
                if waiting_channel is not None and snapshot.get("waiting_channel") != waiting_channel:
                    continue
                matched.append(eid)
            except Exception:
                continue
        return matched

    async def delete_execution(self, execution_id: str) -> None:
        self._validate_key(execution_id)
        exec_dir = self.base_dir / execution_id
        if exec_dir.exists() and exec_dir.is_dir():
            shutil.rmtree(exec_dir)

class MemoryBackend(PersistenceBackend):
    """In-memory backend for ephemeral executions."""
    
    def __init__(self):
        self._store: Dict[str, bytes] = {}
        
    async def save(self, key: str, value: bytes) -> None:
        self._store[key] = value
        
    async def load(self, key: str) -> Optional[bytes]:
        return self._store.get(key)
        
    async def delete(self, key: str) -> None:
        self._store.pop(key, None)

    async def list_execution_ids(
        self,
        *,
        event: Optional[str] = None,
        waiting_channel: Optional[str] = None,
    ) -> List[str]:
        ids = {k.split("/", 1)[0] for k in self._store if "/" in k}
        all_ids = sorted(ids)
        if event is None and waiting_channel is None:
            return all_ids
        matched = []
        for eid in all_ids:
            ptr_bytes = await self.load(f"{eid}/latest")
            if not ptr_bytes:
                continue
            key = ptr_bytes.decode("utf-8")
            data_bytes = await self.load(key)
            if not data_bytes:
                continue
            try:
                snapshot = json.loads(data_bytes.decode("utf-8"))
                if not isinstance(snapshot, dict):
                    continue
                if event is not None and snapshot.get("event") != event:
                    continue
                if waiting_channel is not None and snapshot.get("waiting_channel") != waiting_channel:
                    continue
                matched.append(eid)
            except Exception:
                continue
        return matched

    async def delete_execution(self, execution_id: str) -> None:
        prefix = f"{execution_id}/"
        keys = [k for k in self._store if k.startswith(prefix)]
        for k in keys:
            del self._store[k]

class CheckpointManager:
    """Manages saving and loading machine snapshots."""
    
    def __init__(self, backend: PersistenceBackend, execution_id: str):
        self.backend = backend
        self.execution_id = execution_id
        
    def _snapshot_key(self, event: str, step: int) -> str:
        """Generate key for specific snapshot."""
        return f"{self.execution_id}/step_{step:06d}_{event}.json"
        
    def _latest_pointer_key(self) -> str:
        """Key that points to the latest snapshot."""
        return f"{self.execution_id}/latest"

    def _safe_serialize_value(self, value: Any, path: str, non_serializable: List[str]) -> Any:
        """Recursively serialize a value, converting non-JSON types to strings."""
        if isinstance(value, dict):
            result = {}
            for k, v in value.items():
                try:
                    json.dumps({k: v})
                    result[k] = v
                except (TypeError, OverflowError):
                    result[k] = self._safe_serialize_value(v, f"{path}.{k}", non_serializable)
            return result
        elif isinstance(value, list):
            result = []
            for i, item in enumerate(value):
                try:
                    json.dumps(item)
                    result.append(item)
                except (TypeError, OverflowError):
                    result.append(self._safe_serialize_value(item, f"{path}[{i}]", non_serializable))
            return result
        else:
            try:
                json.dumps(value)
                return value
            except (TypeError, OverflowError):
                original_type = type(value).__name__
                non_serializable.append(f"{path} ({original_type})")
                return str(value)

    def _safe_serialize(self, data: Dict[str, Any]) -> str:
        """Safely serialize data to JSON, handling non-serializable objects."""
        try:
            return json.dumps(data)
        except (TypeError, OverflowError):
            # Identify and warn about specific non-serializable fields
            safe_data = {}
            non_serializable_fields: List[str] = []

            for k, v in data.items():
                if isinstance(v, dict):
                    # Recursively check nested dicts
                    try:
                        json.dumps(v)
                        safe_data[k] = v
                    except (TypeError, OverflowError):
                        safe_data[k] = self._safe_serialize_value(v, k, non_serializable_fields)
                elif isinstance(v, list):
                    # Recursively check lists
                    try:
                        json.dumps(v)
                        safe_data[k] = v
                    except (TypeError, OverflowError):
                        safe_data[k] = self._safe_serialize_value(v, k, non_serializable_fields)
                else:
                    try:
                        json.dumps({k: v})
                        safe_data[k] = v
                    except (TypeError, OverflowError):
                        original_type = type(v).__name__
                        safe_data[k] = str(v)
                        non_serializable_fields.append(f"{k} ({original_type})")

            if non_serializable_fields:
                logger.warning(
                    f"Context fields not JSON serializable, converted to strings: "
                    f"{', '.join(non_serializable_fields)}. "
                    f"These values will lose type information on restore."
                )

            return json.dumps(safe_data)

    async def save_checkpoint(self, snapshot: MachineSnapshot) -> None:
        """Save a snapshot and update latest pointer."""
        data = asdict(snapshot)
        json_bytes = self._safe_serialize(data).encode('utf-8')
        
        # Save the immutable snapshot
        key = self._snapshot_key(snapshot.event or "unknown", snapshot.step)
        await self.backend.save(key, json_bytes)
        
        # Update pointer to this key
        await self.backend.save(self._latest_pointer_key(), key.encode('utf-8'))
        
    async def load_latest(self) -> Optional[MachineSnapshot]:
        """Load the latest snapshot."""
        # Get pointer
        ptr_bytes = await self.backend.load(self._latest_pointer_key())
        if not ptr_bytes:
            return None
            
        # Get snapshot
        key = ptr_bytes.decode('utf-8')
        data_bytes = await self.backend.load(key)
        if not data_bytes:
            return None
            
        data = json.loads(data_bytes.decode('utf-8'))
        return MachineSnapshot(**data)

    async def load_status(self) -> Optional[tuple]:
        """Return (event, current_state) without deserializing full context.

        For SQLite backends this reads indexed columns directly.
        For other backends it falls back to loading the full snapshot.

        Returns:
            Tuple of (event, current_state), or None if no checkpoint exists.
        """
        ptr_bytes = await self.backend.load(self._latest_pointer_key())
        if not ptr_bytes:
            return None

        key = ptr_bytes.decode('utf-8')
        data_bytes = await self.backend.load(key)
        if not data_bytes:
            return None

        data = json.loads(data_bytes.decode('utf-8'))
        return (data.get("event"), data.get("current_state"))


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SQLiteCheckpointBackend(PersistenceBackend):
    """SQLite-backed checkpoint persistence.

    Stores snapshot blobs in a ``machine_checkpoints`` table and latest
    pointers in a ``machine_latest`` table.  Keys follow the standard
    FlatMachine conventions:

        "<execution_id>/step_000001_state_exit.json"
        "<execution_id>/latest"

    The backend uses WAL mode and a busy timeout for safe concurrent access
    from a single process with multiple async tasks.
    """

    def __init__(self, db_path: str):
        self.db_path = str(Path(db_path).resolve())
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=30.0)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA synchronous = NORMAL")
        self._conn.execute("PRAGMA busy_timeout = 10000")
        self._ensure_schema()
        self._op_lock = asyncio.Lock()

    def _ensure_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS machine_checkpoints (
                checkpoint_key  TEXT PRIMARY KEY,
                execution_id    TEXT NOT NULL,
                machine_name    TEXT,
                event           TEXT,
                current_state   TEXT,
                waiting_channel TEXT,
                snapshot_json   BLOB NOT NULL,
                created_at      TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_mc_execution_created
              ON machine_checkpoints(execution_id, created_at DESC);

            CREATE INDEX IF NOT EXISTS idx_mc_waiting_channel
              ON machine_checkpoints(waiting_channel)
              WHERE waiting_channel IS NOT NULL;

            CREATE TABLE IF NOT EXISTS machine_latest (
                execution_id TEXT PRIMARY KEY,
                latest_key   TEXT NOT NULL,
                updated_at   TEXT NOT NULL
            );
            """
        )
        # Migration: add waiting_channel if table already existed without it
        try:
            self._conn.execute(
                "ALTER TABLE machine_checkpoints ADD COLUMN waiting_channel TEXT"
            )
            self._conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_mc_waiting_channel
                  ON machine_checkpoints(waiting_channel)
                  WHERE waiting_channel IS NOT NULL
                """
            )
            self._conn.commit()
        except sqlite3.OperationalError:
            pass  # Column already exists
        self._conn.commit()

    @staticmethod
    def _validate_key(key: str) -> None:
        if not key or ".." in key or key.startswith("/"):
            raise ValueError(f"Invalid checkpoint key: {key}")

    @staticmethod
    def _execution_id_from_key(key: str) -> str:
        return key.split("/", 1)[0]

    async def save(self, key: str, value: bytes) -> None:
        self._validate_key(key)
        if not isinstance(value, (bytes, bytearray)):
            raise TypeError("Checkpoint value must be bytes")

        execution_id = self._execution_id_from_key(key)
        now = _utc_now_iso()

        async with self._op_lock:
            if key.endswith("/latest"):
                latest_key = bytes(value).decode("utf-8").strip()
                self._validate_key(latest_key)
                self._conn.execute(
                    """
                    INSERT INTO machine_latest (execution_id, latest_key, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(execution_id) DO UPDATE SET
                        latest_key = excluded.latest_key,
                        updated_at = excluded.updated_at
                    """,
                    (execution_id, latest_key, now),
                )
                self._conn.commit()
                return

            # Parse snapshot metadata for indexed columns
            machine_name = None
            event = None
            current_state = None
            waiting_channel = None
            try:
                snapshot = json.loads(bytes(value).decode("utf-8"))
                if isinstance(snapshot, dict):
                    machine_name = snapshot.get("machine_name")
                    event = snapshot.get("event")
                    current_state = snapshot.get("current_state")
                    waiting_channel = snapshot.get("waiting_channel")
            except Exception:
                pass

            self._conn.execute(
                """
                INSERT INTO machine_checkpoints (
                    checkpoint_key, execution_id, machine_name,
                    event, current_state, waiting_channel, snapshot_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(checkpoint_key) DO UPDATE SET
                    execution_id = excluded.execution_id,
                    machine_name = excluded.machine_name,
                    event = excluded.event,
                    current_state = excluded.current_state,
                    waiting_channel = excluded.waiting_channel,
                    snapshot_json = excluded.snapshot_json,
                    created_at = excluded.created_at
                """,
                (key, execution_id, machine_name, event, current_state,
                 waiting_channel, sqlite3.Binary(bytes(value)), now),
            )
            self._conn.commit()

    async def load(self, key: str) -> Optional[bytes]:
        self._validate_key(key)
        execution_id = self._execution_id_from_key(key)

        async with self._op_lock:
            if key.endswith("/latest"):
                row = self._conn.execute(
                    "SELECT latest_key FROM machine_latest WHERE execution_id = ?",
                    (execution_id,),
                ).fetchone()
                if not row:
                    return None
                return str(row["latest_key"]).encode("utf-8")

            row = self._conn.execute(
                "SELECT snapshot_json FROM machine_checkpoints WHERE checkpoint_key = ?",
                (key,),
            ).fetchone()
            if not row:
                return None
            payload = row["snapshot_json"]
            return bytes(payload) if payload is not None else None

    async def delete(self, key: str) -> None:
        self._validate_key(key)
        execution_id = self._execution_id_from_key(key)

        async with self._op_lock:
            if key.endswith("/latest"):
                self._conn.execute(
                    "DELETE FROM machine_latest WHERE execution_id = ?",
                    (execution_id,),
                )
                self._conn.commit()
                return

            self._conn.execute(
                "DELETE FROM machine_checkpoints WHERE checkpoint_key = ?",
                (key,),
            )
            self._conn.execute(
                "DELETE FROM machine_latest WHERE execution_id = ? AND latest_key = ?",
                (execution_id, key),
            )
            self._conn.commit()

    async def list_execution_ids(
        self,
        *,
        event: Optional[str] = None,
        waiting_channel: Optional[str] = None,
    ) -> List[str]:
        async with self._op_lock:
            if event is None and waiting_channel is None:
                rows = self._conn.execute(
                    "SELECT DISTINCT execution_id FROM machine_checkpoints ORDER BY execution_id"
                ).fetchall()
            else:
                # Join through latest pointer, filter on indexed columns
                conditions = []
                params = []
                if event is not None:
                    conditions.append("mc.event = ?")
                    params.append(event)
                if waiting_channel is not None:
                    conditions.append("mc.waiting_channel = ?")
                    params.append(waiting_channel)
                where = " AND ".join(conditions)
                rows = self._conn.execute(
                    f"""
                    SELECT ml.execution_id
                    FROM machine_latest ml
                    JOIN machine_checkpoints mc ON mc.checkpoint_key = ml.latest_key
                    WHERE {where}
                    ORDER BY ml.execution_id
                    """,
                    params,
                ).fetchall()
            return [r["execution_id"] for r in rows]

    async def delete_execution(self, execution_id: str) -> None:
        self._validate_key(execution_id)
        async with self._op_lock:
            self._conn.execute(
                "DELETE FROM machine_checkpoints WHERE execution_id = ?",
                (execution_id,),
            )
            self._conn.execute(
                "DELETE FROM machine_latest WHERE execution_id = ?",
                (execution_id,),
            )
            self._conn.commit()

"""
Signal and trigger backends for cross-process machine activation.

Signals are named-channel messages that wake checkpointed machines.
A machine paused at a `wait_for` state checkpoints with a `waiting_channel`
tag and exits. When a signal arrives on that channel, a dispatcher finds
matching checkpoints and resumes them.

Trigger backends notify a consumer process that a signal has arrived.
The trigger is an optimization — signals are durable in the signal backend.
If no trigger fires, signals are still consumed on next poll/startup.

Backends:
  SignalBackend:
    - MemorySignalBackend: In-memory, for testing and single-process
    - SQLiteSignalBackend: SQLite-backed, for durable local storage

  TriggerBackend:
    - NoOpTrigger:    Consumer already running (polling/in-process)
    - FileTrigger:    Touch file → launchd WatchPaths / systemd PathChanged
    - SocketTrigger:  SOCK_DGRAM to UDS → dispatcher wakes immediately
    - DynamoDB:       NoOpTrigger (Streams → Lambda is implicit infrastructure)
"""

import asyncio
import json
import logging
import os
import socket
import sqlite3
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


# =============================================================================
# Types
# =============================================================================

@dataclass
class Signal:
    """A signal on a named channel."""
    id: str
    channel: str
    data: Any
    created_at: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# =============================================================================
# Signal Backend Protocol
# =============================================================================

@runtime_checkable
class SignalBackend(Protocol):
    """Durable signal storage for cross-process machine activation."""

    async def send(self, channel: str, data: Any) -> str:
        """Send a signal to a named channel.

        Args:
            channel: Channel name (e.g., "approval/task-001", "quota/openai")
            data: Signal payload (JSON-serializable)

        Returns:
            Signal ID
        """
        ...

    async def consume(self, channel: str) -> Optional[Signal]:
        """Atomically consume the next signal on a channel.

        Removes the signal from storage.

        Returns:
            Signal or None if none pending
        """
        ...

    async def peek(self, channel: str) -> List[Signal]:
        """Peek at pending signals without consuming.

        Returns:
            List of pending signals on this channel
        """
        ...

    async def channels(self) -> List[str]:
        """List channels that have pending signals.

        Returns:
            List of channel names with pending signals
        """
        ...


# =============================================================================
# Trigger Backend Protocol
# =============================================================================

@runtime_checkable
class TriggerBackend(Protocol):
    """Process activation when signals or work arrive."""

    async def notify(self, channel: str) -> None:
        """Signal that activity occurred on a channel.

        Args:
            channel: Channel name
        """
        ...


# =============================================================================
# Memory Signal Backend
# =============================================================================

class MemorySignalBackend:
    """In-memory signal backend for testing and single-process use."""

    def __init__(self):
        self._channels: Dict[str, List[Signal]] = {}
        self._lock = asyncio.Lock()

    async def send(self, channel: str, data: Any) -> str:
        async with self._lock:
            signal_id = str(uuid.uuid4())
            sig = Signal(
                id=signal_id,
                channel=channel,
                data=data,
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            if channel not in self._channels:
                self._channels[channel] = []
            self._channels[channel].append(sig)
            logger.debug(f"Signal sent: {channel} ({signal_id})")
            return signal_id

    async def consume(self, channel: str) -> Optional[Signal]:
        async with self._lock:
            signals = self._channels.get(channel, [])
            if not signals:
                return None
            sig = signals.pop(0)
            if not signals:
                del self._channels[channel]
            logger.debug(f"Signal consumed: {channel} ({sig.id})")
            return sig

    async def peek(self, channel: str) -> List[Signal]:
        async with self._lock:
            return list(self._channels.get(channel, []))

    async def channels(self) -> List[str]:
        async with self._lock:
            return sorted(ch for ch, sigs in self._channels.items() if sigs)


# =============================================================================
# SQLite Signal Backend
# =============================================================================

class SQLiteSignalBackend:
    """SQLite-backed signal backend for durable local use.

    Stores signals in a ``signals`` table with atomic consume via DELETE
    returning the consumed row. Shares the sqlite_path convention with
    work pools and checkpoints.
    """

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS signals (
        id TEXT PRIMARY KEY,
        channel TEXT NOT NULL,
        data_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_signals_channel
      ON signals(channel, created_at ASC);
    """

    def __init__(self, db_path: str = "flatmachines.sqlite"):
        self.db_path = Path(db_path).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False, timeout=30.0)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA synchronous = NORMAL")
        self._conn.execute("PRAGMA busy_timeout = 10000")
        self._conn.executescript(self.SCHEMA)
        self._conn.commit()
        self._lock = asyncio.Lock()

    def _row_to_signal(self, row: sqlite3.Row) -> Signal:
        return Signal(
            id=row["id"],
            channel=row["channel"],
            data=json.loads(row["data_json"]),
            created_at=row["created_at"],
        )

    async def send(self, channel: str, data: Any) -> str:
        async with self._lock:
            signal_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc).isoformat()
            self._conn.execute(
                "INSERT INTO signals (id, channel, data_json, created_at) VALUES (?, ?, ?, ?)",
                (signal_id, channel, json.dumps(data), now),
            )
            self._conn.commit()
            logger.debug(f"Signal sent: {channel} ({signal_id})")
            return signal_id

    async def consume(self, channel: str) -> Optional[Signal]:
        async with self._lock:
            row = self._conn.execute(
                "SELECT * FROM signals WHERE channel = ? ORDER BY created_at ASC LIMIT 1",
                (channel,),
            ).fetchone()
            if not row:
                return None
            sig = self._row_to_signal(row)
            self._conn.execute("DELETE FROM signals WHERE id = ?", (sig.id,))
            self._conn.commit()
            logger.debug(f"Signal consumed: {channel} ({sig.id})")
            return sig

    async def peek(self, channel: str) -> List[Signal]:
        async with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM signals WHERE channel = ? ORDER BY created_at ASC",
                (channel,),
            ).fetchall()
            return [self._row_to_signal(r) for r in rows]

    async def channels(self) -> List[str]:
        async with self._lock:
            rows = self._conn.execute(
                "SELECT DISTINCT channel FROM signals ORDER BY channel",
            ).fetchall()
            return [r["channel"] for r in rows]


# =============================================================================
# Trigger Backends
# =============================================================================

class NoOpTrigger:
    """No-op trigger for in-process consumers and DynamoDB deployments.

    DynamoDB Streams → Lambda handles activation at the infrastructure level.
    No application code needed.
    """

    async def notify(self, channel: str) -> None:
        pass


class FileTrigger:
    """File-based trigger for launchd WatchPaths / systemd PathChanged.

    Touches a single trigger file. The OS watches the file and starts
    the dispatcher process. Zero processes running while idle.
    """

    def __init__(self, base_path: str = "/tmp/flatmachines"):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    async def notify(self, channel: str) -> None:
        trigger_file = self.base_path / "trigger"
        trigger_file.touch()
        logger.debug(f"FileTrigger: touched {trigger_file}")


class SocketTrigger:
    """UDS datagram trigger for low-latency in-host wake.

    Sends channel name as a datagram to a Unix domain socket.
    The dispatcher binds the socket and reads notifications.

    SOCK_DGRAM — fire-and-forget, no connection state.
    Cross-platform: asyncio uses kqueue (macOS) / epoll (Linux).

    If no dispatcher is listening (socket doesn't exist), silently ignores.
    Signals are durable in the signal backend — the trigger is an optimization.
    """

    def __init__(self, socket_path: str = "/tmp/flatmachines/trigger.sock"):
        self.socket_path = socket_path

    async def notify(self, channel: str) -> None:
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            sock.setblocking(False)
            try:
                sock.sendto(channel.encode("utf-8"), self.socket_path)
                logger.debug(f"SocketTrigger: notified {channel}")
            finally:
                sock.close()
        except (FileNotFoundError, ConnectionRefusedError, OSError):
            # No dispatcher listening — signal is still in the backend
            logger.debug(f"SocketTrigger: no listener at {self.socket_path}, skipping")


# =============================================================================
# Factories
# =============================================================================

def create_signal_backend(backend_type: str = "memory", **kwargs: Any) -> SignalBackend:
    """Create a signal backend by type.

    Args:
        backend_type: "memory" or "sqlite"
        **kwargs: Backend-specific options (e.g., db_path for sqlite)
    """
    if backend_type == "memory":
        return MemorySignalBackend()
    elif backend_type == "sqlite":
        db_path = kwargs.get("db_path", "flatmachines.sqlite")
        return SQLiteSignalBackend(db_path=db_path)
    else:
        raise ValueError(f"Unknown signal backend type: {backend_type}")


def create_trigger_backend(backend_type: str = "none", **kwargs: Any) -> TriggerBackend:
    """Create a trigger backend by type.

    Args:
        backend_type: "none", "file", or "socket"
        **kwargs: Backend-specific options
    """
    if backend_type == "none":
        return NoOpTrigger()
    elif backend_type == "file":
        base_path = kwargs.get("base_path", "/tmp/flatmachines")
        return FileTrigger(base_path=base_path)
    elif backend_type == "socket":
        socket_path = kwargs.get("socket_path", "/tmp/flatmachines/trigger.sock")
        return SocketTrigger(socket_path=socket_path)
    else:
        raise ValueError(f"Unknown trigger backend type: {backend_type}")


__all__ = [
    "Signal",
    "SignalBackend",
    "TriggerBackend",
    "MemorySignalBackend",
    "SQLiteSignalBackend",
    "NoOpTrigger",
    "FileTrigger",
    "SocketTrigger",
    "create_signal_backend",
    "create_trigger_backend",
]

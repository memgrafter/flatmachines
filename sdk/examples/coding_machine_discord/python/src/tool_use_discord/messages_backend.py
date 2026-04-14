from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional


@dataclass(frozen=True)
class QueueMessage:
    id: int
    queue: str
    conversation_key: str
    payload: dict[str, Any]
    created_at: float
    available_at: float
    attempts: int
    lease_owner: Optional[str]
    lease_expires_at: Optional[float]


class SQLiteMessageBackend:
    """Generic leased message queue on SQLite.

    Queue semantics:
    - enqueue(): write message with optional dedupe key
    - lease(): claim visible messages for a worker (lease timeout)
    - ack(): mark complete
    - nack(): release for retry after optional delay
    """

    def __init__(self, db_path: str):
        self.db_path = str(Path(db_path).expanduser().resolve())
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA busy_timeout = 10000")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    queue TEXT NOT NULL,
                    conversation_key TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    dedupe_key TEXT,
                    created_at REAL NOT NULL,
                    available_at REAL NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    lease_owner TEXT,
                    lease_expires_at REAL,
                    leased_at REAL,
                    acked_at REAL
                )
                """
            )
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_dedupe
                ON messages(dedupe_key)
                WHERE dedupe_key IS NOT NULL
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_messages_ready
                ON messages(queue, acked_at, available_at, lease_expires_at)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS queue_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS discord_users (
                    user_id TEXT PRIMARY KEY,
                    username TEXT,
                    is_admin INTEGER NOT NULL DEFAULT 0,
                    updated_at REAL NOT NULL
                )
                """
            )

    def enqueue(
        self,
        *,
        queue: str,
        conversation_key: str,
        payload: dict[str, Any],
        dedupe_key: Optional[str] = None,
        available_at: Optional[float] = None,
        now: Optional[float] = None,
    ) -> Optional[int]:
        t = time.time() if now is None else float(now)
        ready_at = t if available_at is None else float(available_at)

        with self._connect() as conn:
            try:
                cur = conn.execute(
                    """
                    INSERT INTO messages(
                        queue, conversation_key, payload_json, dedupe_key,
                        created_at, available_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        queue,
                        conversation_key,
                        json.dumps(payload),
                        dedupe_key,
                        t,
                        ready_at,
                    ),
                )
                return int(cur.lastrowid)
            except sqlite3.IntegrityError:
                # Duplicate dedupe_key
                return None

    def lease(
        self,
        *,
        queue: str,
        worker_id: str,
        limit: int = 10,
        lease_seconds: float = 30.0,
        now: Optional[float] = None,
    ) -> list[QueueMessage]:
        if limit <= 0:
            return []

        t = time.time() if now is None else float(now)
        lease_expires_at = t + float(lease_seconds)

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                """
                SELECT id
                FROM messages
                WHERE queue = ?
                  AND acked_at IS NULL
                  AND available_at <= ?
                  AND (lease_expires_at IS NULL OR lease_expires_at <= ?)
                ORDER BY available_at ASC, id ASC
                LIMIT ?
                """,
                (queue, t, t, limit),
            ).fetchall()

            ids = [int(row["id"]) for row in rows]
            if not ids:
                conn.execute("COMMIT")
                return []

            conn.executemany(
                """
                UPDATE messages
                SET lease_owner = ?,
                    lease_expires_at = ?,
                    leased_at = ?,
                    attempts = attempts + 1
                WHERE id = ?
                """,
                [(worker_id, lease_expires_at, t, message_id) for message_id in ids],
            )

            placeholders = ",".join("?" for _ in ids)
            leased_rows = conn.execute(
                f"""
                SELECT *
                FROM messages
                WHERE id IN ({placeholders})
                ORDER BY id ASC
                """,
                ids,
            ).fetchall()
            conn.execute("COMMIT")

        return [self._row_to_message(row) for row in leased_rows]

    def ack(self, message_ids: Iterable[int], now: Optional[float] = None) -> int:
        ids = [int(mid) for mid in message_ids]
        if not ids:
            return 0

        t = time.time() if now is None else float(now)
        placeholders = ",".join("?" for _ in ids)

        with self._connect() as conn:
            cur = conn.execute(
                f"""
                UPDATE messages
                SET acked_at = ?,
                    lease_owner = NULL,
                    lease_expires_at = NULL,
                    leased_at = NULL
                WHERE id IN ({placeholders})
                  AND acked_at IS NULL
                """,
                [t, *ids],
            )
            return int(cur.rowcount)

    def nack(self, message_id: int, delay_seconds: float = 0.0, now: Optional[float] = None) -> bool:
        t = time.time() if now is None else float(now)
        available_at = t + float(delay_seconds)
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE messages
                SET available_at = ?,
                    lease_owner = NULL,
                    lease_expires_at = NULL,
                    leased_at = NULL
                WHERE id = ?
                  AND acked_at IS NULL
                """,
                (available_at, int(message_id)),
            )
            return cur.rowcount > 0

    def ack_conversation(self, *, queue: str, conversation_key: str, now: Optional[float] = None) -> int:
        """Acknowledge all active messages in a queue conversation.

        Useful when a permanent upstream error (e.g. out-of-quota) means
        retrying stale requests would create a response backlog.
        """
        t = time.time() if now is None else float(now)
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE messages
                SET acked_at = ?,
                    lease_owner = NULL,
                    lease_expires_at = NULL,
                    leased_at = NULL
                WHERE queue = ?
                  AND conversation_key = ?
                  AND acked_at IS NULL
                """,
                (t, str(queue), str(conversation_key)),
            )
            return int(cur.rowcount)

    def get_state(self, key: str, default: Optional[str] = None) -> Optional[str]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM queue_state WHERE key = ?",
                (key,),
            ).fetchone()
            if row is None:
                return default
            return str(row["value"])

    def set_state(self, key: str, value: str, now: Optional[float] = None) -> None:
        t = time.time() if now is None else float(now)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO queue_state(key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (key, value, t),
            )

    def upsert_discord_user(
        self,
        *,
        user_id: str,
        is_admin: bool,
        username: Optional[str] = None,
        now: Optional[float] = None,
    ) -> None:
        t = time.time() if now is None else float(now)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO discord_users(user_id, username, is_admin, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username = COALESCE(excluded.username, discord_users.username),
                    is_admin = excluded.is_admin,
                    updated_at = excluded.updated_at
                """,
                (str(user_id), username, 1 if is_admin else 0, t),
            )

    def is_discord_user_admin(self, user_id: Optional[str]) -> bool:
        if user_id is None:
            return False
        normalized = str(user_id).strip()
        if not normalized:
            return False

        with self._connect() as conn:
            row = conn.execute(
                "SELECT is_admin FROM discord_users WHERE user_id = ?",
                (normalized,),
            ).fetchone()
            if row is None:
                return False
            return bool(int(row["is_admin"]))

    def queue_counts(self) -> dict[str, dict[str, int]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    queue,
                    SUM(CASE WHEN acked_at IS NULL THEN 1 ELSE 0 END) AS active,
                    SUM(CASE WHEN acked_at IS NOT NULL THEN 1 ELSE 0 END) AS acked,
                    SUM(CASE WHEN acked_at IS NULL AND lease_owner IS NOT NULL THEN 1 ELSE 0 END) AS leased
                FROM messages
                GROUP BY queue
                ORDER BY queue
                """
            ).fetchall()

        out: dict[str, dict[str, int]] = {}
        for row in rows:
            out[str(row["queue"])] = {
                "active": int(row["active"] or 0),
                "acked": int(row["acked"] or 0),
                "leased": int(row["leased"] or 0),
            }
        return out

    @staticmethod
    def _row_to_message(row: sqlite3.Row) -> QueueMessage:
        return QueueMessage(
            id=int(row["id"]),
            queue=str(row["queue"]),
            conversation_key=str(row["conversation_key"]),
            payload=json.loads(row["payload_json"]),
            created_at=float(row["created_at"]),
            available_at=float(row["available_at"]),
            attempts=int(row["attempts"]),
            lease_owner=str(row["lease_owner"]) if row["lease_owner"] is not None else None,
            lease_expires_at=float(row["lease_expires_at"]) if row["lease_expires_at"] is not None else None,
        )

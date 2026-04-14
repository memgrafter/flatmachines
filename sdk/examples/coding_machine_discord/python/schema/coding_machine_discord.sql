-- SQLite schema for sdk/examples/coding_machine_discord
-- Mirrors python/src/tool_use_discord/messages_backend.py

PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA busy_timeout = 10000;

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
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_dedupe
ON messages(dedupe_key)
WHERE dedupe_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_messages_ready
ON messages(queue, acked_at, available_at, lease_expires_at);

CREATE TABLE IF NOT EXISTS queue_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS discord_users (
    user_id TEXT PRIMARY KEY,
    username TEXT,
    is_admin INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL
);


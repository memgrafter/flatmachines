/**
 * SQLite lease lock — Phase 3.8
 *
 * Ports Python SDK's SQLiteLeaseLock from locking.py.
 * Uses node:sqlite for zero-dependency SQLite.
 */

import { ExecutionLock } from './types';

export class SQLiteLeaseLock implements ExecutionLock {
  private db: any;
  private _ownsDb: boolean;
  private ownerId: string;
  private phase: string;
  private ttlSeconds: number;
  private renewIntervalSeconds: number;
  private _heartbeatTimers = new Map<string, ReturnType<typeof setInterval>>();

  constructor(optsOrDb: {
    dbPath: string;
    ownerId?: string;
    phase?: string;
    ttlSeconds?: number;
    renewIntervalSeconds?: number;
  } | any, dbOpts?: {
    ownerId?: string;
    phase?: string;
    ttlSeconds?: number;
    renewIntervalSeconds?: number;
  }) {
    // Accept either { dbPath, ... } options or a raw db instance
    if (optsOrDb && typeof optsOrDb === 'object' && typeof optsOrDb.exec === 'function') {
      // Raw db instance passed
      this.db = optsOrDb;
      this._ownsDb = false;
      this.ownerId = dbOpts?.ownerId ?? `${process.pid}:${Date.now()}`;
      this.phase = dbOpts?.phase ?? 'machine';
      this.ttlSeconds = Math.max(dbOpts?.ttlSeconds ?? 300, 30);
      this.renewIntervalSeconds = Math.max(dbOpts?.renewIntervalSeconds ?? 100, 5);
    } else {
      const opts = optsOrDb as { dbPath: string; ownerId?: string; phase?: string; ttlSeconds?: number; renewIntervalSeconds?: number };
      let DatabaseSync: any;
      try {
        DatabaseSync = require('node:sqlite').DatabaseSync;
      } catch {
        throw new Error('SQLiteLeaseLock requires Node.js ≥22.5 with built-in node:sqlite module.');
      }
      this._ownsDb = true;
      this.ownerId = opts.ownerId ?? `${process.pid}:${Date.now()}`;
      this.phase = opts.phase ?? 'machine';
      this.ttlSeconds = Math.max(opts.ttlSeconds ?? 300, 30);
      this.renewIntervalSeconds = Math.max(opts.renewIntervalSeconds ?? 100, 5);
      this.db = new DatabaseSync(opts.dbPath);
      this.db.exec('PRAGMA journal_mode = WAL');
      this.db.exec('PRAGMA synchronous = NORMAL');
      this.db.exec('PRAGMA busy_timeout = 10000');
    }
    this._ensureSchema();
  }

  private _ensureSchema(): void {
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS execution_leases (
        execution_id   TEXT PRIMARY KEY,
        owner_id       TEXT NOT NULL,
        phase          TEXT NOT NULL,
        lease_until    INTEGER NOT NULL,
        fencing_token  INTEGER NOT NULL DEFAULT 1,
        acquired_at    TEXT NOT NULL,
        updated_at     TEXT NOT NULL
      );
      CREATE INDEX IF NOT EXISTS idx_execution_leases_until
        ON execution_leases(lease_until);
    `);
  }

  async acquire(key: string): Promise<boolean> {
    const now = Math.floor(Date.now() / 1000);
    const leaseUntil = now + this.ttlSeconds;
    const isoNow = new Date().toISOString();

    this.db.exec('BEGIN IMMEDIATE');
    try {
      this.db.prepare(`
        INSERT INTO execution_leases (
          execution_id, owner_id, phase, lease_until,
          fencing_token, acquired_at, updated_at
        ) VALUES (?, ?, ?, ?, 1, ?, ?)
        ON CONFLICT(execution_id) DO UPDATE SET
          owner_id = excluded.owner_id,
          phase = excluded.phase,
          lease_until = excluded.lease_until,
          fencing_token = execution_leases.fencing_token + 1,
          updated_at = excluded.updated_at
        WHERE execution_leases.lease_until < ?
           OR execution_leases.owner_id = excluded.owner_id
      `).run(key, this.ownerId, this.phase, leaseUntil, isoNow, isoNow, now);

      const changes = this.db.prepare('SELECT changes() as c').get().c;
      this.db.exec('COMMIT');

      if (changes > 0) {
        this._startHeartbeat(key);
        return true;
      }
      return false;
    } catch {
      this.db.exec('ROLLBACK');
      return false;
    }
  }

  async release(key: string): Promise<void> {
    this._stopHeartbeat(key);
    try {
      this.db.prepare(
        'DELETE FROM execution_leases WHERE execution_id = ? AND owner_id = ?'
      ).run(key, this.ownerId);
    } catch {
      // Ignore
    }
  }

  private _startHeartbeat(key: string): void {
    if (this._heartbeatTimers.has(key)) return;
    const timer = setInterval(() => {
      this._renew(key);
    }, this.renewIntervalSeconds * 1000);
    // Allow the process to exit even if timer is running
    if (timer.unref) timer.unref();
    this._heartbeatTimers.set(key, timer);
  }

  private _stopHeartbeat(key: string): void {
    const timer = this._heartbeatTimers.get(key);
    if (timer) {
      clearInterval(timer);
      this._heartbeatTimers.delete(key);
    }
  }

  private _renew(key: string): boolean {
    const leaseUntil = Math.floor(Date.now() / 1000) + this.ttlSeconds;
    const isoNow = new Date().toISOString();
    try {
      this.db.prepare(`
        UPDATE execution_leases
        SET lease_until = ?, updated_at = ?
        WHERE execution_id = ? AND owner_id = ?
      `).run(leaseUntil, isoNow, key, this.ownerId);
      const changes = this.db.prepare('SELECT changes() as c').get().c;
      return changes > 0;
    } catch {
      return false;
    }
  }

  close(): void {
    for (const key of this._heartbeatTimers.keys()) {
      this._stopHeartbeat(key);
    }
    if (this._ownsDb) this.db.close();
  }
}

/**
 * Work pool backends.
 *
 * Ports Python SDK's work.py. Durable task storage with atomic claiming.
 * Memory and SQLite backends.
 */

import { randomUUID } from 'node:crypto';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

export interface WorkItem {
  id: string;
  data: any;
  claimed_by?: string;
  claimed_at?: string;
  attempts: number;
  max_retries: number;
  status?: string;
}

// ─────────────────────────────────────────────────────────────────────────────
// WorkPool interface
// ─────────────────────────────────────────────────────────────────────────────

export interface WorkPool {
  push(item: any, options?: { max_retries?: number }): Promise<string>;
  claim(workerId: string): Promise<WorkItem | null>;
  complete(itemId: string, result?: any): Promise<void>;
  fail(itemId: string, error?: string): Promise<void>;
  size(): Promise<number>;
  releaseByWorker(workerId: string): Promise<number>;
}

// ─────────────────────────────────────────────────────────────────────────────
// WorkBackend interface
// ─────────────────────────────────────────────────────────────────────────────

export interface WorkBackend {
  pool(name: string): WorkPool;
}

// ─────────────────────────────────────────────────────────────────────────────
// Memory implementations
// ─────────────────────────────────────────────────────────────────────────────

interface MemoryWorkItemInternal {
  id: string;
  data: any;
  status: string;
  claimed_by: string | null;
  claimed_at: string | null;
  attempts: number;
  max_retries: number;
  created_at: string;
}

export class MemoryWorkPool implements WorkPool {
  readonly name: string;
  private _items = new Map<string, MemoryWorkItemInternal>();

  constructor(name: string) { this.name = name; }

  async push(item: any, options?: { max_retries?: number }): Promise<string> {
    const id = randomUUID();
    this._items.set(id, {
      id, data: item, status: 'pending', claimed_by: null, claimed_at: null,
      attempts: 0, max_retries: options?.max_retries ?? 3,
      created_at: new Date().toISOString(),
    });
    return id;
  }

  async claim(workerId: string): Promise<WorkItem | null> {
    for (const item of this._items.values()) {
      if (item.status === 'pending') {
        item.status = 'claimed';
        item.claimed_by = workerId;
        item.claimed_at = new Date().toISOString();
        item.attempts += 1;
        return { id: item.id, data: item.data, claimed_by: workerId, claimed_at: item.claimed_at, attempts: item.attempts, max_retries: item.max_retries };
      }
    }
    return null;
  }

  async complete(itemId: string, _result?: any): Promise<void> {
    if (!this._items.has(itemId)) throw new Error(`Work item ${itemId} not found`);
    this._items.delete(itemId);
  }

  async fail(itemId: string, _error?: string): Promise<void> {
    const item = this._items.get(itemId);
    if (!item) throw new Error(`Work item ${itemId} not found`);
    if (item.attempts >= item.max_retries) {
      item.status = 'poisoned';
    } else {
      item.status = 'pending';
      item.claimed_by = null;
      item.claimed_at = null;
    }
  }

  async size(): Promise<number> {
    let count = 0;
    for (const item of this._items.values()) {
      if (item.status === 'pending') count++;
    }
    return count;
  }

  async releaseByWorker(workerId: string): Promise<number> {
    let released = 0;
    for (const item of this._items.values()) {
      if (item.claimed_by === workerId && item.status === 'claimed') {
        item.status = 'pending';
        item.claimed_by = null;
        item.claimed_at = null;
        released++;
      }
    }
    return released;
  }
}

export class MemoryWorkBackend implements WorkBackend {
  private _pools = new Map<string, MemoryWorkPool>();

  pool(name: string): MemoryWorkPool {
    let p = this._pools.get(name);
    if (!p) { p = new MemoryWorkPool(name); this._pools.set(name, p); }
    return p;
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// SQLite implementations
// ─────────────────────────────────────────────────────────────────────────────

export class SQLiteWorkPool implements WorkPool {
  readonly name: string;
  private db: any;

  constructor(name: string, db: any) {
    this.name = name;
    this.db = db;
  }

  async push(item: any, options?: { max_retries?: number }): Promise<string> {
    const id = randomUUID();
    const maxRetries = options?.max_retries ?? 3;
    const now = new Date().toISOString();
    this.db.prepare(`
      INSERT INTO work_pool (item_id, pool_name, data, status, attempts, max_retries, created_at)
      VALUES (?, ?, ?, 'pending', 0, ?, ?)
    `).run(id, this.name, JSON.stringify(item), maxRetries, now);
    return id;
  }

  async claim(workerId: string): Promise<WorkItem | null> {
    const now = new Date().toISOString();
    this.db.exec('BEGIN IMMEDIATE');
    try {
      const row = this.db.prepare(`
        SELECT item_id FROM work_pool
        WHERE pool_name = ? AND status = 'pending'
        ORDER BY created_at ASC LIMIT 1
      `).get(this.name);
      if (!row) { this.db.exec('COMMIT'); return null; }
      const itemId = row.item_id;
      this.db.prepare(`
        UPDATE work_pool SET status = 'claimed', claimed_by = ?, claimed_at = ?, attempts = attempts + 1
        WHERE item_id = ?
      `).run(workerId, now, itemId);
      this.db.exec('COMMIT');
      const updated = this.db.prepare('SELECT * FROM work_pool WHERE item_id = ?').get(itemId);
      if (!updated) return null;
      return { id: updated.item_id, data: JSON.parse(updated.data), claimed_by: updated.claimed_by, claimed_at: updated.claimed_at, attempts: updated.attempts, max_retries: updated.max_retries };
    } catch (e) {
      this.db.exec('ROLLBACK');
      throw e;
    }
  }

  async complete(itemId: string, _result?: any): Promise<void> {
    this.db.prepare('DELETE FROM work_pool WHERE item_id = ?').run(itemId);
  }

  async fail(itemId: string, _error?: string): Promise<void> {
    const row = this.db.prepare('SELECT attempts, max_retries FROM work_pool WHERE item_id = ?').get(itemId);
    if (!row) throw new Error(`Work item ${itemId} not found`);
    if (row.attempts >= row.max_retries) {
      this.db.prepare("UPDATE work_pool SET status = 'poisoned' WHERE item_id = ?").run(itemId);
    } else {
      this.db.prepare("UPDATE work_pool SET status = 'pending', claimed_by = NULL, claimed_at = NULL WHERE item_id = ?").run(itemId);
    }
  }

  async size(): Promise<number> {
    const row = this.db.prepare("SELECT COUNT(*) as cnt FROM work_pool WHERE pool_name = ? AND status = 'pending'").get(this.name);
    return row.cnt;
  }

  async releaseByWorker(workerId: string): Promise<number> {
    this.db.prepare(`
      UPDATE work_pool SET status = 'pending', claimed_by = NULL, claimed_at = NULL
      WHERE pool_name = ? AND claimed_by = ? AND status = 'claimed'
    `).run(this.name, workerId);
    return this.db.prepare('SELECT changes() as c').get().c;
  }
}

export class SQLiteWorkBackend implements WorkBackend {
  private db: any;
  private _pools = new Map<string, SQLiteWorkPool>();

  constructor(dbPath: string = 'workers.sqlite') {
    let DatabaseSync: any;
    try {
      DatabaseSync = require('node:sqlite').DatabaseSync;
    } catch {
      throw new Error('SQLiteWorkBackend requires Node.js ≥22.5 with built-in node:sqlite module.');
    }
    this.db = new DatabaseSync(dbPath);
    this.db.exec('PRAGMA journal_mode = WAL');
    this.db.exec('PRAGMA busy_timeout = 10000');
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS work_pool (
        item_id TEXT PRIMARY KEY,
        pool_name TEXT NOT NULL,
        data TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        claimed_by TEXT,
        claimed_at TEXT,
        attempts INTEGER NOT NULL DEFAULT 0,
        max_retries INTEGER NOT NULL DEFAULT 3,
        created_at TEXT NOT NULL,
        error TEXT
      );
      CREATE INDEX IF NOT EXISTS idx_work_pool_name ON work_pool(pool_name);
      CREATE INDEX IF NOT EXISTS idx_work_status ON work_pool(status);
      CREATE INDEX IF NOT EXISTS idx_work_claimed_by ON work_pool(claimed_by);
    `);
  }

  pool(name: string): SQLiteWorkPool {
    let p = this._pools.get(name);
    if (!p) { p = new SQLiteWorkPool(name, this.db); this._pools.set(name, p); }
    return p;
  }

  close(): void { this.db.close(); }
}

// ─────────────────────────────────────────────────────────────────────────────
// Factory
// ─────────────────────────────────────────────────────────────────────────────

export function createWorkBackend(type: string = 'memory', opts?: Record<string, any>): WorkBackend {
  if (type === 'memory') return new MemoryWorkBackend();
  if (type === 'sqlite') return new SQLiteWorkBackend(opts?.db_path);
  throw new Error(`Unknown work backend type: ${type}`);
}
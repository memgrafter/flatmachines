/**
 * Distributed backends.
 *
 * Ports Python SDK's distributed.py. Worker registration and lifecycle
 * management with Memory and SQLite backends.
 */

import { randomUUID } from 'node:crypto';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

export interface WorkerRegistration {
  worker_id: string;
  host?: string;
  pid?: number;
  capabilities?: string[];
  pool_id?: string;
  started_at?: string;
}

export interface WorkerRecord extends WorkerRegistration {
  status: string;
  last_heartbeat: string;
  current_task_id?: string;
  metadata?: Record<string, any>;
}

export interface WorkerFilter {
  status?: string | string[];
  capability?: string;
  pool_id?: string;
  stale_threshold_seconds?: number;
}

// ─────────────────────────────────────────────────────────────────────────────
// RegistrationBackend interface
// ─────────────────────────────────────────────────────────────────────────────

export interface RegistrationBackend {
  register(worker: WorkerRegistration): Promise<WorkerRecord>;
  heartbeat(workerId: string, metadata?: Record<string, any>): Promise<void>;
  updateStatus(workerId: string, status: string): Promise<void>;
  get(workerId: string): Promise<WorkerRecord | null>;
  list(filter?: WorkerFilter): Promise<WorkerRecord[]>;
}

// ─────────────────────────────────────────────────────────────────────────────
// MemoryRegistrationBackend
// ─────────────────────────────────────────────────────────────────────────────

export class MemoryRegistrationBackend implements RegistrationBackend {
  private _workers = new Map<string, WorkerRecord>();

  async register(worker: WorkerRegistration): Promise<WorkerRecord> {
    const now = new Date().toISOString();
    const record: WorkerRecord = {
      ...worker,
      status: 'active',
      last_heartbeat: now,
      started_at: worker.started_at ?? now,
    };
    this._workers.set(worker.worker_id, record);
    return record;
  }

  async heartbeat(workerId: string, metadata?: Record<string, any>): Promise<void> {
    const record = this._workers.get(workerId);
    if (!record) throw new Error(`Worker ${workerId} not found`);
    record.last_heartbeat = new Date().toISOString();
    if (metadata) record.metadata = { ...(record.metadata ?? {}), ...metadata };
  }

  async updateStatus(workerId: string, status: string): Promise<void> {
    const record = this._workers.get(workerId);
    if (!record) throw new Error(`Worker ${workerId} not found`);
    record.status = status;
  }

  async get(workerId: string): Promise<WorkerRecord | null> {
    return this._workers.get(workerId) ?? null;
  }

  async list(filter?: WorkerFilter): Promise<WorkerRecord[]> {
    let workers = [...this._workers.values()];
    if (filter) {
      if (filter.status) {
        const statuses = Array.isArray(filter.status) ? filter.status : [filter.status];
        workers = workers.filter(w => statuses.includes(w.status));
      }
      if (filter.capability) {
        workers = workers.filter(w => w.capabilities?.includes(filter.capability!));
      }
      if (filter.pool_id) {
        workers = workers.filter(w => w.pool_id === filter.pool_id);
      }
      if (filter.stale_threshold_seconds) {
        const cutoff = new Date(Date.now() - filter.stale_threshold_seconds * 1000).toISOString();
        workers = workers.filter(w => w.last_heartbeat < cutoff);
      }
    }
    return workers;
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// SQLiteRegistrationBackend
// ─────────────────────────────────────────────────────────────────────────────

export class SQLiteRegistrationBackend implements RegistrationBackend {
  private db: any;

  constructor(dbPath: string = 'workers.sqlite') {
    let DatabaseSync: any;
    try {
      DatabaseSync = require('node:sqlite').DatabaseSync;
    } catch {
      throw new Error('SQLiteRegistrationBackend requires Node.js ≥22.5 with built-in node:sqlite module.');
    }
    this.db = new DatabaseSync(dbPath);
    this.db.exec('PRAGMA journal_mode = WAL');
    this.db.exec('PRAGMA busy_timeout = 10000');
    this._ensureSchema();
  }

  private _ensureSchema(): void {
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS worker_registry (
        worker_id TEXT PRIMARY KEY,
        status TEXT NOT NULL DEFAULT 'active',
        last_heartbeat TEXT NOT NULL,
        host TEXT,
        pid INTEGER,
        capabilities TEXT,
        pool_id TEXT,
        started_at TEXT,
        current_task_id TEXT,
        metadata TEXT
      );
      CREATE INDEX IF NOT EXISTS idx_worker_status ON worker_registry(status);
      CREATE INDEX IF NOT EXISTS idx_worker_heartbeat ON worker_registry(last_heartbeat);
    `);
  }

  private _rowToRecord(row: any): WorkerRecord {
    return {
      worker_id: row.worker_id,
      status: row.status,
      last_heartbeat: row.last_heartbeat,
      host: row.host ?? undefined,
      pid: row.pid ?? undefined,
      capabilities: row.capabilities ? JSON.parse(row.capabilities) : undefined,
      pool_id: row.pool_id ?? undefined,
      started_at: row.started_at ?? undefined,
      current_task_id: row.current_task_id ?? undefined,
      metadata: row.metadata ? JSON.parse(row.metadata) : undefined,
    };
  }

  async register(worker: WorkerRegistration): Promise<WorkerRecord> {
    const now = new Date().toISOString();
    const caps = worker.capabilities ? JSON.stringify(worker.capabilities) : null;
    this.db.prepare(`
      INSERT OR REPLACE INTO worker_registry
      (worker_id, status, last_heartbeat, host, pid, capabilities, pool_id, started_at)
      VALUES (?, 'active', ?, ?, ?, ?, ?, ?)
    `).run(worker.worker_id, now, worker.host ?? null, worker.pid ?? null, caps, worker.pool_id ?? null, worker.started_at ?? now);
    return {
      ...worker,
      status: 'active',
      last_heartbeat: now,
      started_at: worker.started_at ?? now,
    };
  }

  async heartbeat(workerId: string, metadata?: Record<string, any>): Promise<void> {
    const now = new Date().toISOString();
    if (metadata) {
      const row = this.db.prepare('SELECT metadata FROM worker_registry WHERE worker_id = ?').get(workerId);
      if (!row) throw new Error(`Worker ${workerId} not found`);
      const existing = row.metadata ? JSON.parse(row.metadata) : {};
      const merged = { ...existing, ...metadata };
      this.db.prepare('UPDATE worker_registry SET last_heartbeat = ?, metadata = ? WHERE worker_id = ?').run(now, JSON.stringify(merged), workerId);
    } else {
      const result = this.db.prepare('UPDATE worker_registry SET last_heartbeat = ? WHERE worker_id = ?').run(now, workerId);
      if (this.db.prepare('SELECT changes() as c').get().c === 0) throw new Error(`Worker ${workerId} not found`);
    }
  }

  async updateStatus(workerId: string, status: string): Promise<void> {
    this.db.prepare('UPDATE worker_registry SET status = ? WHERE worker_id = ?').run(status, workerId);
  }

  async get(workerId: string): Promise<WorkerRecord | null> {
    const row = this.db.prepare('SELECT * FROM worker_registry WHERE worker_id = ?').get(workerId);
    return row ? this._rowToRecord(row) : null;
  }

  async list(filter?: WorkerFilter): Promise<WorkerRecord[]> {
    let query = 'SELECT * FROM worker_registry WHERE 1=1';
    const params: any[] = [];
    if (filter?.status) {
      const statuses = Array.isArray(filter.status) ? filter.status : [filter.status];
      query += ` AND status IN (${statuses.map(() => '?').join(',')})`;
      params.push(...statuses);
    }
    if (filter?.capability) {
      query += ' AND capabilities LIKE ?';
      params.push(`%"${filter.capability}"%`);
    }
    if (filter?.pool_id) {
      query += ' AND pool_id = ?';
      params.push(filter.pool_id);
    }
    if (filter?.stale_threshold_seconds) {
      const cutoff = new Date(Date.now() - filter.stale_threshold_seconds * 1000).toISOString();
      query += ' AND last_heartbeat < ?';
      params.push(cutoff);
    }
    const rows = this.db.prepare(query).all(...params);
    return rows.map((r: any) => this._rowToRecord(r));
  }

  close(): void { this.db.close(); }
}

// ─────────────────────────────────────────────────────────────────────────────
// Factory
// ─────────────────────────────────────────────────────────────────────────────

export function createRegistrationBackend(type: string = 'memory', opts?: Record<string, any>): RegistrationBackend {
  if (type === 'memory') return new MemoryRegistrationBackend();
  if (type === 'sqlite') return new SQLiteRegistrationBackend(opts?.db_path);
  throw new Error(`Unknown registration backend type: ${type}`);
}

// ─────────────────────────────────────────────────────────────────────────────
// Re-exports for backward compatibility (Python SDK exposes these from distributed module)
// ─────────────────────────────────────────────────────────────────────────────

export {
  MemoryWorkBackend,
  MemoryWorkBackend as WorkBackend,
  SQLiteWorkBackend,
  MemoryWorkPool,
  MemoryWorkPool as WorkPool,
  SQLiteWorkPool,
  createWorkBackend,
} from './work';
// Runtime-accessible WorkItem class for backward compat
export const WorkItem = class WorkItem {
  id: string; data: any; claimed_by?: string; claimed_at?: string;
  attempts: number; max_retries: number; status?: string;
  constructor(opts?: any) {
    this.id = opts?.id ?? ''; this.data = opts?.data;
    this.attempts = opts?.attempts ?? 0; this.max_retries = opts?.max_retries ?? 3;
    this.status = opts?.status;
  }
};
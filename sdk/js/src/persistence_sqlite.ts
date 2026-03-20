/**
 * SQLite persistence backend — Phase 2.4
 *
 * Uses node:sqlite (Node ≥22.5 built-in) for zero-dependency SQLite.
 * Ports Python SDK's SQLiteCheckpointBackend from persistence.py.
 */

import { PersistenceBackend, MachineSnapshot } from './types';

// ─────────────────────────────────────────────────────────────────────────────
// Lazy load node:sqlite — fails gracefully on older Node versions
// ─────────────────────────────────────────────────────────────────────────────

let _DatabaseSync: any = null;

function getDatabaseSync(): any {
  if (_DatabaseSync) return _DatabaseSync;
  try {
    // Dynamic import of built-in module
    const mod = require('node:sqlite');
    _DatabaseSync = mod.DatabaseSync;
    return _DatabaseSync;
  } catch {
    throw new Error(
      'SQLite backends require Node.js ≥22.5 with built-in node:sqlite module. ' +
      'Use MemoryBackend or LocalFileBackend on older Node versions.'
    );
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// SQLiteCheckpointBackend
// ─────────────────────────────────────────────────────────────────────────────

export class SQLiteCheckpointBackend implements PersistenceBackend {
  private db: any;
  private _configStore: SQLiteConfigStore | null = null;

  constructor(dbPath: string = 'flatmachines.sqlite') {
    const DatabaseSync = getDatabaseSync();
    this.db = new DatabaseSync(dbPath);
    this.db.exec('PRAGMA journal_mode = WAL');
    this.db.exec('PRAGMA synchronous = NORMAL');
    this.db.exec('PRAGMA busy_timeout = 10000');
    this._ensureSchema();
  }

  get configStore(): SQLiteConfigStore {
    if (!this._configStore) {
      this._configStore = new SQLiteConfigStore(this.db);
    }
    return this._configStore;
  }

  private _ensureSchema(): void {
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS machine_checkpoints (
        checkpoint_key  TEXT PRIMARY KEY,
        execution_id    TEXT NOT NULL,
        machine_name    TEXT,
        event           TEXT,
        current_state   TEXT,
        waiting_channel TEXT,
        snapshot_json   TEXT NOT NULL,
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
    `);
  }

  private static validateKey(key: string): void {
    if (!key || key.includes('..') || key.startsWith('/')) {
      throw new Error(`Invalid checkpoint key: ${key}`);
    }
  }

  private static executionIdFromKey(key: string): string {
    return key.split('/', 1)[0]!;
  }

  async save(key: string, snapshot: MachineSnapshot): Promise<void> {
    SQLiteCheckpointBackend.validateKey(key);
    const executionId = SQLiteCheckpointBackend.executionIdFromKey(key);
    const now = new Date().toISOString();
    const jsonStr = JSON.stringify(snapshot);

    // latest pointer
    const latestKey = `${executionId}/latest`;
    if (key === latestKey) {
      // Should not happen with our CheckpointManager, but handle gracefully
      return;
    }

    // Save checkpoint
    this.db.exec('BEGIN IMMEDIATE');
    try {
      const insertStmt = this.db.prepare(`
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
      `);
      insertStmt.run(
        key,
        executionId,
        snapshot.machine_name ?? null,
        snapshot.event ?? null,
        snapshot.current_state ?? null,
        snapshot.waiting_channel ?? null,
        jsonStr,
        now,
      );

      // Update latest pointer
      const latestStmt = this.db.prepare(`
        INSERT INTO machine_latest (execution_id, latest_key, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(execution_id) DO UPDATE SET
          latest_key = excluded.latest_key,
          updated_at = excluded.updated_at
      `);
      latestStmt.run(executionId, key, now);

      this.db.exec('COMMIT');
    } catch (e) {
      this.db.exec('ROLLBACK');
      throw e;
    }
  }

  async load(key: string): Promise<MachineSnapshot | null> {
    SQLiteCheckpointBackend.validateKey(key);
    const row = this.db.prepare(
      'SELECT snapshot_json FROM machine_checkpoints WHERE checkpoint_key = ?'
    ).get(key);
    if (!row) return null;
    return JSON.parse(row.snapshot_json) as MachineSnapshot;
  }

  async delete(key: string): Promise<void> {
    SQLiteCheckpointBackend.validateKey(key);
    const executionId = SQLiteCheckpointBackend.executionIdFromKey(key);
    this.db.prepare('DELETE FROM machine_checkpoints WHERE checkpoint_key = ?').run(key);
    this.db.prepare('DELETE FROM machine_latest WHERE execution_id = ? AND latest_key = ?').run(executionId, key);
  }

  async list(prefix: string): Promise<string[]> {
    const rows = this.db.prepare(
      "SELECT checkpoint_key FROM machine_checkpoints WHERE checkpoint_key LIKE ? ORDER BY checkpoint_key"
    ).all(prefix + '%');
    return rows.map((r: any) => r.checkpoint_key);
  }

  async listExecutionIds(options?: { event?: string; waiting_channel?: string }): Promise<string[]> {
    if (!options?.event && !options?.waiting_channel) {
      const rows = this.db.prepare(
        'SELECT DISTINCT execution_id FROM machine_checkpoints ORDER BY execution_id'
      ).all();
      return rows.map((r: any) => r.execution_id);
    }

    const conditions: string[] = [];
    const params: any[] = [];
    if (options?.event) { conditions.push('mc.event = ?'); params.push(options.event); }
    if (options?.waiting_channel) { conditions.push('mc.waiting_channel = ?'); params.push(options.waiting_channel); }
    const where = conditions.join(' AND ');

    const rows = this.db.prepare(`
      SELECT ml.execution_id
      FROM machine_latest ml
      JOIN machine_checkpoints mc ON mc.checkpoint_key = ml.latest_key
      WHERE ${where}
      ORDER BY ml.execution_id
    `).all(...params);
    return rows.map((r: any) => r.execution_id);
  }

  async deleteExecution(executionId: string): Promise<void> {
    SQLiteCheckpointBackend.validateKey(executionId);
    this.db.prepare('DELETE FROM machine_checkpoints WHERE execution_id = ?').run(executionId);
    this.db.prepare('DELETE FROM machine_latest WHERE execution_id = ?').run(executionId);
  }

  /**
   * Load the latest checkpoint for an execution.
   */
  async loadLatest(executionId: string): Promise<MachineSnapshot | null> {
    const row = this.db.prepare(
      'SELECT latest_key FROM machine_latest WHERE execution_id = ?'
    ).get(executionId);
    if (!row) return null;
    return this.load(row.latest_key);
  }

  close(): void {
    this.db.close();
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// SQLiteConfigStore — Phase 3.6
// ─────────────────────────────────────────────────────────────────────────────

export function configHash(raw: string): string {
  const { createHash } = require('crypto');
  return createHash('sha256').update(raw, 'utf-8').digest('hex');
}

export interface ConfigStore {
  put(raw: string): Promise<string>;
  get(hashKey: string): Promise<string | null>;
  delete(hashKey: string): Promise<void>;
}

export class MemoryConfigStore implements ConfigStore {
  private _store = new Map<string, string>();

  async put(raw: string): Promise<string> {
    const h = configHash(raw);
    this._store.set(h, raw);
    return h;
  }

  async get(hashKey: string): Promise<string | null> {
    return this._store.get(hashKey) ?? null;
  }

  async delete(hashKey: string): Promise<void> {
    this._store.delete(hashKey);
  }
}

export class LocalFileConfigStore implements ConfigStore {
  private dir: string;

  constructor(baseDir = '.checkpoints') {
    const { mkdirSync, existsSync: ex } = require('fs');
    this.dir = require('path').join(baseDir, '_configs');
    if (!ex(this.dir)) mkdirSync(this.dir, { recursive: true });
  }

  async put(raw: string): Promise<string> {
    const { writeFileSync, existsSync: ex, renameSync } = require('fs');
    const { join } = require('path');
    const h = configHash(raw);
    const path = join(this.dir, `${h}.yml`);
    if (!ex(path)) {
      const tmp = `${path}.tmp`;
      writeFileSync(tmp, raw, 'utf-8');
      renameSync(tmp, path);
    }
    return h;
  }

  async get(hashKey: string): Promise<string | null> {
    const { readFileSync, existsSync: ex } = require('fs');
    const path = require('path').join(this.dir, `${hashKey}.yml`);
    if (!ex(path)) return null;
    return readFileSync(path, 'utf-8');
  }

  async delete(hashKey: string): Promise<void> {
    const { unlinkSync, existsSync: ex } = require('fs');
    const path = require('path').join(this.dir, `${hashKey}.yml`);
    if (ex(path)) unlinkSync(path);
  }
}

export class SQLiteConfigStore implements ConfigStore {
  private db: any;

  constructor(db: any) {
    this.db = db;
    this._ensureSchema();
  }

  private _ensureSchema(): void {
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS machine_configs (
        config_hash  TEXT PRIMARY KEY,
        machine_name TEXT,
        spec_version TEXT,
        config_raw   TEXT NOT NULL,
        created_at   TEXT NOT NULL
      );
    `);
  }

  async put(raw: string): Promise<string> {
    const h = configHash(raw);
    const now = new Date().toISOString();
    let machineName: string | null = null;
    let specVersion: string | null = null;
    try {
      const yaml = require('yaml');
      const parsed = yaml.parse(raw);
      if (parsed && typeof parsed === 'object') {
        machineName = parsed.data?.name ?? null;
        specVersion = parsed.spec_version ?? null;
      }
    } catch { /* ignore parse errors */ }

    this.db.prepare(`
      INSERT INTO machine_configs (config_hash, machine_name, spec_version, config_raw, created_at)
      VALUES (?, ?, ?, ?, ?)
      ON CONFLICT(config_hash) DO NOTHING
    `).run(h, machineName, specVersion, raw, now);
    return h;
  }

  async get(hashKey: string): Promise<string | null> {
    const row = this.db.prepare(
      'SELECT config_raw FROM machine_configs WHERE config_hash = ?'
    ).get(hashKey);
    return row ? row.config_raw : null;
  }

  async delete(hashKey: string): Promise<void> {
    this.db.prepare('DELETE FROM machine_configs WHERE config_hash = ?').run(hashKey);
  }
}

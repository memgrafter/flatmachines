/**
 * Signal and trigger backends.
 *
 * Ports Python SDK's signals.py. Provides durable signal storage and
 * trigger backends for cross-process machine activation.
 */

import { randomUUID } from 'node:crypto';
import { mkdirSync, writeFileSync } from 'fs';
import { join } from 'path';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

export interface Signal {
  id: string;
  channel: string;
  data: any;
  created_at: string;
}

// ─────────────────────────────────────────────────────────────────────────────
// Signal Backend
// ─────────────────────────────────────────────────────────────────────────────

export interface SignalBackend {
  send(channel: string, data: any): Promise<string>;
  consume(channel: string): Promise<Signal | null>;
  peek(channel: string): Promise<Signal[]>;
  channels(): Promise<string[]>;
}

// ─────────────────────────────────────────────────────────────────────────────
// Trigger Backend
// ─────────────────────────────────────────────────────────────────────────────

export interface TriggerBackend {
  notify(channel: string): Promise<void>;
}

// ─────────────────────────────────────────────────────────────────────────────
// Memory Signal Backend
// ─────────────────────────────────────────────────────────────────────────────

export class MemorySignalBackend implements SignalBackend {
  private _channels = new Map<string, Signal[]>();

  async send(channel: string, data: any): Promise<string> {
    const id = randomUUID();
    const sig: Signal = { id, channel, data, created_at: new Date().toISOString() };
    let queue = this._channels.get(channel);
    if (!queue) { queue = []; this._channels.set(channel, queue); }
    queue.push(sig);
    return id;
  }

  async consume(channel: string): Promise<Signal | null> {
    const queue = this._channels.get(channel);
    if (!queue?.length) return null;
    const sig = queue.shift()!;
    if (!queue.length) this._channels.delete(channel);
    return sig;
  }

  async peek(channel: string): Promise<Signal[]> {
    return [...(this._channels.get(channel) ?? [])];
  }

  async channels(): Promise<string[]> {
    return [...this._channels.keys()].filter(ch => (this._channels.get(ch)?.length ?? 0) > 0).sort();
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// SQLite Signal Backend
// ─────────────────────────────────────────────────────────────────────────────

export class SQLiteSignalBackend implements SignalBackend {
  private db: any;

  constructor(dbPath: string = 'flatmachines.sqlite') {
    // Dynamic require for optional built-in module (node:sqlite requires Node ≥22.5)
    let DatabaseSync: any;
    try {
      DatabaseSync = require('node:sqlite').DatabaseSync;
    } catch {
      throw new Error('SQLite signal backend requires Node.js ≥22.5 with built-in node:sqlite module.');
    }
    this.db = new DatabaseSync(dbPath);
    this.db.exec('PRAGMA journal_mode = WAL');
    this.db.exec('PRAGMA synchronous = NORMAL');
    this.db.exec('PRAGMA busy_timeout = 10000');
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS signals (
        id TEXT PRIMARY KEY,
        channel TEXT NOT NULL,
        data_json TEXT NOT NULL,
        created_at TEXT NOT NULL
      );
      CREATE INDEX IF NOT EXISTS idx_signals_channel
        ON signals(channel, created_at ASC);
    `);
  }

  async send(channel: string, data: any): Promise<string> {
    const id = randomUUID();
    const now = new Date().toISOString();
    this.db.prepare(
      'INSERT INTO signals (id, channel, data_json, created_at) VALUES (?, ?, ?, ?)'
    ).run(id, channel, JSON.stringify(data), now);
    return id;
  }

  async consume(channel: string): Promise<Signal | null> {
    this.db.exec('BEGIN IMMEDIATE');
    try {
      const row = this.db.prepare(
        'SELECT * FROM signals WHERE channel = ? ORDER BY created_at ASC LIMIT 1'
      ).get(channel);
      if (!row) { this.db.exec('COMMIT'); return null; }
      this.db.prepare('DELETE FROM signals WHERE id = ?').run(row.id);
      this.db.exec('COMMIT');
      return { id: row.id, channel: row.channel, data: JSON.parse(row.data_json), created_at: row.created_at };
    } catch (e) {
      this.db.exec('ROLLBACK');
      throw e;
    }
  }

  async peek(channel: string): Promise<Signal[]> {
    const rows = this.db.prepare(
      'SELECT * FROM signals WHERE channel = ? ORDER BY created_at ASC'
    ).all(channel);
    return rows.map((r: any) => ({ id: r.id, channel: r.channel, data: JSON.parse(r.data_json), created_at: r.created_at }));
  }

  async channels(): Promise<string[]> {
    const rows = this.db.prepare('SELECT DISTINCT channel FROM signals ORDER BY channel').all();
    return rows.map((r: any) => r.channel);
  }

  close(): void { this.db.close(); }
}

// ─────────────────────────────────────────────────────────────────────────────
// Trigger Backends
// ─────────────────────────────────────────────────────────────────────────────

export class NoOpTrigger implements TriggerBackend {
  async notify(_channel: string): Promise<void> {}
}

export class FileTrigger implements TriggerBackend {
  private basePath: string;

  constructor(basePath: string = '/tmp/flatmachines') {
    this.basePath = basePath;
  }

  async notify(_channel: string): Promise<void> {
    mkdirSync(this.basePath, { recursive: true });
    const triggerFile = join(this.basePath, 'trigger');
    writeFileSync(triggerFile, '');
  }
}

export class SocketTrigger implements TriggerBackend {
  private socketPath: string;

  constructor(socketPath: string = '/tmp/flatmachines/trigger.sock') {
    this.socketPath = socketPath;
  }

  async notify(channel: string): Promise<void> {
    try {
      // Use UDP datagram socket for one-shot fire-and-forget notification.
      // The OS socket queue buffers the message until the dispatcher reads it.
      const dgram = require('node:dgram');
      const socket = dgram.createSocket('unix_dgram');
      await new Promise<void>((resolve) => {
        socket.send(Buffer.from(channel, 'utf-8'), this.socketPath, () => {
          socket.close();
          resolve();
        });
      });
    } catch {
      // No dispatcher listening — signal is still in the backend
    }
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Factories
// ─────────────────────────────────────────────────────────────────────────────

export function createSignalBackend(type: string = 'memory', opts?: Record<string, any>): SignalBackend {
  if (type === 'memory') return new MemorySignalBackend();
  if (type === 'sqlite') return new SQLiteSignalBackend(opts?.db_path);
  throw new Error(`Unknown signal backend type: ${type}`);
}

export function createTriggerBackend(type: string = 'none', opts?: Record<string, any>): TriggerBackend {
  if (type === 'none') return new NoOpTrigger();
  if (type === 'file') return new FileTrigger(opts?.base_path);
  if (type === 'socket') return new SocketTrigger(opts?.socket_path);
  throw new Error(`Unknown trigger backend type: ${type}`);
}

// ─────────────────────────────────────────────────────────────────────────────
// Helper — Phase 4.7
// ─────────────────────────────────────────────────────────────────────────────

export async function sendAndNotify(
  signalBackend: SignalBackend,
  triggerBackend: TriggerBackend,
  channel: string,
  data: any,
): Promise<string> {
  const id = await signalBackend.send(channel, data);
  await triggerBackend.notify(channel);
  return id;
}
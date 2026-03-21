import { PersistenceBackend, MachineSnapshot } from './types';
import { promises as fs } from 'fs';
import { join, dirname } from 'path';

export class MemoryBackend implements PersistenceBackend {
  private store = new Map<string, MachineSnapshot>();

  async save(key: string, snapshot: MachineSnapshot): Promise<void> {
    // Deep clone via JSON to strip frozen objects and break references
    this.store.set(key, JSON.parse(JSON.stringify(snapshot)));
  }

  async load(key: string): Promise<MachineSnapshot | null> {
    const s = this.store.get(key);
    return s ? JSON.parse(JSON.stringify(s)) : null;
  }

  async delete(key: string): Promise<void> {
    this.store.delete(key);
  }

  async list(prefix: string): Promise<string[]> {
    return [...this.store.keys()].filter(k => k.startsWith(prefix)).sort();
  }

  async listExecutionIds(options?: { event?: string; waiting_channel?: string }): Promise<string[]> {
    // Find all unique execution IDs by scanning latest checkpoint per execution
    // Use key ordering as tiebreaker (later keys = more recent)
    const execMap = new Map<string, { key: string; snapshot: MachineSnapshot }>();
    for (const [key, snapshot] of this.store.entries()) {
      // Skip non-snapshot entries (e.g., latest pointers stored as strings)
      if (!snapshot || typeof snapshot !== 'object' || !snapshot.execution_id) continue;
      const eid = snapshot.execution_id;
      const existing = execMap.get(eid);
      if (!existing || (snapshot.step ?? 0) > (existing.snapshot.step ?? 0) ||
          ((snapshot.step ?? 0) === (existing.snapshot.step ?? 0) && key > existing.key)) {
        execMap.set(eid, { key, snapshot });
      }
    }

    const results: string[] = [];
    for (const [eid, { snapshot }] of execMap.entries()) {
      if (options?.waiting_channel != null) {
        if ((snapshot as any).waiting_channel !== options.waiting_channel) continue;
      }
      if (options?.event != null && options.event !== null) {
        if ((snapshot as any).event !== options.event) continue;
      }
      results.push(eid);
    }
    return results.sort();
  }

  async deleteExecution(executionId: string): Promise<void> {
    for (const key of [...this.store.keys()]) {
      if (key.startsWith(executionId + '/') || key === executionId) {
        this.store.delete(key);
      }
    }
  }
}

export class LocalFileBackend implements PersistenceBackend {
  constructor(private dir = ".checkpoints") { }

  private async ensureDir(path: string): Promise<void> {
    try {
      await fs.mkdir(dirname(path), { recursive: true });
    } catch (error) {
      // Directory might already exist
    }
  }

  private getPath(key: string): string {
    return join(this.dir, `${key}.json`);
  }

  async save(key: string, snapshot: MachineSnapshot): Promise<void> {
    const path = this.getPath(key);
    await this.ensureDir(path);
    const tempPath = `${path}.tmp`;

    // Write to temp file first, then rename for atomicity
    await fs.writeFile(tempPath, JSON.stringify(snapshot, null, 2));
    await fs.rename(tempPath, path);
  }

  async load(key: string): Promise<MachineSnapshot | null> {
    try {
      const path = this.getPath(key);
      const data = await fs.readFile(path, 'utf-8');
      return JSON.parse(data) as MachineSnapshot;
    } catch (error) {
      return null;
    }
  }

  async delete(key: string): Promise<void> {
    try {
      const path = this.getPath(key);
      await fs.unlink(path);
    } catch (error) {
      // File might not exist
    }
  }

  async list(prefix: string): Promise<string[]> {
    try {
      const files = await fs.readdir(this.dir, { recursive: true }) as string[];
      return files
        .filter((file: string) => file.endsWith('.json'))
        .map((file: string) => file.replace('.json', ''))
        .filter((key: string) => key.startsWith(prefix))
        .sort();
    } catch (error) {
      return [];
    }
  }

  async listExecutionIds(options?: { event?: string; waiting_channel?: string }): Promise<string[]> {
    // List all files, group by execution ID, check latest
    const allKeys = await this.list('');
    const execMap = new Map<string, { key: string; snapshot: MachineSnapshot }>();
    for (const key of allKeys) {
      const snapshot = await this.load(key);
      if (!snapshot || !snapshot.execution_id) continue;
      const eid = snapshot.execution_id;
      const existing = execMap.get(eid);
      if (!existing || (snapshot.step ?? 0) > (existing.snapshot.step ?? 0) ||
          ((snapshot.step ?? 0) === (existing.snapshot.step ?? 0) && key > existing.key)) {
        execMap.set(eid, { key, snapshot });
      }
    }
    const results: string[] = [];
    for (const [eid, { snapshot }] of execMap.entries()) {
      if (options?.waiting_channel != null) {
        if ((snapshot as any).waiting_channel !== options.waiting_channel) continue;
      }
      if (options?.event != null && options.event !== null) {
        if ((snapshot as any).event !== options.event) continue;
      }
      results.push(eid);
    }
    return results.sort();
  }

  async deleteExecution(executionId: string): Promise<void> {
    const keys = await this.list(executionId);
    for (const key of keys) {
      await this.delete(key);
    }
  }
}

/**
 * Clone a snapshot under a new execution ID and persist it. (#20)
 */
export async function cloneSnapshot(
  snapshot: MachineSnapshot,
  newExecutionId: string,
  persistence: PersistenceBackend,
): Promise<MachineSnapshot> {
  const cloned: MachineSnapshot = {
    ...JSON.parse(JSON.stringify(snapshot)),
    execution_id: newExecutionId,
    created_at: new Date().toISOString(),
    parent_execution_id: snapshot.execution_id,
    pending_launches: undefined,
  };
  const manager = new CheckpointManager(persistence);
  await manager.checkpoint(cloned);
  return cloned;
}

export class CheckpointManager {
  private _executionId?: string;

  constructor(private backend: PersistenceBackend, executionId?: string) {
    this._executionId = executionId;
  }

  async checkpoint(snapshot: MachineSnapshot): Promise<void> {
    const eventSuffix = snapshot.event ? `_${snapshot.event}` : '';
    const key = `${snapshot.execution_id}/step_${String(snapshot.step).padStart(6, "0")}${eventSuffix}`;
    await this.backend.save(key, snapshot);
  }

  async restore(executionId?: string): Promise<MachineSnapshot | null> {
    const eid = executionId ?? this._executionId;
    if (!eid) throw new Error('executionId is required');
    const keys = await this.backend.list(eid);
    if (!keys.length) return null;
    // Filter out 'latest' entries and sort by step
    const checkpointKeys = keys.filter(k => !k.endsWith('/latest'));
    if (!checkpointKeys.length) return null;
    const sortedKeys = checkpointKeys.sort();
    return this.backend.load(sortedKeys[sortedKeys.length - 1]!);
  }

  /**
   * Load status (event, current_state) from the latest checkpoint.
   */
  async loadStatus(): Promise<[string, string] | null> {
    const snapshot = await this.restore();
    if (!snapshot) return null;
    return [snapshot.event ?? 'unknown', snapshot.current_state];
  }

  /**
   * Load the latest checkpoint for the configured execution ID.
   * Alias for restore().
   */
  async loadLatest(): Promise<MachineSnapshot | null> {
    return this.restore();
  }

  /**
   * Access the underlying persistence backend.
   */
  get persistenceBackend(): PersistenceBackend {
    return this.backend;
  }

  /**
   * Safely serialize an object to JSON, converting non-serializable values.
   * Logs warnings for fields that needed conversion.
   */
  _safe_serialize(obj: any): string {
    return JSON.stringify(obj, (_key, value) => {
      if (value instanceof Date) return value.toISOString();
      if (typeof value === 'function') return '<function>';
      if (typeof value === 'bigint') return value.toString();
      if (value instanceof RegExp) return value.toString();
      if (value instanceof Map) return Object.fromEntries(value);
      if (value instanceof Set) return [...value];
      return value;
    });
  }
}

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
    const execMap = new Map<string, MachineSnapshot>();
    for (const [key, snapshot] of this.store.entries()) {
      const eid = snapshot.execution_id;
      const existing = execMap.get(eid);
      if (!existing || snapshot.step > existing.step) {
        execMap.set(eid, snapshot);
      }
    }

    const results: string[] = [];
    for (const [eid, snapshot] of execMap.entries()) {
      if (options?.waiting_channel != null) {
        if ((snapshot as any).waiting_channel !== options.waiting_channel) continue;
      }
      if (options?.event != null) {
        if ((snapshot as any).event !== options.event) continue;
      }
      results.push(eid);
    }
    return results;
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
  constructor(private backend: PersistenceBackend) { }

  async checkpoint(snapshot: MachineSnapshot): Promise<void> {
    const key = `${snapshot.execution_id}/step_${String(snapshot.step).padStart(6, "0")}`;
    await this.backend.save(key, snapshot);
  }

  async restore(executionId: string): Promise<MachineSnapshot | null> {
    const keys = await this.backend.list(executionId);
    if (!keys.length) return null;
    // Return the latest checkpoint (highest step number)
    const sortedKeys = keys.sort((a, b) => {
      const stepA = parseInt(a.split('_')[1] || '0');
      const stepB = parseInt(b.split('_')[1] || '0');
      return stepA - stepB;
    });
    return this.backend.load(sortedKeys[sortedKeys.length - 1]!);
  }
}

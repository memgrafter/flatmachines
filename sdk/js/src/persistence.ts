import { PersistenceBackend, MachineSnapshot } from './types';
import { promises as fs } from 'fs';
import { join, dirname } from 'path';

export class MemoryBackend implements PersistenceBackend {
  private store = new Map<string, MachineSnapshot>();
  
  async save(key: string, snapshot: MachineSnapshot): Promise<void> {
    this.store.set(key, snapshot);
  }
  
  async load(key: string): Promise<MachineSnapshot | null> {
    return this.store.get(key) ?? null;
  }
  
  async delete(key: string): Promise<void> {
    this.store.delete(key);
  }
  
  async list(prefix: string): Promise<string[]> {
    return [...this.store.keys()].filter(k => k.startsWith(prefix));
  }
}

export class LocalFileBackend implements PersistenceBackend {
  constructor(private dir = ".checkpoints") {}
  
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
        .filter((key: string) => key.startsWith(prefix));
    } catch (error) {
      return [];
    }
  }
}

export class CheckpointManager {
  constructor(private backend: PersistenceBackend) {}
  
  async checkpoint(snapshot: MachineSnapshot): Promise<void> {
    const key = `${snapshot.executionId}/step_${String(snapshot.step).padStart(6, "0")}`;
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
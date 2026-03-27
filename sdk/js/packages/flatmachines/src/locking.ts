import type { ExecutionLock } from './types';
import { promises as fs } from 'fs';
import { join, dirname } from 'path';

/**
 * NoOpLock - Always acquires the lock.
 * Use when locking is handled externally or disabled.
 *
 * Required by flatagents-runtime.d.ts spec.
 */
export class NoOpLock implements ExecutionLock {
  async acquire(key: string): Promise<boolean> {
    return true;
  }

  async release(key: string): Promise<void> {
    // No-op
  }
}

/**
 * LocalFileLock - File-based locking for single-node deployments.
 * Uses exclusive file creation to prevent concurrent execution.
 *
 * Recommended by flatagents-runtime.d.ts spec.
 */
export class LocalFileLock implements ExecutionLock {
  private lockDir: string;
  private handles = new Map<string, fs.FileHandle>();

  constructor(lockDir = '.locks') {
    this.lockDir = lockDir;
  }

  private getLockPath(key: string): string {
    // Sanitize key to be filesystem-safe
    const safeKey = key.replace(/[^a-zA-Z0-9_-]/g, '_');
    return join(this.lockDir, `${safeKey}.lock`);
  }

  private async ensureDir(): Promise<void> {
    try {
      await fs.mkdir(this.lockDir, { recursive: true });
    } catch (error) {
      // Directory might already exist
    }
  }

  async acquire(key: string): Promise<boolean> {
    await this.ensureDir();
    const lockPath = this.getLockPath(key);

    try {
      // Use 'wx' flag: create exclusively, fail if exists
      const handle = await fs.open(lockPath, 'wx');

      // Write process info for debugging
      await handle.write(JSON.stringify({
        pid: process.pid,
        key,
        acquired_at: new Date().toISOString()
      }));

      this.handles.set(key, handle);
      return true;
    } catch (error: any) {
      if (error.code === 'EEXIST') {
        // Lock already held by another process
        return false;
      }
      throw error;
    }
  }

  async release(key: string): Promise<void> {
    const handle = this.handles.get(key);
    const lockPath = this.getLockPath(key);

    if (handle) {
      await handle.close();
      this.handles.delete(key);
    }

    try {
      await fs.unlink(lockPath);
    } catch (error) {
      // File might not exist
    }
  }
}
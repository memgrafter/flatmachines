// persistence_sqlite.test.ts
// Unit tests for SQLiteCheckpointBackend prune functionality

import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { mkdtempSync, existsSync, rmSync } from 'fs';
import { join } from 'path';
import { tmpdir } from 'os';
import { SQLiteCheckpointBackend } from '@memgrafter/flatmachines';
import { MachineSnapshot } from '@memgrafter/flatagents';

const makeTempDb = () => join(mkdtempSync(join(tmpdir(), 'flatmachines-sqlite-prune-')), 'test.sqlite');

function makeSnapshot(executionId: string, step: number, created_at: string): MachineSnapshot {
  return {
    execution_id: executionId,
    machine_name: 'test-machine',
    current_state: 'test-state',
    context: {},
    step,
    created_at,
  };
}

describe('SQLiteCheckpointBackend - Prune', () => {
  let dbPath: string;
  let tmpDir: string;
  let backend: SQLiteCheckpointBackend;

  beforeEach(() => {
    tmpDir = mkdtempSync(join(tmpdir(), 'flatmachines-sqlite-prune-'));
    dbPath = join(tmpDir, 'test.sqlite');
    backend = new SQLiteCheckpointBackend(dbPath);
  });

  afterEach(() => {
    backend.close();
    if (existsSync(tmpDir)) {
      rmSync(tmpDir, { recursive: true, force: true });
    }
  });

  it('should prune executions by age', async () => {
    await backend.save('old-exec/step_000001', makeSnapshot('old-exec', 1, '2026-01-01T00:00:00.000Z'));
    await backend.save('recent-exec/step_000001', makeSnapshot('recent-exec', 1, new Date().toISOString()));

    const deleted = await backend.prune({ max_age_seconds: 3600 });
    expect(deleted).toBe(1);

    const remaining = await backend.list('old-exec');
    expect(remaining).toHaveLength(0);

    const recentKeys = await backend.list('recent-exec');
    expect(recentKeys).toHaveLength(1);
  });

  it('should prune executions by count', async () => {
    for (let i = 1; i <= 5; i++) {
      const dateStr = `2026-06-0${i}T00:00:00.000Z`;
      await backend.save(`exec-${i}/step_000001`, makeSnapshot(`exec-${i}`, 1, dateStr));
    }

    const deleted = await backend.prune({ max_count: 3 });
    expect(deleted).toBe(2);

    const allKeys = await backend.list('');
    expect(allKeys).toHaveLength(3);
  });

  it('should return 0 when nothing matches', async () => {
    await backend.save('exec-1/step_000001', makeSnapshot('exec-1', 1, new Date().toISOString()));

    const deleted = await backend.prune({ max_age_seconds: 3600 });
    expect(deleted).toBe(0);
  });

  it('should not affect unrelated executions', async () => {
    await backend.save('keep/step_000001', makeSnapshot('keep', 1, new Date().toISOString()));
    await backend.save('prune-me/step_000001', makeSnapshot('prune-me', 1, '2026-01-01T00:00:00.000Z'));

    await backend.prune({ max_age_seconds: 3600 });

    const keep = await backend.load('keep/step_000001');
    expect(keep).not.toBeNull();

    const pruned = await backend.load('prune-me/step_000001');
    expect(pruned).toBeNull();
  });

  it('should prune by age and count combined', async () => {
    const now = Date.now();
    // Old executions that will be age-pruned
    await backend.save('old-1/step_000001', makeSnapshot('old-1', 1, new Date(now - 120_000).toISOString()));
    await backend.save('old-2/step_000001', makeSnapshot('old-2', 1, new Date(now - 90_000).toISOString()));
    // Newer executions that should survive
    await backend.save('new-1/step_000001', makeSnapshot('new-1', 1, new Date(now - 10_000).toISOString()));
    await backend.save('new-2/step_000001', makeSnapshot('new-2', 1, new Date(now - 5_000).toISOString()));
    await backend.save('new-3/step_000001', makeSnapshot('new-3', 1, new Date(now).toISOString()));

    const deleted = await backend.prune({ max_age_seconds: 30, max_count: 2 });
    // Age: old-1, old-2 (older than 30s) = 2
    // Count: new-1, new-2, new-3 remain after age. Keep 2 most recent = new-2, new-3. new-1 is also deleted.
    // Total deleted: 3
    expect(deleted).toBe(3);

    const allKeys = await backend.list('');
    expect(allKeys).toHaveLength(2); // new-2 and new-3
  });
});

import { createRequire } from 'node:module'
import { existsSync, mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

import {
  FlatMachine,
  LocalFileBackend,
  LocalFileLock,
  MemoryBackend,
  MemoryConfigStore,
  NoOpLock,
  SQLiteCheckpointBackend,
  SQLiteLeaseLock,
  type MachineConfig,
  type MachineSnapshot,
} from '../../src'

const require = createRequire(import.meta.url)
const { DatabaseSync } = require('node:sqlite') as {
  DatabaseSync: new (path: string) => any
}

const SQLITE_PERSISTENCE_CONFIG_FILE = 'sdk/python/tests/unit/test_sqlite_persistence_config.py'
const SQLITE_CHECKPOINT_BACKEND_FILE = 'sdk/python/tests/unit/test_sqlite_checkpoint_backend.py'
const SQLITE_LEASE_LOCK_FILE = 'sdk/python/tests/unit/test_sqlite_lease_lock.py'
const BACKEND_LIFECYCLE_FILE = 'sdk/python/tests/unit/test_backend_lifecycle.py'

const createTempDir = (prefix: string): string => mkdtempSync(join(tmpdir(), prefix))

const cleanupDir = (dir: string): void => {
  rmSync(dir, { recursive: true, force: true })
}

const closeMaybe = (value: unknown): void => {
  if (value && typeof (value as any).close === 'function') {
    ;(value as any).close()
  }
}

const minimalMachineConfig = (persistenceConfig?: Record<string, unknown>): MachineConfig => ({
  spec: 'flatmachine',
  spec_version: '2.2.1',
  data: {
    name: 'test-sqlite-persistence',
    states: {
      start: {
        type: 'initial',
        transitions: [{ to: 'done' }],
      },
      done: {
        type: 'final',
        output: { result: 'ok' },
      },
    },
    ...(persistenceConfig ? { persistence: persistenceConfig as any } : {}),
  },
})

const makeSnapshot = (
  executionId: string,
  step = 1,
  event = 'execute',
  waitingChannel?: string,
): MachineSnapshot => ({
  execution_id: executionId,
  machine_name: 'parity-machine',
  spec_version: '2.2.1',
  current_state: 'running',
  context: {
    fake: true,
    event,
    ...(waitingChannel ? { waiting_channel: waitingChannel } : {}),
  },
  step,
  created_at: '2026-03-20T08:38:22.000Z',
  event,
  ...(waitingChannel ? { waiting_channel: waitingChannel } : {}),
})

const createSQLiteCheckpoint = () => {
  const dir = createTempDir('parity-persistence-config-sqlite-')
  const dbPath = join(dir, 'checkpoints.sqlite')
  const backend = new SQLiteCheckpointBackend(dbPath)
  return {
    backend,
    dbPath,
    cleanup: () => {
      closeMaybe(backend)
      cleanupDir(dir)
    },
  }
}

const stopHeartbeat = (lock: SQLiteLeaseLock, executionId: string): void => {
  const timers = (lock as any)._heartbeatTimers as Map<string, ReturnType<typeof setInterval>>
  const timer = timers.get(executionId)
  if (timer) {
    clearInterval(timer)
    timers.delete(executionId)
  }
}

type LifecycleBackendKind = 'local' | 'memory' | 'sqlite'

const createLifecycleBackend = (kind: LifecycleBackendKind) => {
  const dir = createTempDir(`parity-backend-lifecycle-${kind}-`)

  if (kind === 'local') {
    const backend = new LocalFileBackend(join(dir, '.checkpoints'))
    return {
      backend,
      cleanup: () => {
        cleanupDir(dir)
      },
    }
  }

  if (kind === 'memory') {
    const backend = new MemoryBackend()
    return {
      backend,
      cleanup: () => {
        cleanupDir(dir)
      },
    }
  }

  const backend = new SQLiteCheckpointBackend(join(dir, 'lifecycle.sqlite'))
  return {
    backend,
    cleanup: () => {
      closeMaybe(backend)
      cleanupDir(dir)
    },
  }
}

const listExecutionIdsOrThrow = async (
  backend: any,
  options?: { event?: string; waiting_channel?: string },
): Promise<string[]> => {
  if (typeof backend.listExecutionIds !== 'function') {
    throw new Error('listExecutionIds() is not implemented on backend')
  }
  return backend.listExecutionIds(options)
}

const deleteExecutionOrThrow = async (backend: any, executionId: string): Promise<void> => {
  if (typeof backend.deleteExecution !== 'function') {
    throw new Error('deleteExecution() is not implemented on backend')
  }
  await backend.deleteExecution(executionId)
}

const writeLifecycleCheckpoint = async (
  backend: any,
  executionId: string,
  step = 1,
  event = 'execute',
  waitingChannel?: string,
): Promise<void> => {
  const key = `${executionId}/step_${String(step).padStart(6, '0')}_${event}.json`
  await backend.save(key, makeSnapshot(executionId, step, event, waitingChannel))
  await backend.save(`${executionId}/latest`, key as any)
}

const runLifecycleCase = async (
  runCase: (backend: any, kind: LifecycleBackendKind) => Promise<void>,
): Promise<void> => {
  const failures: string[] = []

  for (const kind of ['local', 'memory', 'sqlite'] as const) {
    const { backend, cleanup } = createLifecycleBackend(kind)
    try {
      await runCase(backend, kind)
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      failures.push(`[${kind}] ${message}`)
    } finally {
      cleanup()
    }
  }

  if (failures.length) {
    throw new Error(`Backend parity failures:\n${failures.join('\n')}`)
  }
}

describe('python parity :: sqlite persistence config', () => {
  it(`${SQLITE_PERSISTENCE_CONFIG_FILE}::TestSqliteBackendInitialization.test_persistence_config_sqlite_initializes_sqlite_backend`, () => {
    const dir = createTempDir('parity-persistence-config-machine-')
    const dbPath = join(dir, 'state.db')
    let backend: unknown

    try {
      const machine = new FlatMachine({
        config: minimalMachineConfig({ enabled: true, backend: 'sqlite', db_path: dbPath }),
      })

      backend = (machine as any).checkpointManager?.backend

      expect(backend).toBeInstanceOf(SQLiteCheckpointBackend)
      expect((backend as any).db.location()).toBe(resolve(dbPath))
    } finally {
      closeMaybe(backend)
      cleanupDir(dir)
    }
  })

  it(`${SQLITE_PERSISTENCE_CONFIG_FILE}::TestSqliteBackendInitialization.test_persistence_config_sqlite_default_db_path`, () => {
    const dir = createTempDir('parity-persistence-config-default-path-')
    const prevCwd = process.cwd()
    let backend: unknown

    process.chdir(dir)
    try {
      const machine = new FlatMachine({
        config: minimalMachineConfig({ enabled: true, backend: 'sqlite' }),
      })

      backend = (machine as any).checkpointManager?.backend

      expect(backend).toBeInstanceOf(SQLiteCheckpointBackend)
      expect((backend as any).db.location()).toContain('flatmachines.sqlite')
    } finally {
      process.chdir(prevCwd)
      closeMaybe(backend)
      cleanupDir(dir)
    }
  })

  it(`${SQLITE_PERSISTENCE_CONFIG_FILE}::TestSqliteAutoLock.test_persistence_config_sqlite_auto_lock_is_sqlite_lease`, () => {
    const dir = createTempDir('parity-persistence-config-auto-lock-')
    const dbPath = join(dir, 'state.db')
    let backend: unknown
    let lock: unknown

    try {
      const machine = new FlatMachine({
        config: minimalMachineConfig({ enabled: true, backend: 'sqlite', db_path: dbPath }),
      })

      backend = (machine as any).checkpointManager?.backend
      lock = (machine as any).executionLock

      expect(backend).toBeInstanceOf(SQLiteCheckpointBackend)
      expect(lock).toBeInstanceOf(SQLiteLeaseLock)
    } finally {
      closeMaybe(lock)
      closeMaybe(backend)
      cleanupDir(dir)
    }
  })

  it(`${SQLITE_PERSISTENCE_CONFIG_FILE}::TestSqliteAutoLock.test_sqlite_lock_uses_same_db_path`, () => {
    const dir = createTempDir('parity-persistence-config-lock-path-')
    const dbPath = join(dir, 'state.db')
    let backend: unknown
    let lock: unknown

    try {
      const machine = new FlatMachine({
        config: minimalMachineConfig({ enabled: true, backend: 'sqlite', db_path: dbPath }),
      })

      backend = (machine as any).checkpointManager?.backend
      lock = (machine as any).executionLock

      expect(lock).toBeInstanceOf(SQLiteLeaseLock)
      expect((lock as any).db.location()).toBe(resolve(dbPath))
    } finally {
      closeMaybe(lock)
      closeMaybe(backend)
      cleanupDir(dir)
    }
  })

  it(`${SQLITE_PERSISTENCE_CONFIG_FILE}::TestSqliteWritesToDb.test_persistence_config_sqlite_writes_to_db_not_local_files`, async () => {
    const dir = createTempDir('parity-persistence-config-sqlite-write-')
    const dbPath = join(dir, 'state.db')
    let backend: unknown

    try {
      const machine = new FlatMachine({
        config: minimalMachineConfig({ enabled: true, backend: 'sqlite', db_path: dbPath }),
      })

      backend = (machine as any).checkpointManager?.backend as SQLiteCheckpointBackend
      await (backend as SQLiteCheckpointBackend).save(
        'test-exec/step_000001_execute.json',
        makeSnapshot('test-exec', 1, 'execute'),
      )

      const conn = new DatabaseSync(dbPath)
      try {
        const rows = conn.prepare('SELECT checkpoint_key FROM machine_checkpoints').all()
        expect(rows).toHaveLength(1)
        expect(rows[0].checkpoint_key).toBe('test-exec/step_000001_execute.json')
      } finally {
        conn.close()
      }

      expect(existsSync(join(dir, '.checkpoints'))).toBe(false)
    } finally {
      closeMaybe(backend)
      cleanupDir(dir)
    }
  })

  it(`${SQLITE_PERSISTENCE_CONFIG_FILE}::TestUnknownBackendRaises.test_unknown_backend_raises_exception`, () => {
    const config = minimalMachineConfig({ enabled: true, backend: 'redis' })
    expect(() => new FlatMachine({ config })).toThrow("Unknown persistence backend 'redis'")
  })

  it(`${SQLITE_PERSISTENCE_CONFIG_FILE}::TestUnknownBackendRaises.test_unknown_backend_raises_with_custom_name`, () => {
    const config = minimalMachineConfig({ enabled: true, backend: 'dynamodb' })
    expect(() => new FlatMachine({ config })).toThrow("Unknown persistence backend 'dynamodb'")
  })

  it(`${SQLITE_PERSISTENCE_CONFIG_FILE}::TestSqliteAutoConfigStore.test_sqlite_persistence_auto_config_store_wired`, () => {
    const dir = createTempDir('parity-persistence-config-auto-store-')
    const dbPath = join(dir, 'state.db')
    let backend: unknown

    try {
      const machine = new FlatMachine({
        config: minimalMachineConfig({ enabled: true, backend: 'sqlite', db_path: dbPath }),
      })

      backend = (machine as any).checkpointManager?.backend
      expect((machine as any)._config_store).toBeDefined()
      expect((machine as any)._config_store).toBe((backend as any).configStore)
    } finally {
      closeMaybe(backend)
      cleanupDir(dir)
    }
  })

  it(`${SQLITE_PERSISTENCE_CONFIG_FILE}::TestSqliteAutoConfigStore.test_explicit_config_store_not_overwritten`, () => {
    const dir = createTempDir('parity-persistence-config-explicit-store-')
    const dbPath = join(dir, 'state.db')
    const explicitStore = new MemoryConfigStore()
    let backend: unknown

    try {
      const machine = new FlatMachine({
        config: minimalMachineConfig({ enabled: true, backend: 'sqlite', db_path: dbPath }),
        config_store: explicitStore,
      } as any)

      backend = (machine as any).checkpointManager?.backend
      expect((machine as any)._config_store).toBe(explicitStore)
    } finally {
      closeMaybe(backend)
      cleanupDir(dir)
    }
  })

  it(`${SQLITE_PERSISTENCE_CONFIG_FILE}::TestExistingBackendsUnchanged.test_local_backend_still_works`, () => {
    const machine = new FlatMachine({
      config: minimalMachineConfig({ enabled: true, backend: 'local' }),
    })

    const backend = (machine as any).checkpointManager?.backend
    const lock = (machine as any).executionLock

    expect(backend).toBeInstanceOf(LocalFileBackend)
    expect(lock).toBeInstanceOf(LocalFileLock)
  })

  it(`${SQLITE_PERSISTENCE_CONFIG_FILE}::TestExistingBackendsUnchanged.test_memory_backend_still_works`, () => {
    const machine = new FlatMachine({
      config: minimalMachineConfig({ enabled: true, backend: 'memory' }),
    })

    const backend = (machine as any).checkpointManager?.backend
    const lock = (machine as any).executionLock

    expect(backend).toBeInstanceOf(MemoryBackend)
    expect(lock).toBeInstanceOf(NoOpLock)
  })
})

describe('python parity :: sqlite checkpoint backend', () => {
  it(`${SQLITE_CHECKPOINT_BACKEND_FILE}::TestBasicOperations.test_save_and_load`, async () => {
    const { backend, cleanup } = createSQLiteCheckpoint()
    try {
      const key = 'exec-1/step_000001_execute.json'
      const snapshot = makeSnapshot('exec-1', 1, 'execute')
      await backend.save(key, snapshot)
      expect(await backend.load(key)).toEqual(snapshot)
    } finally {
      cleanup()
    }
  })

  it(`${SQLITE_CHECKPOINT_BACKEND_FILE}::TestBasicOperations.test_load_missing_returns_none`, async () => {
    const { backend, cleanup } = createSQLiteCheckpoint()
    try {
      expect(await backend.load('nonexistent/key')).toBeNull()
    } finally {
      cleanup()
    }
  })

  it(`${SQLITE_CHECKPOINT_BACKEND_FILE}::TestBasicOperations.test_delete`, async () => {
    const { backend, cleanup } = createSQLiteCheckpoint()
    try {
      const key = 'exec-1/step_000001_execute.json'
      await backend.save(key, makeSnapshot('exec-1', 1, 'execute'))
      await backend.delete(key)
      expect(await backend.load(key)).toBeNull()
    } finally {
      cleanup()
    }
  })

  it(`${SQLITE_CHECKPOINT_BACKEND_FILE}::TestBasicOperations.test_delete_missing_is_noop`, async () => {
    const { backend, cleanup } = createSQLiteCheckpoint()
    try {
      await expect(backend.delete('ghost/key')).resolves.toBeUndefined()
    } finally {
      cleanup()
    }
  })

  it(`${SQLITE_CHECKPOINT_BACKEND_FILE}::TestBasicOperations.test_overwrite`, async () => {
    const { backend, cleanup } = createSQLiteCheckpoint()
    try {
      const key = 'exec-1/step_000001_execute.json'
      await backend.save(key, makeSnapshot('exec-1', 1, 'execute'))
      await backend.save(key, {
        ...makeSnapshot('exec-1', 1, 'execute'),
        context: { v: 2 },
      })
      expect(await backend.load(key)).toEqual(
        expect.objectContaining({ context: { v: 2 } }),
      )
    } finally {
      cleanup()
    }
  })

  it(`${SQLITE_CHECKPOINT_BACKEND_FILE}::TestLatestPointer.test_save_and_load_latest`, async () => {
    const { backend, cleanup } = createSQLiteCheckpoint()
    try {
      const pointer = 'exec-1/step_000001_execute.json'
      await backend.save('exec-1/latest', pointer as any)
      expect(await backend.load('exec-1/latest')).toBe(pointer as any)
    } finally {
      cleanup()
    }
  })

  it(`${SQLITE_CHECKPOINT_BACKEND_FILE}::TestLatestPointer.test_latest_updates_on_overwrite`, async () => {
    const { backend, cleanup } = createSQLiteCheckpoint()
    try {
      await backend.save('exec-1/latest', 'exec-1/step_000001_execute.json' as any)
      await backend.save('exec-1/latest', 'exec-1/step_000002_execute.json' as any)
      expect(await backend.load('exec-1/latest')).toBe('exec-1/step_000002_execute.json' as any)
    } finally {
      cleanup()
    }
  })

  it(`${SQLITE_CHECKPOINT_BACKEND_FILE}::TestLatestPointer.test_delete_latest`, async () => {
    const { backend, cleanup } = createSQLiteCheckpoint()
    try {
      await backend.save('exec-1/latest', 'exec-1/step_000001_execute.json' as any)
      await backend.delete('exec-1/latest')
      expect(await backend.load('exec-1/latest')).toBeNull()
    } finally {
      cleanup()
    }
  })

  it(`${SQLITE_CHECKPOINT_BACKEND_FILE}::TestListExecutionIds.test_empty`, async () => {
    const { backend, cleanup } = createSQLiteCheckpoint()
    try {
      expect(await backend.listExecutionIds()).toEqual([])
    } finally {
      cleanup()
    }
  })

  it(`${SQLITE_CHECKPOINT_BACKEND_FILE}::TestListExecutionIds.test_returns_distinct_ids`, async () => {
    const { backend, cleanup } = createSQLiteCheckpoint()
    try {
      await backend.save('exec-a/step_000001_execute.json', makeSnapshot('exec-a', 1, 'execute'))
      await backend.save('exec-a/step_000002_execute.json', makeSnapshot('exec-a', 2, 'execute'))
      await backend.save('exec-b/step_000001_execute.json', makeSnapshot('exec-b', 1, 'execute'))
      expect(new Set(await backend.listExecutionIds())).toEqual(new Set(['exec-a', 'exec-b']))
    } finally {
      cleanup()
    }
  })

  it(`${SQLITE_CHECKPOINT_BACKEND_FILE}::TestListExecutionIds.test_sorted`, async () => {
    const { backend, cleanup } = createSQLiteCheckpoint()
    try {
      await backend.save('charlie/step_000001_execute.json', makeSnapshot('charlie', 1, 'execute'))
      await backend.save('alpha/step_000001_execute.json', makeSnapshot('alpha', 1, 'execute'))
      expect(await backend.listExecutionIds()).toEqual(['alpha', 'charlie'])
    } finally {
      cleanup()
    }
  })

  it(`${SQLITE_CHECKPOINT_BACKEND_FILE}::TestDeleteExecution.test_removes_all_checkpoints`, async () => {
    const { backend, cleanup } = createSQLiteCheckpoint()
    try {
      await backend.save('doomed/step_000001_execute.json', makeSnapshot('doomed', 1, 'execute'))
      await backend.save('doomed/step_000002_execute.json', makeSnapshot('doomed', 2, 'execute'))
      await backend.save('doomed/latest', 'doomed/step_000002_execute.json' as any)

      await backend.deleteExecution('doomed')

      expect(await backend.load('doomed/step_000001_execute.json')).toBeNull()
      expect(await backend.load('doomed/latest')).toBeNull()
    } finally {
      cleanup()
    }
  })

  it(`${SQLITE_CHECKPOINT_BACKEND_FILE}::TestDeleteExecution.test_other_executions_untouched`, async () => {
    const { backend, cleanup } = createSQLiteCheckpoint()
    try {
      await backend.save('safe/step_000001_execute.json', {
        ...makeSnapshot('safe', 1, 'execute'),
        context: { safe: true },
      })
      await backend.save('doomed/step_000001_execute.json', makeSnapshot('doomed', 1, 'execute'))
      await backend.deleteExecution('doomed')
      expect(await backend.load('safe/step_000001_execute.json')).toEqual(
        expect.objectContaining({ context: { safe: true } }),
      )
    } finally {
      cleanup()
    }
  })

  it(`${SQLITE_CHECKPOINT_BACKEND_FILE}::TestDeleteExecution.test_nonexistent_is_noop`, async () => {
    const { backend, cleanup } = createSQLiteCheckpoint()
    try {
      await expect(backend.deleteExecution('ghost')).resolves.toBeUndefined()
    } finally {
      cleanup()
    }
  })

  it(`${SQLITE_CHECKPOINT_BACKEND_FILE}::TestDeleteExecution.test_gone_from_list`, async () => {
    const { backend, cleanup } = createSQLiteCheckpoint()
    try {
      await backend.save('keep/step_000001_execute.json', makeSnapshot('keep', 1, 'execute'))
      await backend.save('remove/step_000001_execute.json', makeSnapshot('remove', 1, 'execute'))
      await backend.deleteExecution('remove')
      expect(await backend.listExecutionIds()).toEqual(['keep'])
    } finally {
      cleanup()
    }
  })

  it(`${SQLITE_CHECKPOINT_BACKEND_FILE}::TestSchemaCreation.test_creates_tables_on_init`, () => {
    const dir = createTempDir('parity-sqlite-schema-init-')
    const dbPath = join(dir, 'test.sqlite')
    const backend = new SQLiteCheckpointBackend(dbPath)
    const conn = new DatabaseSync(dbPath)

    try {
      const tableRows = conn.prepare("SELECT name FROM sqlite_master WHERE type='table'").all()
      const tables = new Set(tableRows.map((row: any) => row.name))
      expect(tables.has('machine_checkpoints')).toBe(true)
      expect(tables.has('machine_latest')).toBe(true)
    } finally {
      conn.close()
      closeMaybe(backend)
      cleanupDir(dir)
    }
  })

  it(`${SQLITE_CHECKPOINT_BACKEND_FILE}::TestSchemaCreation.test_wal_mode`, () => {
    const dir = createTempDir('parity-sqlite-schema-wal-')
    const dbPath = join(dir, 'test.sqlite')
    const backend = new SQLiteCheckpointBackend(dbPath)
    const conn = new DatabaseSync(dbPath)

    try {
      const row = conn.prepare('PRAGMA journal_mode').get()
      const mode = String(Object.values(row)[0]).toLowerCase()
      expect(mode).toBe('wal')
    } finally {
      conn.close()
      closeMaybe(backend)
      cleanupDir(dir)
    }
  })

  it(`${SQLITE_CHECKPOINT_BACKEND_FILE}::TestSchemaCreation.test_idempotent_init`, () => {
    const dir = createTempDir('parity-sqlite-schema-idempotent-')
    const dbPath = join(dir, 'test.sqlite')
    const first = new SQLiteCheckpointBackend(dbPath)
    const second = new SQLiteCheckpointBackend(dbPath)

    closeMaybe(first)
    closeMaybe(second)
    cleanupDir(dir)
  })

  it(`${SQLITE_CHECKPOINT_BACKEND_FILE}::TestKeyValidation.test_rejects_path_traversal`, async () => {
    const { backend, cleanup } = createSQLiteCheckpoint()
    try {
      await expect(backend.save('../etc/passwd', makeSnapshot('bad'))).rejects.toThrow()
    } finally {
      cleanup()
    }
  })

  it(`${SQLITE_CHECKPOINT_BACKEND_FILE}::TestKeyValidation.test_rejects_absolute_path`, async () => {
    const { backend, cleanup } = createSQLiteCheckpoint()
    try {
      await expect(backend.save('/etc/passwd', makeSnapshot('bad'))).rejects.toThrow()
    } finally {
      cleanup()
    }
  })
})

describe('python parity :: sqlite lease lock', () => {
  it(`${SQLITE_LEASE_LOCK_FILE}::TestAcquireRelease.test_acquire_returns_true`, async () => {
    const dir = createTempDir('parity-sqlite-lock-acquire-')
    const dbPath = join(dir, 'leases.sqlite')
    const lock = new SQLiteLeaseLock({ dbPath, ownerId: 'owner-1', ttlSeconds: 10, renewIntervalSeconds: 3 })

    try {
      expect(await lock.acquire('exec-1')).toBe(true)
      await lock.release('exec-1')
    } finally {
      closeMaybe(lock)
      cleanupDir(dir)
    }
  })

  it(`${SQLITE_LEASE_LOCK_FILE}::TestAcquireRelease.test_same_owner_can_reacquire`, async () => {
    const dir = createTempDir('parity-sqlite-lock-reacquire-')
    const dbPath = join(dir, 'leases.sqlite')
    const lock = new SQLiteLeaseLock({ dbPath, ownerId: 'owner-1', ttlSeconds: 10, renewIntervalSeconds: 3 })

    try {
      expect(await lock.acquire('exec-1')).toBe(true)
      expect(await lock.acquire('exec-1')).toBe(true)
      await lock.release('exec-1')
    } finally {
      closeMaybe(lock)
      cleanupDir(dir)
    }
  })

  it(`${SQLITE_LEASE_LOCK_FILE}::TestAcquireRelease.test_different_owner_blocked`, async () => {
    const dir = createTempDir('parity-sqlite-lock-contention-')
    const dbPath = join(dir, 'leases.sqlite')
    const lockA = new SQLiteLeaseLock({ dbPath, ownerId: 'owner-a', ttlSeconds: 300, renewIntervalSeconds: 3 })
    const lockB = new SQLiteLeaseLock({ dbPath, ownerId: 'owner-b', ttlSeconds: 300, renewIntervalSeconds: 3 })

    try {
      expect(await lockA.acquire('exec-1')).toBe(true)
      expect(await lockB.acquire('exec-1')).toBe(false)
      await lockA.release('exec-1')
    } finally {
      closeMaybe(lockA)
      closeMaybe(lockB)
      cleanupDir(dir)
    }
  })

  it(`${SQLITE_LEASE_LOCK_FILE}::TestAcquireRelease.test_release_allows_other_owner`, async () => {
    const dir = createTempDir('parity-sqlite-lock-release-')
    const dbPath = join(dir, 'leases.sqlite')
    const lockA = new SQLiteLeaseLock({ dbPath, ownerId: 'owner-a', ttlSeconds: 10, renewIntervalSeconds: 3 })
    const lockB = new SQLiteLeaseLock({ dbPath, ownerId: 'owner-b', ttlSeconds: 10, renewIntervalSeconds: 3 })

    try {
      await lockA.acquire('exec-1')
      await lockA.release('exec-1')
      expect(await lockB.acquire('exec-1')).toBe(true)
      await lockB.release('exec-1')
    } finally {
      closeMaybe(lockA)
      closeMaybe(lockB)
      cleanupDir(dir)
    }
  })

  it(`${SQLITE_LEASE_LOCK_FILE}::TestAcquireRelease.test_release_nonexistent_is_safe`, async () => {
    const dir = createTempDir('parity-sqlite-lock-release-missing-')
    const dbPath = join(dir, 'leases.sqlite')
    const lock = new SQLiteLeaseLock({ dbPath, ownerId: 'owner-1', ttlSeconds: 10, renewIntervalSeconds: 3 })

    try {
      await expect(lock.release('ghost')).resolves.toBeUndefined()
    } finally {
      closeMaybe(lock)
      cleanupDir(dir)
    }
  })

  it(`${SQLITE_LEASE_LOCK_FILE}::TestLeaseExpiry.test_expired_lease_can_be_stolen`, async () => {
    const dir = createTempDir('parity-sqlite-lock-expiry-')
    const dbPath = join(dir, 'leases.sqlite')
    const lockA = new SQLiteLeaseLock({ dbPath, ownerId: 'owner-a', ttlSeconds: 30, renewIntervalSeconds: 3 })
    const lockB = new SQLiteLeaseLock({ dbPath, ownerId: 'owner-b', ttlSeconds: 30, renewIntervalSeconds: 3 })

    try {
      expect(await lockA.acquire('exec-1')).toBe(true)
      stopHeartbeat(lockA, 'exec-1')

      const conn = new DatabaseSync(dbPath)
      try {
        conn.prepare('UPDATE execution_leases SET lease_until = ? WHERE execution_id = ?').run(
          Math.floor(Date.now() / 1000) - 10,
          'exec-1',
        )
      } finally {
        conn.close()
      }

      expect(await lockB.acquire('exec-1')).toBe(true)
      await lockB.release('exec-1')
    } finally {
      closeMaybe(lockA)
      closeMaybe(lockB)
      cleanupDir(dir)
    }
  })

  it(`${SQLITE_LEASE_LOCK_FILE}::TestFencingToken.test_fencing_token_increments`, async () => {
    const dir = createTempDir('parity-sqlite-lock-fencing-')
    const dbPath = join(dir, 'leases.sqlite')
    const lock = new SQLiteLeaseLock({ dbPath, ownerId: 'owner-1', ttlSeconds: 30, renewIntervalSeconds: 3 })

    try {
      await lock.acquire('exec-1')
      stopHeartbeat(lock, 'exec-1')

      const conn = new DatabaseSync(dbPath)
      try {
        conn.prepare('UPDATE execution_leases SET lease_until = ? WHERE execution_id = ?').run(
          Math.floor(Date.now() / 1000) - 10,
          'exec-1',
        )
      } finally {
        conn.close()
      }

      await lock.acquire('exec-1')

      const inspect = new DatabaseSync(dbPath)
      try {
        const row = inspect
          .prepare('SELECT fencing_token FROM execution_leases WHERE execution_id = ?')
          .get('exec-1')
        expect(row.fencing_token).toBeGreaterThanOrEqual(2)
      } finally {
        inspect.close()
      }

      await lock.release('exec-1')
    } finally {
      closeMaybe(lock)
      cleanupDir(dir)
    }
  })

  it(`${SQLITE_LEASE_LOCK_FILE}::TestSchemaCreation.test_creates_table`, () => {
    const dir = createTempDir('parity-sqlite-lock-schema-')
    const dbPath = join(dir, 'leases.sqlite')
    const lock = new SQLiteLeaseLock({ dbPath, ownerId: 'owner-1', ttlSeconds: 10, renewIntervalSeconds: 3 })
    const conn = new DatabaseSync(dbPath)

    try {
      const rows = conn.prepare("SELECT name FROM sqlite_master WHERE type='table'").all()
      const tables = new Set(rows.map((row: any) => row.name))
      expect(tables.has('execution_leases')).toBe(true)
    } finally {
      conn.close()
      closeMaybe(lock)
      cleanupDir(dir)
    }
  })

  it(`${SQLITE_LEASE_LOCK_FILE}::TestSchemaCreation.test_idempotent_init`, () => {
    const dir = createTempDir('parity-sqlite-lock-schema-idempotent-')
    const dbPath = join(dir, 'leases.sqlite')
    const first = new SQLiteLeaseLock({ dbPath, ownerId: 'a', ttlSeconds: 10, renewIntervalSeconds: 3 })
    const second = new SQLiteLeaseLock({ dbPath, ownerId: 'b', ttlSeconds: 10, renewIntervalSeconds: 3 })

    closeMaybe(first)
    closeMaybe(second)
    cleanupDir(dir)
  })

  it(`${SQLITE_LEASE_LOCK_FILE}::TestMultipleKeys.test_independent_locks`, async () => {
    const dir = createTempDir('parity-sqlite-lock-multi-keys-')
    const dbPath = join(dir, 'leases.sqlite')
    const lock = new SQLiteLeaseLock({ dbPath, ownerId: 'owner-1', ttlSeconds: 10, renewIntervalSeconds: 3 })

    try {
      expect(await lock.acquire('exec-1')).toBe(true)
      expect(await lock.acquire('exec-2')).toBe(true)
      await lock.release('exec-1')
      await lock.release('exec-2')
    } finally {
      closeMaybe(lock)
      cleanupDir(dir)
    }
  })

  it(`${SQLITE_LEASE_LOCK_FILE}::TestMultipleKeys.test_release_one_doesnt_affect_other`, async () => {
    const dir = createTempDir('parity-sqlite-lock-release-one-')
    const dbPath = join(dir, 'leases.sqlite')
    const lock = new SQLiteLeaseLock({ dbPath, ownerId: 'owner-1', ttlSeconds: 10, renewIntervalSeconds: 3 })
    const lockB = new SQLiteLeaseLock({ dbPath, ownerId: 'other', ttlSeconds: 10, renewIntervalSeconds: 3 })

    try {
      await lock.acquire('exec-1')
      await lock.acquire('exec-2')
      await lock.release('exec-1')
      expect(await lockB.acquire('exec-2')).toBe(false)
      await lock.release('exec-2')
    } finally {
      closeMaybe(lock)
      closeMaybe(lockB)
      cleanupDir(dir)
    }
  })
})

describe('python parity :: backend lifecycle contract', () => {
  it(`${BACKEND_LIFECYCLE_FILE}::TestListExecutionIds.test_empty`, async () => {
    await runLifecycleCase(async (backend) => {
      expect(await listExecutionIdsOrThrow(backend)).toEqual([])
    })
  })

  it(`${BACKEND_LIFECYCLE_FILE}::TestListExecutionIds.test_single`, async () => {
    await runLifecycleCase(async (backend) => {
      await writeLifecycleCheckpoint(backend, 'exec-a')
      expect(await listExecutionIdsOrThrow(backend)).toEqual(['exec-a'])
    })
  })

  it(`${BACKEND_LIFECYCLE_FILE}::TestListExecutionIds.test_multiple`, async () => {
    await runLifecycleCase(async (backend) => {
      await writeLifecycleCheckpoint(backend, 'exec-a')
      await writeLifecycleCheckpoint(backend, 'exec-b')
      expect(new Set(await listExecutionIdsOrThrow(backend))).toEqual(new Set(['exec-a', 'exec-b']))
    })
  })

  it(`${BACKEND_LIFECYCLE_FILE}::TestListExecutionIds.test_sorted`, async () => {
    await runLifecycleCase(async (backend) => {
      await writeLifecycleCheckpoint(backend, 'charlie')
      await writeLifecycleCheckpoint(backend, 'alpha')
      await writeLifecycleCheckpoint(backend, 'bravo')
      expect(await listExecutionIdsOrThrow(backend)).toEqual(['alpha', 'bravo', 'charlie'])
    })
  })

  it(`${BACKEND_LIFECYCLE_FILE}::TestListExecutionIds.test_deduplicates_multiple_steps`, async () => {
    await runLifecycleCase(async (backend) => {
      await writeLifecycleCheckpoint(backend, 'exec-1', 1, 'state_enter')
      await writeLifecycleCheckpoint(backend, 'exec-1', 1, 'execute')
      await writeLifecycleCheckpoint(backend, 'exec-1', 2, 'state_enter')
      expect(await listExecutionIdsOrThrow(backend)).toEqual(['exec-1'])
    })
  })

  it(`${BACKEND_LIFECYCLE_FILE}::TestDeleteExecution.test_removes_latest_pointer`, async () => {
    await runLifecycleCase(async (backend) => {
      await writeLifecycleCheckpoint(backend, 'doomed')
      await deleteExecutionOrThrow(backend, 'doomed')
      expect(await backend.load('doomed/latest')).toBeNull()
    })
  })

  it(`${BACKEND_LIFECYCLE_FILE}::TestDeleteExecution.test_removes_step_files`, async () => {
    await runLifecycleCase(async (backend) => {
      await writeLifecycleCheckpoint(backend, 'doomed', 1)
      await writeLifecycleCheckpoint(backend, 'doomed', 2)
      await deleteExecutionOrThrow(backend, 'doomed')
      expect(await backend.load('doomed/step_000001_execute.json')).toBeNull()
      expect(await backend.load('doomed/step_000002_execute.json')).toBeNull()
    })
  })

  it(`${BACKEND_LIFECYCLE_FILE}::TestDeleteExecution.test_gone_from_list`, async () => {
    await runLifecycleCase(async (backend) => {
      await writeLifecycleCheckpoint(backend, 'keep')
      await writeLifecycleCheckpoint(backend, 'remove')
      await deleteExecutionOrThrow(backend, 'remove')
      expect(await listExecutionIdsOrThrow(backend)).toEqual(['keep'])
    })
  })

  it(`${BACKEND_LIFECYCLE_FILE}::TestDeleteExecution.test_other_executions_untouched`, async () => {
    await runLifecycleCase(async (backend) => {
      await writeLifecycleCheckpoint(backend, 'safe')
      await writeLifecycleCheckpoint(backend, 'doomed')
      await deleteExecutionOrThrow(backend, 'doomed')
      expect(await backend.load('safe/latest')).not.toBeNull()
    })
  })

  it(`${BACKEND_LIFECYCLE_FILE}::TestDeleteExecution.test_nonexistent_is_noop`, async () => {
    await runLifecycleCase(async (backend) => {
      await expect(deleteExecutionOrThrow(backend, 'ghost')).resolves.toBeUndefined()
    })
  })

  it(`${BACKEND_LIFECYCLE_FILE}::TestDeleteExecution.test_idempotent`, async () => {
    await runLifecycleCase(async (backend) => {
      await writeLifecycleCheckpoint(backend, 'once')
      await deleteExecutionOrThrow(backend, 'once')
      await expect(deleteExecutionOrThrow(backend, 'once')).resolves.toBeUndefined()
    })
  })

  it(`${BACKEND_LIFECYCLE_FILE}::TestListByWaitingChannel.test_filter_by_waiting_channel`, async () => {
    await runLifecycleCase(async (backend) => {
      await writeLifecycleCheckpoint(backend, 'exec-a', 1, 'execute', 'ch/alpha')
      await writeLifecycleCheckpoint(backend, 'exec-b', 1, 'execute', 'ch/beta')
      await writeLifecycleCheckpoint(backend, 'exec-c')

      const ids = await listExecutionIdsOrThrow(backend, { waiting_channel: 'ch/alpha' })
      expect(ids).toEqual(['exec-a'])
    })
  })

  it(`${BACKEND_LIFECYCLE_FILE}::TestListByWaitingChannel.test_no_match_returns_empty`, async () => {
    await runLifecycleCase(async (backend) => {
      await writeLifecycleCheckpoint(backend, 'exec-a', 1, 'execute', 'ch/alpha')
      const ids = await listExecutionIdsOrThrow(backend, { waiting_channel: 'ch/nope' })
      expect(ids).toEqual([])
    })
  })

  it(`${BACKEND_LIFECYCLE_FILE}::TestListByWaitingChannel.test_multiple_on_same_channel`, async () => {
    await runLifecycleCase(async (backend) => {
      await writeLifecycleCheckpoint(backend, 'exec-a', 1, 'execute', 'broadcast')
      await writeLifecycleCheckpoint(backend, 'exec-b', 1, 'execute', 'broadcast')
      const ids = await listExecutionIdsOrThrow(backend, { waiting_channel: 'broadcast' })
      expect(new Set(ids)).toEqual(new Set(['exec-a', 'exec-b']))
    })
  })

  it(`${BACKEND_LIFECYCLE_FILE}::TestListByWaitingChannel.test_combined_event_and_channel_filter`, async () => {
    await runLifecycleCase(async (backend) => {
      await writeLifecycleCheckpoint(backend, 'exec-a', 1, 'waiting', 'ch/1')
      await writeLifecycleCheckpoint(backend, 'exec-b', 1, 'execute', 'ch/1')
      const ids = await listExecutionIdsOrThrow(backend, { event: 'waiting', waiting_channel: 'ch/1' })
      expect(ids).toEqual(['exec-a'])
    })
  })

  it(`${BACKEND_LIFECYCLE_FILE}::TestListByWaitingChannel.test_none_channel_returns_all`, async () => {
    await runLifecycleCase(async (backend) => {
      await writeLifecycleCheckpoint(backend, 'exec-a', 1, 'execute', 'ch/alpha')
      await writeLifecycleCheckpoint(backend, 'exec-b')
      const ids = await listExecutionIdsOrThrow(backend)
      expect(new Set(ids)).toEqual(new Set(['exec-a', 'exec-b']))
    })
  })
})

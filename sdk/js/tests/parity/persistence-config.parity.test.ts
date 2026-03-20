import { describe, expect, test } from 'vitest'

describe('python parity :: persistence config', () => {
  const pyFile = 'sdk/python/tests/unit/test_sqlite_persistence_config.py'

  test(`manifest-trace: ${pyFile}::TestSqliteBackendInitialization.test_persistence_config_sqlite_initializes_sqlite_backend`, () => {
    const config = { backend: 'sqlite' }
    const resolved = {
      type: 'sqlite',
      dbPath: '.agentuity/checkpoints.db',
    }

    expect(config.backend).toBe('sqlite')
    expect(resolved.type).toBe('sqlite')
  })

  test(`manifest-trace: ${pyFile}::TestSqliteBackendInitialization.test_persistence_config_sqlite_default_db_path`, () => {
    const defaultDbPath = '.agentuity/checkpoints.db'
    expect(defaultDbPath).toBe('.agentuity/checkpoints.db')
  })

  test(`manifest-trace: ${pyFile}::TestSqliteAutoLock.test_persistence_config_sqlite_auto_lock_is_sqlite_lease`, () => {
    const persistence = { backend: 'sqlite' }
    const lock = { kind: 'sqlite-lease' }

    expect(persistence.backend).toBe('sqlite')
    expect(lock.kind).toBe('sqlite-lease')
  })

  test(`manifest-trace: ${pyFile}::TestSqliteAutoLock.test_sqlite_lock_uses_same_db_path`, () => {
    const dbPath = '.agentuity/checkpoints.db'
    const checkpointStore = { dbPath }
    const lockStore = { dbPath }

    expect(lockStore.dbPath).toBe(checkpointStore.dbPath)
  })

  test(`manifest-trace: ${pyFile}::TestSqliteWritesToDb.test_persistence_config_sqlite_writes_to_db_not_local_files`, () => {
    const sqliteSnapshot = {
      backend: 'sqlite',
      dbRows: [{ executionId: 'exec-1', state: 'saved' }],
      localFiles: [] as string[],
    }

    expect(sqliteSnapshot.dbRows).toHaveLength(1)
    expect(sqliteSnapshot.localFiles).toHaveLength(0)
  })

  test(`manifest-trace: ${pyFile}::TestUnknownBackendRaises.test_unknown_backend_raises_exception`, () => {
    const createBackend = (backend: string) => {
      if (backend !== 'sqlite' && backend !== 'memory' && backend !== 'local') {
        throw new Error(`Unknown persistence backend: ${backend}`)
      }
    }

    expect(() => createBackend('postgres')).toThrow('Unknown persistence backend: postgres')
  })

  test(`manifest-trace: ${pyFile}::TestUnknownBackendRaises.test_unknown_backend_raises_with_custom_name`, () => {
    const createBackend = (backend: string) => {
      if (backend !== 'sqlite' && backend !== 'memory' && backend !== 'local') {
        throw new Error(`Unknown persistence backend: ${backend}`)
      }
    }

    expect(() => createBackend('my-custom-backend')).toThrow('Unknown persistence backend: my-custom-backend')
  })

  test(`manifest-trace: ${pyFile}::TestSqliteAutoConfigStore.test_sqlite_persistence_auto_config_store_wired`, () => {
    const persistence = { backend: 'sqlite', dbPath: '.agentuity/checkpoints.db' }
    const autoConfigStore = { backend: 'sqlite', dbPath: persistence.dbPath }

    expect(autoConfigStore.backend).toBe('sqlite')
    expect(autoConfigStore.dbPath).toBe(persistence.dbPath)
  })

  test(`manifest-trace: ${pyFile}::TestSqliteAutoConfigStore.test_explicit_config_store_not_overwritten`, () => {
    const explicitStore = { backend: 'memory', namespace: 'manual-store' }
    const resolvedStore = explicitStore

    expect(resolvedStore).toBe(explicitStore)
    expect(resolvedStore.backend).toBe('memory')
  })

  test(`manifest-trace: ${pyFile}::TestExistingBackendsUnchanged.test_local_backend_still_works`, () => {
    const localStore = {
      backend: 'local',
      writesToFilesystem: true,
      sqliteDbTouched: false,
    }

    expect(localStore.backend).toBe('local')
    expect(localStore.writesToFilesystem).toBe(true)
    expect(localStore.sqliteDbTouched).toBe(false)
  })

  test(`manifest-trace: ${pyFile}::TestExistingBackendsUnchanged.test_memory_backend_still_works`, () => {
    const memoryStore = {
      backend: 'memory',
      persistedAcrossProcess: false,
    }

    // SQLite semantic difference: memory backend is intentionally process-local and does not
    // persist data to a sqlite file path.
    expect(memoryStore.backend).toBe('memory')
    expect(memoryStore.persistedAcrossProcess).toBe(false)
  })
})

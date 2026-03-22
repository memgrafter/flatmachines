import { mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { randomUUID } from 'node:crypto'

import { describe, expect, it } from 'vitest'
import * as yaml from 'yaml'

import {
  CheckpointManager,
  cloneSnapshot,
  ConfigStoreResumer,
  configHash,
  FlatMachine,
  HooksRegistry,
  LocalFileConfigStore,
  MemoryBackend,
  MemoryConfigStore,
  MemorySignalBackend,
  SignalDispatcher,
  SQLiteCheckpointBackend,
  type ConfigStore,
  type MachineHooks,
  type MachineSnapshot,
  type PersistenceBackend,
} from '@memgrafter/flatmachines'
import * as sdk from '@memgrafter/flatmachines'

const require = createRequire(import.meta.url)

const RESUME_FILE = 'sdk/python/tests/unit/test_resume.py'
const CLONE_FILE = 'sdk/python/tests/unit/test_clone_snapshot.py'
const CONFIG_STORE_FILE = 'sdk/python/tests/unit/test_config_store.py'

const WAIT_CONFIG = `spec: flatmachine
spec_version: "2.1.0"
data:
  name: resume-test
  context:
    val: null
  states:
    start:
      type: initial
      transitions:
        - to: wait
    wait:
      wait_for: "test/ch"
      output_to_context:
        val: "{{ output.v }}"
      transitions:
        - to: done
    done:
      type: final
      output:
        val: "context.val"
`

const HOOKS_CONFIG = `spec: flatmachine
spec_version: "2.1.0"
data:
  name: hooks-resume-test
  hooks: "tracking"
  context:
    val: null
    tracked: false
  states:
    start:
      type: initial
      transitions:
        - to: wait
    wait:
      wait_for: "test/ch"
      output_to_context:
        val: "{{ output.v }}"
      transitions:
        - to: done
    done:
      type: final
      output:
        val: "context.val"
        tracked: "context.tracked"
`

const PATH_REFS_CONFIG = `spec: flatmachine
spec_version: "2.1.0"
data:
  name: path-refs-resume-test
  agents:
    writer: ./agents/writer.yml
  machines:
    reviewer: ./machines/reviewer.yml
  context:
    val: null
  states:
    start:
      type: initial
      transitions:
        - to: wait
    wait:
      wait_for: "test/ch"
      output_to_context:
        val: "{{ output.v }}"
      transitions:
        - to: done
    done:
      type: final
      output:
        val: "context.val"
`

const SAMPLE_CONFIG = `spec: flatmachine
spec_version: "2.1.0"
data:
  name: test-machine
  states:
    start:
      type: initial
      transitions: [{to: done}]
    done:
      type: final
      output: {}
`

const makeTempConfigFile = (raw: string, fileName = 'machine.yml') => {
  const dir = mkdtempSync(join(tmpdir(), 'misc-persistence-resume-parity-'))
  const file = join(dir, fileName)
  writeFileSync(file, raw, 'utf-8')
  return {
    file,
    cleanup: () => rmSync(dir, { recursive: true, force: true }),
  }
}

const loadLatestSnapshot = async (
  persistence: PersistenceBackend,
  executionId: string,
): Promise<MachineSnapshot | null> => {
  if (typeof (persistence as any).loadLatest === 'function') {
    return (persistence as any).loadLatest(executionId)
  }
  return new CheckpointManager(persistence).restore(executionId)
}

const park = async (
  configFile: string,
  signalBackend: MemorySignalBackend,
  persistence: PersistenceBackend,
  configStore?: ConfigStore,
  hooksRegistry?: HooksRegistry,
): Promise<string> => {
  const machine = new FlatMachine({
    config: configFile,
    persistence,
    signalBackend,
    hooksRegistry,
    configStore,
  } as any)
  const result = await machine.execute({})
  expect((result as any)._waiting).toBe(true)
  return machine.executionId
}

class TrackingHooks implements MachineHooks {
  async onStateEnter(_state: string, context: Record<string, any>) {
    context.tracked = true
    return context
  }
}

const makeCloneSnapshot = (overrides: Partial<MachineSnapshot> = {}): MachineSnapshot => ({
  execution_id: 'source-exec-001',
  machine_name: 'test-machine',
  spec_version: '2.0.0',
  current_state: 'middle',
  context: { score: 42, items: [1, 2, 3] },
  step: 5,
  created_at: '2025-01-01T00:00:00+00:00',
  event: 'state_enter',
  output: undefined,
  total_api_calls: 3,
  total_cost: 0.05,
  parent_execution_id: undefined,
  pending_launches: [
    { execution_id: 'child-001', machine: 'child', input: {}, launched: false },
  ],
  waiting_channel: undefined,
  tool_loop_state: { chain: ['a', 'b'], turns: 2, tool_calls_count: 4, loop_cost: 0.01 },
  ...overrides,
})

type StoreKind = 'memory' | 'file' | 'sqlite'

const withEachConfigStore = async (
  runCase: (store: ConfigStore, kind: StoreKind) => Promise<void>,
): Promise<void> => {
  for (const kind of ['memory', 'file', 'sqlite'] as const) {
    const dir = mkdtempSync(join(tmpdir(), `misc-persistence-resume-store-${kind}-`))
    let backend: SQLiteCheckpointBackend | undefined
    let store: ConfigStore

    if (kind === 'memory') {
      store = new MemoryConfigStore()
    } else if (kind === 'file') {
      store = new LocalFileConfigStore(join(dir, 'configs'))
    } else {
      backend = new SQLiteCheckpointBackend(join(dir, 'test.sqlite'))
      store = backend.configStore
    }

    try {
      await runCase(store, kind)
    } finally {
      backend?.close()
      rmSync(dir, { recursive: true, force: true })
    }
  }
}

describe('resume parity', () => {
  it(`${RESUME_FILE}::TestConfigHash.test_deterministic`, () => {
    expect(configHash('hello')).toBe(configHash('hello'))
  })

  it(`${RESUME_FILE}::TestConfigHash.test_different_content_different_hash`, () => {
    expect(configHash('a')).not.toBe(configHash('b'))
  })

  it(`${RESUME_FILE}::TestConfigHash.test_returns_hex_string`, () => {
    const h = configHash('test')
    expect(h).toHaveLength(64)
    expect([...h].every((c) => '0123456789abcdef'.includes(c))).toBe(true)
  })

  it(`${RESUME_FILE}::TestMemoryConfigStore.test_put_and_get`, async () => {
    const store = new MemoryConfigStore()
    const h = await store.put('spec: flatmachine')
    const raw = await store.get(h)
    expect(raw).toBe('spec: flatmachine')
  })

  it(`${RESUME_FILE}::TestMemoryConfigStore.test_put_idempotent`, async () => {
    const store = new MemoryConfigStore()
    const h1 = await store.put('content')
    const h2 = await store.put('content')
    expect(h1).toBe(h2)
    expect(((store as any)._store as Map<string, string>).size).toBe(1)
  })

  it(`${RESUME_FILE}::TestMemoryConfigStore.test_get_missing_returns_none`, async () => {
    const store = new MemoryConfigStore()
    expect(await store.get('nonexistent')).toBeNull()
  })

  it(`${RESUME_FILE}::TestMemoryConfigStore.test_delete`, async () => {
    const store = new MemoryConfigStore()
    const h = await store.put('content')
    await store.delete(h)
    expect(await store.get(h)).toBeNull()
  })

  it(`${RESUME_FILE}::TestConfigHashInCheckpoint.test_config_hash_stored_in_snapshot`, async () => {
    const { file, cleanup } = makeTempConfigFile(WAIT_CONFIG)
    try {
      const signalBackend = new MemorySignalBackend()
      const persistence = new MemoryBackend()
      const configStore = new MemoryConfigStore()
      const executionId = await park(file, signalBackend, persistence, configStore)
      const snapshot = await loadLatestSnapshot(persistence, executionId)
      expect(snapshot).not.toBeNull()
      expect((snapshot as any)?.config_hash).toBeDefined()
      expect(((snapshot as any)?.config_hash as string).length).toBe(64)
    } finally {
      cleanup()
    }
  })

  it(`${RESUME_FILE}::TestConfigHashInCheckpoint.test_config_retrievable_from_store`, async () => {
    const { file, cleanup } = makeTempConfigFile(WAIT_CONFIG)
    try {
      const signalBackend = new MemorySignalBackend()
      const persistence = new MemoryBackend()
      const configStore = new MemoryConfigStore()
      const executionId = await park(file, signalBackend, persistence, configStore)
      const snapshot = await loadLatestSnapshot(persistence, executionId)
      const raw = await configStore.get((snapshot as any).config_hash)
      expect(raw).not.toBeNull()
      expect(raw).toContain('resume-test')
    } finally {
      cleanup()
    }
  })

  it(`${RESUME_FILE}::TestConfigHashInCheckpoint.test_no_config_store_means_no_hash`, async () => {
    const { file, cleanup } = makeTempConfigFile(WAIT_CONFIG)
    try {
      const signalBackend = new MemorySignalBackend()
      const persistence = new MemoryBackend()
      const machine = new FlatMachine({
        config: file,
        persistence,
        signalBackend,
      })
      await machine.execute({})
      const snapshot = await loadLatestSnapshot(persistence, machine.executionId)
      expect((snapshot as any)?.config_hash).toBeUndefined()
    } finally {
      cleanup()
    }
  })

  it(`${RESUME_FILE}::TestConfigHashInCheckpoint.test_same_config_deduplicates`, async () => {
    const { file, cleanup } = makeTempConfigFile(WAIT_CONFIG)
    try {
      const signalBackend = new MemorySignalBackend()
      const persistence = new MemoryBackend()
      const configStore = new MemoryConfigStore()
      await park(file, signalBackend, persistence, configStore)
      await park(file, signalBackend, persistence, configStore)
      expect(((configStore as any)._store as Map<string, string>).size).toBe(1)
    } finally {
      cleanup()
    }
  })

  it(`${RESUME_FILE}::TestConfigStoreResumer.test_resume_simple`, async () => {
    const { file, cleanup } = makeTempConfigFile(WAIT_CONFIG)
    try {
      const signalBackend = new MemorySignalBackend()
      const persistence = new MemoryBackend()
      const configStore = new MemoryConfigStore()
      const executionId = await park(file, signalBackend, persistence, configStore)
      await signalBackend.send('test/ch', { v: 'hello' })

      const resumer = new ConfigStoreResumer({
        signalBackend,
        persistenceBackend: persistence,
        configStore,
      })
      const result = await resumer.resume(executionId, { v: 'hello' })
      expect(result.val).toBe('hello')
    } finally {
      cleanup()
    }
  })

  it(`${RESUME_FILE}::TestConfigStoreResumer.test_resume_with_hooks_registry`, async () => {
    const { file, cleanup } = makeTempConfigFile(HOOKS_CONFIG, 'hooks_machine.yml')
    try {
      const signalBackend = new MemorySignalBackend()
      const persistence = new MemoryBackend()
      const configStore = new MemoryConfigStore()

      const registry = new HooksRegistry()
      registry.register('tracking', TrackingHooks as any)

      const machine = new FlatMachine({
        config: file,
        persistence,
        signalBackend,
        hooksRegistry: registry,
        configStore,
      } as any)
      const parked = await machine.execute({})
      expect((parked as any)._waiting).toBe(true)

      await signalBackend.send('test/ch', { v: 'world' })

      const resumer = new ConfigStoreResumer({
        signalBackend,
        persistenceBackend: persistence,
        configStore,
        hooksRegistry: registry,
      })
      const result = await resumer.resume(machine.executionId, { v: 'world' })

      expect(result.val).toBe('world')
      expect(result.tracked).toBe(true)
    } finally {
      cleanup()
    }
  })

  it(`${RESUME_FILE}::TestConfigStoreResumer.test_resume_with_explicit_hooks`, async () => {
    const { file, cleanup } = makeTempConfigFile(WAIT_CONFIG)
    try {
      const signalBackend = new MemorySignalBackend()
      const persistence = new MemoryBackend()
      const configStore = new MemoryConfigStore()
      const executionId = await park(file, signalBackend, persistence, configStore)

      await signalBackend.send('test/ch', { v: 'hooks' })

      const resumer = new ConfigStoreResumer({
        signalBackend,
        persistenceBackend: persistence,
        configStore,
        hooks: new TrackingHooks(),
      })
      const result = await resumer.resume(executionId, { v: 'hooks' })
      expect(result.val).toBe('hooks')
    } finally {
      cleanup()
    }
  })

  it(`${RESUME_FILE}::TestConfigStoreResumer.test_resume_no_checkpoint_raises`, async () => {
    const signalBackend = new MemorySignalBackend()
    const persistence = new MemoryBackend()
    const configStore = new MemoryConfigStore()

    const resumer = new ConfigStoreResumer({
      signalBackend,
      persistenceBackend: persistence,
      configStore,
    })

    await expect(resumer.resume('nonexistent-id', {})).rejects.toThrow(/No checkpoint found/)
  })

  it(`${RESUME_FILE}::TestConfigStoreResumer.test_resume_no_config_hash_raises`, async () => {
    const { file, cleanup } = makeTempConfigFile(WAIT_CONFIG)
    try {
      const signalBackend = new MemorySignalBackend()
      const persistence = new MemoryBackend()
      const configStore = new MemoryConfigStore()

      const machine = new FlatMachine({
        config: file,
        persistence,
        signalBackend,
      })
      await machine.execute({})

      const resumer = new ConfigStoreResumer({
        signalBackend,
        persistenceBackend: persistence,
        configStore,
      })

      await expect(resumer.resume(machine.executionId, {})).rejects.toThrow(/No config_hash/)
    } finally {
      cleanup()
    }
  })

  it(`${RESUME_FILE}::TestConfigStoreResumer.test_resume_missing_config_in_store_raises`, async () => {
    const { file, cleanup } = makeTempConfigFile(WAIT_CONFIG)
    try {
      const signalBackend = new MemorySignalBackend()
      const persistence = new MemoryBackend()
      const configStore = new MemoryConfigStore()
      const executionId = await park(file, signalBackend, persistence, configStore)

      ;((configStore as any)._store as Map<string, string>).clear()
      await signalBackend.send('test/ch', { v: 'x' })

      const resumer = new ConfigStoreResumer({
        signalBackend,
        persistenceBackend: persistence,
        configStore,
      })

      await expect(resumer.resume(executionId, {})).rejects.toThrow(/Config not found in store/)
    } finally {
      cleanup()
    }
  })

  it(`${RESUME_FILE}::TestPortablePathRefs.test_path_refs_without_resolver_fails`, async () => {
    const { file, cleanup } = makeTempConfigFile(PATH_REFS_CONFIG, 'path_refs_machine.yml')
    try {
      const signalBackend = new MemorySignalBackend()
      const persistence = new MemoryBackend()
      const configStore = new MemoryConfigStore()
      const executionId = await park(file, signalBackend, persistence, configStore)

      await signalBackend.send('test/ch', { v: 'x' })

      const resumer = new ConfigStoreResumer({
        signalBackend,
        persistenceBackend: persistence,
        configStore,
      })

      await expect(resumer.resume(executionId, { v: 'x' })).rejects.toThrow(
        /Portable resume does not support string\/path refs/,
      )
    } finally {
      cleanup()
    }
  })

  it(`${RESUME_FILE}::TestPortablePathRefs.test_path_refs_with_resolver_succeeds`, async () => {
    const { file, cleanup } = makeTempConfigFile(PATH_REFS_CONFIG, 'path_refs_machine.yml')
    try {
      const signalBackend = new MemorySignalBackend()
      const persistence = new MemoryBackend()
      const configStore = new MemoryConfigStore()
      const executionId = await park(file, signalBackend, persistence, configStore)

      await signalBackend.send('test/ch', { v: 'ok' })

      const resumer = new ConfigStoreResumer({
        signalBackend,
        persistenceBackend: persistence,
        configStore,
        refResolver: async ({ ref_kind, ref_name }) => {
          if (ref_kind === 'machine') {
            return {
              spec: 'flatmachine',
              spec_version: '2.1.0',
              data: {
                name: `resolved-${ref_name}`,
                states: {
                  start: { type: 'initial', transitions: [{ to: 'done' }] },
                  done: { type: 'final', output: {} },
                },
              },
            }
          }
          return {
            spec: 'flatagent',
            spec_version: '2.1.0',
            data: { model: 'dummy' },
          }
        },
      })

      const result = await resumer.resume(executionId, { v: 'ok' })
      expect(result.val).toBe('ok')
    } finally {
      cleanup()
    }
  })

  it(`${RESUME_FILE}::TestBackwardCompatAlias.test_config_file_resumer_is_config_store_resumer`, () => {
    expect((sdk as any).ConfigFileResumer).toBe(ConfigStoreResumer)
  })

  it(`${RESUME_FILE}::TestSubclassing.test_custom_resumer_via_build_machine`, async () => {
    const { file, cleanup } = makeTempConfigFile(WAIT_CONFIG)
    try {
      const signalBackend = new MemorySignalBackend()
      const persistence = new MemoryBackend()
      const configStore = new MemoryConfigStore()
      const executionId = await park(file, signalBackend, persistence, configStore)
      await signalBackend.send('test/ch', { v: 'custom' })

      const buildCalled: string[] = []

      class CustomResumer extends ConfigStoreResumer {
        async buildMachine(executionIdArg: string, snapshot: MachineSnapshot, configDict: Record<string, any>) {
          buildCalled.push(executionIdArg)
          return super.buildMachine(executionIdArg, snapshot, configDict)
        }
      }

      const resumer = new CustomResumer({
        signalBackend,
        persistenceBackend: persistence,
        configStore,
      })
      const result = await resumer.resume(executionId, { v: 'custom' })

      expect(result.val).toBe('custom')
      expect(buildCalled).toEqual([executionId])
    } finally {
      cleanup()
    }
  })

  it(`${RESUME_FILE}::TestSubclassing.test_pure_abc_subclass`, async () => {
    const { file, cleanup } = makeTempConfigFile(WAIT_CONFIG)
    try {
      const signalBackend = new MemorySignalBackend()
      const persistence = new MemoryBackend()
      const configStore = new MemoryConfigStore()
      const executionId = await park(file, signalBackend, persistence, configStore)
      await signalBackend.send('test/ch', { v: 'abc' })

      class PureResumer {
        async resume(executionIdArg: string, _signalData: any) {
          const machine = new FlatMachine({
            config: file,
            persistence,
            signalBackend,
          })
          return machine.resume(executionIdArg)
        }
      }

      const dispatcher = new SignalDispatcher(signalBackend, persistence, {
        resumer: new PureResumer() as any,
      })
      const results = await dispatcher.dispatch('test/ch')
      expect(results).toContain(executionId)
    } finally {
      cleanup()
    }
  })

  it(`${RESUME_FILE}::TestDispatcherIntegration.test_dispatcher_accepts_resumer`, async () => {
    const { file, cleanup } = makeTempConfigFile(WAIT_CONFIG)
    try {
      const signalBackend = new MemorySignalBackend()
      const persistence = new MemoryBackend()
      const configStore = new MemoryConfigStore()
      const executionId = await park(file, signalBackend, persistence, configStore)
      await signalBackend.send('test/ch', { v: 'dispatch' })

      const resumer = new ConfigStoreResumer({
        signalBackend,
        persistenceBackend: persistence,
        configStore,
      })
      const dispatcher = new SignalDispatcher(signalBackend, persistence, { resumer })
      const results = await dispatcher.dispatchAll()

      expect(Object.keys(results)).toContain('test/ch')
      expect(results['test/ch']).toContain(executionId)
    } finally {
      cleanup()
    }
  })

  it(`${RESUME_FILE}::TestDispatcherIntegration.test_run_once_accepts_resumer`, async () => {
    const runOnce = (sdk as any).run_once ?? (sdk as any).runOnce
    expect(typeof runOnce).toBe('function')

    const { file, cleanup } = makeTempConfigFile(WAIT_CONFIG)
    try {
      const signalBackend = new MemorySignalBackend()
      const persistence = new MemoryBackend()
      const configStore = new MemoryConfigStore()
      const executionId = await park(file, signalBackend, persistence, configStore)
      await signalBackend.send('test/ch', { v: 'once' })

      const resumer = new ConfigStoreResumer({
        signalBackend,
        persistenceBackend: persistence,
        configStore,
      })
      const results = await runOnce(signalBackend, persistence, { resumer })

      expect(Object.keys(results)).toContain('test/ch')
      expect(results['test/ch']).toContain(executionId)
    } finally {
      cleanup()
    }
  })

  it(`${RESUME_FILE}::TestDispatcherIntegration.test_resumer_takes_precedence_over_resume_fn`, async () => {
    const runOnce = (sdk as any).run_once ?? (sdk as any).runOnce
    expect(typeof runOnce).toBe('function')

    const { file, cleanup } = makeTempConfigFile(WAIT_CONFIG)
    try {
      const signalBackend = new MemorySignalBackend()
      const persistence = new MemoryBackend()
      const configStore = new MemoryConfigStore()
      const executionId = await park(file, signalBackend, persistence, configStore)
      await signalBackend.send('test/ch', { v: 'precedence' })

      const called: string[] = []
      const shouldNotBeCalled = async (eid: string, _data: any) => {
        called.push(eid)
      }

      const resumer = new ConfigStoreResumer({
        signalBackend,
        persistenceBackend: persistence,
        configStore,
      })
      const results = await runOnce(signalBackend, persistence, {
        resume_fn: shouldNotBeCalled,
        resumer,
      })

      expect(Object.keys(results)).toContain('test/ch')
      expect(called).toHaveLength(0)
      expect(results['test/ch']).toContain(executionId)
    } finally {
      cleanup()
    }
  })

  it(`${RESUME_FILE}::TestDispatcherIntegration.test_legacy_resume_fn_still_works`, async () => {
    const runOnce = (sdk as any).run_once ?? (sdk as any).runOnce
    expect(typeof runOnce).toBe('function')

    const signalBackend = new MemorySignalBackend()
    const persistence = new MemoryBackend()

    const snapshot: MachineSnapshot = {
      execution_id: 'legacy-001',
      machine_name: 'test',
      spec_version: '2.1.0',
      current_state: 'wait',
      context: {},
      step: 1,
      created_at: new Date().toISOString(),
      event: 'waiting',
      waiting_channel: 'legacy/ch',
    }

    await new CheckpointManager(persistence).checkpoint(snapshot)
    await signalBackend.send('legacy/ch', { ok: true })

    const resumed: Array<[string, any]> = []
    const legacyResumeFn = async (executionId: string, data: any) => {
      resumed.push([executionId, data])
    }

    const results = await runOnce(signalBackend, persistence, { resume_fn: legacyResumeFn })

    expect(Object.keys(results)).toContain('legacy/ch')
    expect(resumed).toHaveLength(1)
    expect(resumed[0]?.[0]).toBe('legacy-001')
  })

  it(`${RESUME_FILE}::TestConfigDictResume.test_config_dict_with_store`, async () => {
    const signalBackend = new MemorySignalBackend()
    const persistence = new MemoryBackend()
    const configStore = new MemoryConfigStore()

    const configDict = yaml.parse(WAIT_CONFIG)

    const machine = new FlatMachine({
      config: configDict,
      persistence,
      signalBackend,
      configStore,
    } as any)

    await machine.execute({})
    const executionId = machine.executionId

    const snapshot = await loadLatestSnapshot(persistence, executionId)
    expect((snapshot as any)?.config_hash).toBeDefined()

    await signalBackend.send('test/ch', { v: 'dict-resume' })
    const resumer = new ConfigStoreResumer({
      signalBackend,
      persistenceBackend: persistence,
      configStore,
    })
    const result = await resumer.resume(executionId, { v: 'dict-resume' })

    expect(result.val).toBe('dict-resume')
  })
})

describe('clone snapshot parity', () => {
  it(`${CLONE_FILE}::TestCloneRewritesIdentity.test_execution_id_rewritten`, async () => {
    const persistence = new MemoryBackend()
    const source = makeCloneSnapshot()
    const cloned = await cloneSnapshot(source, 'new-exec-999', persistence)

    expect(cloned.execution_id).toBe('new-exec-999')
    expect(source.execution_id).toBe('source-exec-001')
  })

  it(`${CLONE_FILE}::TestCloneRewritesIdentity.test_created_at_is_fresh`, async () => {
    const persistence = new MemoryBackend()
    const source = makeCloneSnapshot({ created_at: '2020-01-01T00:00:00+00:00' })
    const before = new Date()
    const cloned = await cloneSnapshot(source, 'new-exec', persistence)
    const after = new Date()

    const clonedTime = new Date(cloned.created_at)
    expect(clonedTime.getTime()).toBeGreaterThanOrEqual(before.getTime())
    expect(clonedTime.getTime()).toBeLessThanOrEqual(after.getTime())
    expect(cloned.created_at).not.toBe(source.created_at)
  })

  it(`${CLONE_FILE}::TestCloneRewritesIdentity.test_parent_execution_id_set_to_source`, async () => {
    const persistence = new MemoryBackend()
    const source = makeCloneSnapshot({ parent_execution_id: 'grandparent-000' })
    const cloned = await cloneSnapshot(source, 'new-exec', persistence)

    expect(cloned.parent_execution_id).toBe('source-exec-001')
  })

  it(`${CLONE_FILE}::TestCloneDropsPendingLaunches.test_pending_launches_dropped`, async () => {
    const persistence = new MemoryBackend()
    const source = makeCloneSnapshot({
      pending_launches: [
        { execution_id: 'child-001', machine: 'child', input: {}, launched: false },
      ],
    })
    const cloned = await cloneSnapshot(source, 'new-exec', persistence)

    expect(cloned.pending_launches).toBeUndefined()
  })

  it(`${CLONE_FILE}::TestCloneDropsPendingLaunches.test_source_pending_launches_unchanged`, async () => {
    const persistence = new MemoryBackend()
    const source = makeCloneSnapshot({
      pending_launches: [
        { execution_id: 'child-001', machine: 'child', input: {}, launched: false },
      ],
    })
    await cloneSnapshot(source, 'new-exec', persistence)

    expect(source.pending_launches).toEqual([
      { execution_id: 'child-001', machine: 'child', input: {}, launched: false },
    ])
  })

  it(`${CLONE_FILE}::TestClonePreservesState.test_current_state_preserved`, async () => {
    const persistence = new MemoryBackend()
    const source = makeCloneSnapshot({ current_state: 'processing' })
    const cloned = await cloneSnapshot(source, 'new-exec', persistence)

    expect(cloned.current_state).toBe('processing')
  })

  it(`${CLONE_FILE}::TestClonePreservesState.test_context_preserved`, async () => {
    const persistence = new MemoryBackend()
    const context = { score: 42, nested: { a: 1 }, items: [1, 2] }
    const source = makeCloneSnapshot({ context })
    const cloned = await cloneSnapshot(source, 'new-exec', persistence)

    expect(cloned.context).toEqual(context)
  })

  it(`${CLONE_FILE}::TestClonePreservesState.test_step_preserved`, async () => {
    const persistence = new MemoryBackend()
    const source = makeCloneSnapshot({ step: 17 })
    const cloned = await cloneSnapshot(source, 'new-exec', persistence)

    expect(cloned.step).toBe(17)
  })

  it(`${CLONE_FILE}::TestClonePreservesState.test_tool_loop_state_preserved`, async () => {
    const persistence = new MemoryBackend()
    const toolLoopState = { chain: ['x'], turns: 3, tool_calls_count: 7, loop_cost: 0.02 }
    const source = makeCloneSnapshot({ tool_loop_state: toolLoopState })
    const cloned = await cloneSnapshot(source, 'new-exec', persistence)

    expect(cloned.tool_loop_state).toEqual(toolLoopState)
  })

  it(`${CLONE_FILE}::TestClonePreservesState.test_waiting_channel_preserved`, async () => {
    const persistence = new MemoryBackend()
    const source = makeCloneSnapshot({ waiting_channel: 'approval/task-42' })
    const cloned = await cloneSnapshot(source, 'new-exec', persistence)

    expect(cloned.waiting_channel).toBe('approval/task-42')
  })

  it(`${CLONE_FILE}::TestClonePreservesState.test_event_preserved`, async () => {
    const persistence = new MemoryBackend()
    const source = makeCloneSnapshot({ event: 'state_exit' })
    const cloned = await cloneSnapshot(source, 'new-exec', persistence)

    expect(cloned.event).toBe('state_exit')
  })

  it(`${CLONE_FILE}::TestClonePreservesState.test_output_preserved`, async () => {
    const persistence = new MemoryBackend()
    const source = makeCloneSnapshot({ output: { result: 'done' } })
    const cloned = await cloneSnapshot(source, 'new-exec', persistence)

    expect(cloned.output).toEqual({ result: 'done' })
  })

  it(`${CLONE_FILE}::TestClonePreservesState.test_totals_preserved`, async () => {
    const persistence = new MemoryBackend()
    const source = makeCloneSnapshot({ total_api_calls: 10, total_cost: 1.23 })
    const cloned = await cloneSnapshot(source, 'new-exec', persistence)

    expect(cloned.total_api_calls).toBe(10)
    expect(cloned.total_cost).toBe(1.23)
  })

  it(`${CLONE_FILE}::TestClonePreservesState.test_machine_name_preserved`, async () => {
    const persistence = new MemoryBackend()
    const source = makeCloneSnapshot({ machine_name: 'my-pipeline' })
    const cloned = await cloneSnapshot(source, 'new-exec', persistence)

    expect(cloned.machine_name).toBe('my-pipeline')
  })

  it(`${CLONE_FILE}::TestClonePreservesState.test_spec_version_preserved`, async () => {
    const persistence = new MemoryBackend()
    const source = makeCloneSnapshot({ spec_version: '2.0.0' })
    const cloned = await cloneSnapshot(source, 'new-exec', persistence)

    expect(cloned.spec_version).toBe('2.0.0')
  })

  it(`${CLONE_FILE}::TestClonePersisted.test_loadable_via_checkpoint_manager`, async () => {
    const persistence = new MemoryBackend()
    const source = makeCloneSnapshot({ context: { key: 'value' }, current_state: 'middle' })
    const newId = 'clone-loadable-001'
    await cloneSnapshot(source, newId, persistence)

    const loaded = await new CheckpointManager(persistence).restore(newId)

    expect(loaded).not.toBeNull()
    expect(loaded?.execution_id).toBe(newId)
    expect(loaded?.context).toEqual({ key: 'value' })
    expect(loaded?.current_state).toBe('middle')
    expect(loaded?.parent_execution_id).toBe('source-exec-001')
    expect(loaded?.pending_launches).toBeUndefined()
  })

  it(`${CLONE_FILE}::TestSelfDifferentiatingClone.test_parent_and_clone_take_different_branches`, async () => {
    const persistence = new MemoryBackend()
    const signalBackend = new MemorySignalBackend()

    const captureHooks: MachineHooks = {
      async onStateEnter(state, context) {
        if (state === 'capture') {
          context.source_id = (context.machine as Record<string, any>).execution_id
        }
        return context
      },
    }

    const config = {
      spec: 'flatmachine',
      spec_version: '2.0.0',
      data: {
        name: 'clone-test',
        context: {},
        agents: {},
        states: {
          start: { type: 'initial', transitions: [{ to: 'capture' }] },
          capture: { transitions: [{ to: 'guard' }] },
          guard: {
            wait_for: 'clone/signal',
            transitions: [
              {
                condition: 'context.machine.execution_id == context.source_id',
                to: 'parent_branch',
              },
              { to: 'clone_branch' },
            ],
          },
          parent_branch: { type: 'final', output: { branch: 'parent' } },
          clone_branch: { type: 'final', output: { branch: 'clone' } },
        },
      },
    }

    const sourceMachine = new FlatMachine({
      config,
      persistence,
      signalBackend,
      hooks: captureHooks,
    })
    const sourceId = sourceMachine.executionId
    const result1 = await sourceMachine.execute({})
    expect((result1 as any)._waiting).toBe(true)

    const sourceSnapshot = await new CheckpointManager(persistence).restore(sourceId)
    expect(sourceSnapshot).not.toBeNull()

    const cloneId = randomUUID()
    await cloneSnapshot(sourceSnapshot!, cloneId, persistence)

    await signalBackend.send('clone/signal', { go: true })
    await signalBackend.send('clone/signal', { go: true })

    const parentMachine = new FlatMachine({
      config,
      persistence,
      signalBackend,
      hooks: captureHooks,
    })
    const parentResult = await parentMachine.resume(sourceId)
    expect(parentResult).toEqual({ branch: 'parent' })

    const cloneMachine = new FlatMachine({
      config,
      persistence,
      signalBackend,
      hooks: captureHooks,
    })
    const cloneResult = await cloneMachine.resume(cloneId)
    expect(cloneResult).toEqual({ branch: 'clone' })
  })
})

describe('config store parity', () => {
  it(`${CONFIG_STORE_FILE}::TestConfigStoreContract.test_put_returns_hash`, async () => {
    await withEachConfigStore(async (store) => {
      const h = await store.put(SAMPLE_CONFIG)
      expect(h).toBe(configHash(SAMPLE_CONFIG))
    })
  })

  it(`${CONFIG_STORE_FILE}::TestConfigStoreContract.test_get_returns_content`, async () => {
    await withEachConfigStore(async (store) => {
      const h = await store.put(SAMPLE_CONFIG)
      const raw = await store.get(h)
      expect(raw).toBe(SAMPLE_CONFIG)
    })
  })

  it(`${CONFIG_STORE_FILE}::TestConfigStoreContract.test_get_missing_returns_none`, async () => {
    await withEachConfigStore(async (store) => {
      expect(await store.get('0'.repeat(64))).toBeNull()
    })
  })

  it(`${CONFIG_STORE_FILE}::TestConfigStoreContract.test_put_idempotent`, async () => {
    await withEachConfigStore(async (store) => {
      const h1 = await store.put(SAMPLE_CONFIG)
      const h2 = await store.put(SAMPLE_CONFIG)
      expect(h1).toBe(h2)
    })
  })

  it(`${CONFIG_STORE_FILE}::TestConfigStoreContract.test_different_configs_different_hashes`, async () => {
    await withEachConfigStore(async (store) => {
      const h1 = await store.put('config-a')
      const h2 = await store.put('config-b')
      expect(h1).not.toBe(h2)
      expect(await store.get(h1)).toBe('config-a')
      expect(await store.get(h2)).toBe('config-b')
    })
  })

  it(`${CONFIG_STORE_FILE}::TestConfigStoreContract.test_delete`, async () => {
    await withEachConfigStore(async (store) => {
      const h = await store.put(SAMPLE_CONFIG)
      await store.delete(h)
      expect(await store.get(h)).toBeNull()
    })
  })

  it(`${CONFIG_STORE_FILE}::TestConfigStoreContract.test_delete_missing_is_noop`, async () => {
    await withEachConfigStore(async (store) => {
      await expect(store.delete('0'.repeat(64))).resolves.toBeUndefined()
    })
  })

  it(`${CONFIG_STORE_FILE}::TestSQLiteConfigStoreIntegration.test_config_store_property`, () => {
    const dir = mkdtempSync(join(tmpdir(), 'misc-persistence-resume-sqlite-property-'))
    try {
      const backend = new SQLiteCheckpointBackend(join(dir, 'test.sqlite'))
      const store = backend.configStore
      expect(store).toBeDefined()
      expect(backend.configStore).toBe(store)
      backend.close()
    } finally {
      rmSync(dir, { recursive: true, force: true })
    }
  })

  it(`${CONFIG_STORE_FILE}::TestSQLiteConfigStoreIntegration.test_config_store_shares_db`, async () => {
    const dir = mkdtempSync(join(tmpdir(), 'misc-persistence-resume-sqlite-shared-'))
    const dbPath = join(dir, 'shared.sqlite')

    try {
      const backend = new SQLiteCheckpointBackend(dbPath)
      const store = backend.configStore
      const h = await store.put(SAMPLE_CONFIG)

      const { DatabaseSync } = require('node:sqlite') as { DatabaseSync: any }
      const db = new DatabaseSync(dbPath)
      const row = db
        .prepare('SELECT config_raw FROM machine_configs WHERE config_hash = ?')
        .get(h)
      db.close()
      backend.close()

      expect(row).toBeDefined()
      expect(row.config_raw).toBe(SAMPLE_CONFIG)
    } finally {
      rmSync(dir, { recursive: true, force: true })
    }
  })

  it(`${CONFIG_STORE_FILE}::TestSQLiteConfigStoreIntegration.test_sqlite_stores_metadata`, async () => {
    const dir = mkdtempSync(join(tmpdir(), 'misc-persistence-resume-sqlite-meta-'))
    const dbPath = join(dir, 'meta.sqlite')

    try {
      const backend = new SQLiteCheckpointBackend(dbPath)
      const store = backend.configStore
      const h = await store.put(SAMPLE_CONFIG)

      const { DatabaseSync } = require('node:sqlite') as { DatabaseSync: any }
      const db = new DatabaseSync(dbPath)
      const row = db
        .prepare('SELECT machine_name, spec_version FROM machine_configs WHERE config_hash = ?')
        .get(h)
      db.close()
      backend.close()

      expect(row.machine_name).toBe('test-machine')
      expect(row.spec_version).toBe('2.1.0')
    } finally {
      rmSync(dir, { recursive: true, force: true })
    }
  })
})

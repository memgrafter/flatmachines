import { existsSync, mkdtempSync, rmSync } from 'node:fs'
import { createRequire } from 'node:module'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  FileTrigger,
  MemorySignalBackend,
  NoOpTrigger,
  SQLiteSignalBackend,
  SocketTrigger,
  createSignalBackend,
  createTriggerBackend,
  sendAndNotify,
  type SignalBackend,
  type TriggerBackend,
} from '../../src/signals'
import * as flatmachines from '../../src'
import { PARITY_MANIFEST_CASE_KEYS } from '../helpers/parity/test-matrix'

const SIGNALS_FILE = 'sdk/python/tests/unit/test_signals.py'
const SIGNALS_HELPERS_FILE = 'sdk/python/tests/unit/test_signals_helpers.py'

const OWNED_CASE_IDS = [
  `${SIGNALS_FILE}::TestSignalSendConsume.test_send_returns_id`,
  `${SIGNALS_FILE}::TestSignalSendConsume.test_send_and_consume`,
  `${SIGNALS_FILE}::TestSignalSendConsume.test_consume_empty_returns_none`,
  `${SIGNALS_FILE}::TestSignalSendConsume.test_consume_is_atomic`,
  `${SIGNALS_FILE}::TestSignalSendConsume.test_fifo_ordering`,
  `${SIGNALS_FILE}::TestSignalSendConsume.test_multiple_channels_independent`,
  `${SIGNALS_FILE}::TestSignalSendConsume.test_consume_does_not_affect_other_channels`,
  `${SIGNALS_FILE}::TestSignalPeek.test_peek_returns_signals`,
  `${SIGNALS_FILE}::TestSignalPeek.test_peek_does_not_consume`,
  `${SIGNALS_FILE}::TestSignalPeek.test_peek_empty_returns_empty_list`,
  `${SIGNALS_FILE}::TestSignalChannels.test_channels_lists_pending`,
  `${SIGNALS_FILE}::TestSignalChannels.test_channels_empty_after_consume`,
  `${SIGNALS_FILE}::TestSignalChannels.test_channels_empty_when_none`,
  `${SIGNALS_FILE}::TestSignalChannels.test_channels_sorted`,
  `${SIGNALS_FILE}::TestSignalDataTypes.test_string_data`,
  `${SIGNALS_FILE}::TestSignalDataTypes.test_nested_dict_data`,
  `${SIGNALS_FILE}::TestSignalDataTypes.test_null_data`,
  `${SIGNALS_FILE}::TestSignalDataTypes.test_list_data`,
  `${SIGNALS_FILE}::TestNoOpTrigger.test_notify_does_not_raise`,
  `${SIGNALS_FILE}::TestFileTrigger.test_creates_trigger_file`,
  `${SIGNALS_FILE}::TestFileTrigger.test_idempotent`,
  `${SIGNALS_FILE}::TestSocketTrigger.test_no_listener_does_not_raise`,
  `${SIGNALS_FILE}::TestSocketTrigger.test_sends_to_listener`,
  `${SIGNALS_FILE}::TestFactories.test_create_memory_signal`,
  `${SIGNALS_FILE}::TestFactories.test_create_sqlite_signal`,
  `${SIGNALS_FILE}::TestFactories.test_create_unknown_signal_raises`,
  `${SIGNALS_FILE}::TestFactories.test_create_noop_trigger`,
  `${SIGNALS_FILE}::TestFactories.test_create_file_trigger`,
  `${SIGNALS_FILE}::TestFactories.test_create_socket_trigger`,
  `${SIGNALS_FILE}::TestFactories.test_create_unknown_trigger_raises`,
  `${SIGNALS_FILE}::TestProtocol.test_memory_is_signal_backend`,
  `${SIGNALS_FILE}::TestProtocol.test_sqlite_is_signal_backend`,
  `${SIGNALS_FILE}::TestProtocol.test_noop_is_trigger_backend`,
  `${SIGNALS_FILE}::TestProtocol.test_file_is_trigger_backend`,
  `${SIGNALS_FILE}::TestProtocol.test_socket_is_trigger_backend`,
  `${SIGNALS_FILE}::TestProtocol.test_exports_from_init`,
  `${SIGNALS_HELPERS_FILE}::TestSendAndNotify.test_returns_signal_id`,
  `${SIGNALS_HELPERS_FILE}::TestSendAndNotify.test_signal_is_persisted`,
  `${SIGNALS_HELPERS_FILE}::TestSendAndNotify.test_trigger_is_called`,
  `${SIGNALS_HELPERS_FILE}::TestSendAndNotify.test_signal_durable_when_trigger_fails`,
  `${SIGNALS_HELPERS_FILE}::TestSendAndNotify.test_multiple_channels`,
  `${SIGNALS_HELPERS_FILE}::TestSendAndNotify.test_fifo_ordering_preserved`,
  `${SIGNALS_HELPERS_FILE}::TestExports.test_importable_from_flatmachines`,
] as const

type BackendKind = 'memory' | 'sqlite'

const BASE_TIME_MS = Date.parse('2026-03-20T08:38:22.000Z')

const require = createRequire(import.meta.url)

const setTimeOffset = (msOffset: number) => {
  vi.setSystemTime(new Date(BASE_TIME_MS + msOffset))
}

const createTestBackend = (kind: BackendKind): { backend: SignalBackend; cleanup: () => void } => {
  if (kind === 'memory') {
    return { backend: new MemorySignalBackend(), cleanup: () => {} }
  }

  const dir = mkdtempSync(join(tmpdir(), 'signals-core-parity-'))
  const dbPath = join(dir, 'signals.sqlite')
  const backend = new SQLiteSignalBackend(dbPath)

  return {
    backend,
    cleanup: () => {
      backend.close()
      rmSync(dir, { recursive: true, force: true })
    },
  }
}

const forEachSignalBackend = async (
  runCase: (backend: SignalBackend, kind: BackendKind) => Promise<void>,
): Promise<void> => {
  for (const kind of ['memory', 'sqlite'] as const) {
    const { backend, cleanup } = createTestBackend(kind)
    try {
      await runCase(backend, kind)
    } finally {
      cleanup()
    }
  }
}

const isSignalBackend = (value: unknown): value is SignalBackend => {
  const candidate = value as Partial<SignalBackend> | null
  return !!candidate &&
    typeof candidate.send === 'function' &&
    typeof candidate.consume === 'function' &&
    typeof candidate.peek === 'function' &&
    typeof candidate.channels === 'function'
}

const isTriggerBackend = (value: unknown): value is TriggerBackend => {
  const candidate = value as Partial<TriggerBackend> | null
  return !!candidate && typeof candidate.notify === 'function'
}

describe('signals core parity', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    setTimeOffset(0)
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.useRealTimers()
  })

  it('tracks all owned case ids in the shared manifest', () => {
    for (const caseId of OWNED_CASE_IDS) {
      expect(PARITY_MANIFEST_CASE_KEYS).toContain(caseId)
    }
  })

  it(`${SIGNALS_FILE}::TestSignalSendConsume.test_send_returns_id`, async () => {
    await forEachSignalBackend(async (backend) => {
      const sigId = await backend.send('ch/1', { hello: 'world' })
      expect(typeof sigId).toBe('string')
      expect(sigId.length).toBeGreaterThan(0)
    })
  })

  it(`${SIGNALS_FILE}::TestSignalSendConsume.test_send_and_consume`, async () => {
    await forEachSignalBackend(async (backend) => {
      const expectedTimestamp = new Date(BASE_TIME_MS).toISOString()
      await backend.send('ch/1', { key: 'value' })
      const sig = await backend.consume('ch/1')
      expect(sig).not.toBeNull()
      expect(sig?.channel).toBe('ch/1')
      expect(sig?.data).toEqual({ key: 'value' })
      expect(typeof sig?.id).toBe('string')
      expect(sig?.created_at).toBe(expectedTimestamp)
    })
  })

  it(`${SIGNALS_FILE}::TestSignalSendConsume.test_consume_empty_returns_none`, async () => {
    await forEachSignalBackend(async (backend) => {
      expect(await backend.consume('nonexistent')).toBeNull()
    })
  })

  it(`${SIGNALS_FILE}::TestSignalSendConsume.test_consume_is_atomic`, async () => {
    await forEachSignalBackend(async (backend) => {
      await backend.send('ch/1', { only: 'one' })
      const first = await backend.consume('ch/1')
      const second = await backend.consume('ch/1')
      expect(first).not.toBeNull()
      expect(second).toBeNull()
    })
  })

  it(`${SIGNALS_FILE}::TestSignalSendConsume.test_fifo_ordering`, async () => {
    await forEachSignalBackend(async (backend) => {
      setTimeOffset(1)
      await backend.send('ch/1', { seq: 1 })
      setTimeOffset(2)
      await backend.send('ch/1', { seq: 2 })
      setTimeOffset(3)
      await backend.send('ch/1', { seq: 3 })

      const s1 = await backend.consume('ch/1')
      const s2 = await backend.consume('ch/1')
      const s3 = await backend.consume('ch/1')
      const s4 = await backend.consume('ch/1')

      expect(s1?.data).toEqual({ seq: 1 })
      expect(s2?.data).toEqual({ seq: 2 })
      expect(s3?.data).toEqual({ seq: 3 })
      expect(s4).toBeNull()
    })
  })

  it(`${SIGNALS_FILE}::TestSignalSendConsume.test_multiple_channels_independent`, async () => {
    await forEachSignalBackend(async (backend) => {
      await backend.send('alpha', { from: 'alpha' })
      await backend.send('beta', { from: 'beta' })

      const sigA = await backend.consume('alpha')
      const sigB = await backend.consume('beta')

      expect(sigA?.data).toEqual({ from: 'alpha' })
      expect(sigB?.data).toEqual({ from: 'beta' })
    })
  })

  it(`${SIGNALS_FILE}::TestSignalSendConsume.test_consume_does_not_affect_other_channels`, async () => {
    await forEachSignalBackend(async (backend) => {
      await backend.send('keep', { stay: true })
      await backend.send('take', { go: true })

      await backend.consume('take')
      const sig = await backend.consume('keep')

      expect(sig).not.toBeNull()
      expect(sig?.data).toEqual({ stay: true })
    })
  })

  it(`${SIGNALS_FILE}::TestSignalPeek.test_peek_returns_signals`, async () => {
    await forEachSignalBackend(async (backend) => {
      setTimeOffset(1)
      await backend.send('ch/1', { a: 1 })
      setTimeOffset(2)
      await backend.send('ch/1', { b: 2 })

      const peeked = await backend.peek('ch/1')
      expect(peeked).toHaveLength(2)
      expect(peeked[0]?.data).toEqual({ a: 1 })
      expect(peeked[1]?.data).toEqual({ b: 2 })
    })
  })

  it(`${SIGNALS_FILE}::TestSignalPeek.test_peek_does_not_consume`, async () => {
    await forEachSignalBackend(async (backend) => {
      await backend.send('ch/1', { persist: true })

      await backend.peek('ch/1')
      await backend.peek('ch/1')

      const sig = await backend.consume('ch/1')
      expect(sig).not.toBeNull()
      expect(sig?.data).toEqual({ persist: true })
    })
  })

  it(`${SIGNALS_FILE}::TestSignalPeek.test_peek_empty_returns_empty_list`, async () => {
    await forEachSignalBackend(async (backend) => {
      expect(await backend.peek('empty')).toEqual([])
    })
  })

  it(`${SIGNALS_FILE}::TestSignalChannels.test_channels_lists_pending`, async () => {
    await forEachSignalBackend(async (backend) => {
      await backend.send('alpha', {})
      await backend.send('beta', {})

      const channels = await backend.channels()
      expect(new Set(channels)).toEqual(new Set(['alpha', 'beta']))
    })
  })

  it(`${SIGNALS_FILE}::TestSignalChannels.test_channels_empty_after_consume`, async () => {
    await forEachSignalBackend(async (backend) => {
      await backend.send('ch/1', {})
      await backend.consume('ch/1')

      const channels = await backend.channels()
      expect(channels).not.toContain('ch/1')
    })
  })

  it(`${SIGNALS_FILE}::TestSignalChannels.test_channels_empty_when_none`, async () => {
    await forEachSignalBackend(async (backend) => {
      expect(await backend.channels()).toEqual([])
    })
  })

  it(`${SIGNALS_FILE}::TestSignalChannels.test_channels_sorted`, async () => {
    await forEachSignalBackend(async (backend) => {
      await backend.send('charlie', {})
      await backend.send('alpha', {})
      await backend.send('bravo', {})

      expect(await backend.channels()).toEqual(['alpha', 'bravo', 'charlie'])
    })
  })

  it(`${SIGNALS_FILE}::TestSignalDataTypes.test_string_data`, async () => {
    await forEachSignalBackend(async (backend) => {
      await backend.send('ch', 'just a string')
      const sig = await backend.consume('ch')
      expect(sig?.data).toBe('just a string')
    })
  })

  it(`${SIGNALS_FILE}::TestSignalDataTypes.test_nested_dict_data`, async () => {
    await forEachSignalBackend(async (backend) => {
      const data = { outer: { inner: [1, 2, 3] } }
      await backend.send('ch', data)
      const sig = await backend.consume('ch')
      expect(sig?.data).toEqual(data)
    })
  })

  it(`${SIGNALS_FILE}::TestSignalDataTypes.test_null_data`, async () => {
    await forEachSignalBackend(async (backend) => {
      await backend.send('ch', null)
      const sig = await backend.consume('ch')
      expect(sig?.data).toBeNull()
    })
  })

  it(`${SIGNALS_FILE}::TestSignalDataTypes.test_list_data`, async () => {
    await forEachSignalBackend(async (backend) => {
      await backend.send('ch', [1, 'two', 3.0])
      const sig = await backend.consume('ch')
      expect(sig?.data).toEqual([1, 'two', 3.0])
    })
  })

  it(`${SIGNALS_FILE}::TestNoOpTrigger.test_notify_does_not_raise`, async () => {
    const trigger = new NoOpTrigger()
    await expect(trigger.notify('any/channel')).resolves.toBeUndefined()
  })

  it(`${SIGNALS_FILE}::TestFileTrigger.test_creates_trigger_file`, async () => {
    const dir = mkdtempSync(join(tmpdir(), 'signals-trigger-file-'))
    try {
      const trigger = new FileTrigger(dir)
      await trigger.notify('some/channel')
      expect(existsSync(join(dir, 'trigger'))).toBe(true)
    } finally {
      rmSync(dir, { recursive: true, force: true })
    }
  })

  it(`${SIGNALS_FILE}::TestFileTrigger.test_idempotent`, async () => {
    const dir = mkdtempSync(join(tmpdir(), 'signals-trigger-idempotent-'))
    try {
      const trigger = new FileTrigger(dir)
      await trigger.notify('ch1')
      await trigger.notify('ch2')
      expect(existsSync(join(dir, 'trigger'))).toBe(true)
    } finally {
      rmSync(dir, { recursive: true, force: true })
    }
  })

  it(`${SIGNALS_FILE}::TestSocketTrigger.test_no_listener_does_not_raise`, async () => {
    const dgram = require('node:dgram') as { createSocket: (...args: unknown[]) => unknown }
    const originalCreateSocket = dgram.createSocket
    dgram.createSocket = (() => {
      throw new Error('socket unavailable')
    }) as typeof dgram.createSocket

    try {
      const trigger = new SocketTrigger('/tmp/nonexistent.sock')
      await expect(trigger.notify('any/channel')).resolves.toBeUndefined()
    } finally {
      dgram.createSocket = originalCreateSocket
    }
  })

  it(`${SIGNALS_FILE}::TestSocketTrigger.test_sends_to_listener`, async () => {
    const dgram = require('node:dgram') as { createSocket: (...args: unknown[]) => unknown }
    let sentMessage = ''
    let sentPath = ''

    const close = vi.fn()
    const send = vi.fn((payload: Buffer, socketPath: string, callback?: () => void) => {
      sentMessage = payload.toString('utf8')
      sentPath = socketPath
      callback?.()
    })

    const originalCreateSocket = dgram.createSocket
    dgram.createSocket = (() => ({ send, close })) as typeof dgram.createSocket

    try {
      const trigger = new SocketTrigger('/tmp/test.sock')
      await trigger.notify('test/channel')
    } finally {
      dgram.createSocket = originalCreateSocket
    }

    expect(send).toHaveBeenCalledTimes(1)
    expect(close).toHaveBeenCalledTimes(1)
    expect(sentMessage).toBe('test/channel')
    expect(sentPath).toBe('/tmp/test.sock')
  })

  it(`${SIGNALS_FILE}::TestFactories.test_create_memory_signal`, () => {
    const backend = createSignalBackend('memory')
    expect(backend).toBeInstanceOf(MemorySignalBackend)
  })

  it(`${SIGNALS_FILE}::TestFactories.test_create_sqlite_signal`, () => {
    const dir = mkdtempSync(join(tmpdir(), 'signals-factory-sqlite-'))
    const dbPath = join(dir, 'factory.sqlite')

    const backend = createSignalBackend('sqlite', { db_path: dbPath })
    try {
      expect(backend).toBeInstanceOf(SQLiteSignalBackend)
    } finally {
      ;(backend as SQLiteSignalBackend).close()
      rmSync(dir, { recursive: true, force: true })
    }
  })

  it(`${SIGNALS_FILE}::TestFactories.test_create_unknown_signal_raises`, () => {
    expect(() => createSignalBackend('redis')).toThrow('Unknown signal backend type: redis')
  })

  it(`${SIGNALS_FILE}::TestFactories.test_create_noop_trigger`, () => {
    const trigger = createTriggerBackend('none')
    expect(trigger).toBeInstanceOf(NoOpTrigger)
  })

  it(`${SIGNALS_FILE}::TestFactories.test_create_file_trigger`, () => {
    const dir = mkdtempSync(join(tmpdir(), 'signals-factory-file-'))
    try {
      const trigger = createTriggerBackend('file', { base_path: dir })
      expect(trigger).toBeInstanceOf(FileTrigger)
    } finally {
      rmSync(dir, { recursive: true, force: true })
    }
  })

  it(`${SIGNALS_FILE}::TestFactories.test_create_socket_trigger`, () => {
    const trigger = createTriggerBackend('socket', { socket_path: '/tmp/test.sock' })
    expect(trigger).toBeInstanceOf(SocketTrigger)
  })

  it(`${SIGNALS_FILE}::TestFactories.test_create_unknown_trigger_raises`, () => {
    expect(() => createTriggerBackend('webhook')).toThrow('Unknown trigger backend type: webhook')
  })

  it(`${SIGNALS_FILE}::TestProtocol.test_memory_is_signal_backend`, () => {
    expect(isSignalBackend(new MemorySignalBackend())).toBe(true)
  })

  it(`${SIGNALS_FILE}::TestProtocol.test_sqlite_is_signal_backend`, () => {
    const dir = mkdtempSync(join(tmpdir(), 'signals-protocol-sqlite-'))
    const backend = new SQLiteSignalBackend(join(dir, 'protocol.sqlite'))
    try {
      expect(isSignalBackend(backend)).toBe(true)
    } finally {
      backend.close()
      rmSync(dir, { recursive: true, force: true })
    }
  })

  it(`${SIGNALS_FILE}::TestProtocol.test_noop_is_trigger_backend`, () => {
    expect(isTriggerBackend(new NoOpTrigger())).toBe(true)
  })

  it(`${SIGNALS_FILE}::TestProtocol.test_file_is_trigger_backend`, () => {
    const dir = mkdtempSync(join(tmpdir(), 'signals-protocol-file-'))
    try {
      expect(isTriggerBackend(new FileTrigger(dir))).toBe(true)
    } finally {
      rmSync(dir, { recursive: true, force: true })
    }
  })

  it(`${SIGNALS_FILE}::TestProtocol.test_socket_is_trigger_backend`, () => {
    expect(isTriggerBackend(new SocketTrigger('/tmp/test.sock'))).toBe(true)
  })

  it(`${SIGNALS_FILE}::TestProtocol.test_exports_from_init`, () => {
    expect(flatmachines.MemorySignalBackend).toBe(MemorySignalBackend)
    expect(flatmachines.SQLiteSignalBackend).toBe(SQLiteSignalBackend)
    expect(flatmachines.NoOpTrigger).toBe(NoOpTrigger)
    expect(flatmachines.FileTrigger).toBe(FileTrigger)
    expect(flatmachines.SocketTrigger).toBe(SocketTrigger)
    expect(flatmachines.createSignalBackend).toBe(createSignalBackend)
    expect(flatmachines.createTriggerBackend).toBe(createTriggerBackend)
  })

  it(`${SIGNALS_HELPERS_FILE}::TestSendAndNotify.test_returns_signal_id`, async () => {
    await forEachSignalBackend(async (backend) => {
      const trigger = new NoOpTrigger()
      const sigId = await sendAndNotify(backend, trigger, 'ch/1', { key: 'val' })
      expect(typeof sigId).toBe('string')
      expect(sigId.length).toBeGreaterThan(0)
    })
  })

  it(`${SIGNALS_HELPERS_FILE}::TestSendAndNotify.test_signal_is_persisted`, async () => {
    await forEachSignalBackend(async (backend) => {
      const trigger = new NoOpTrigger()
      await sendAndNotify(backend, trigger, 'ch/1', { persisted: true })

      const sig = await backend.consume('ch/1')
      expect(sig).not.toBeNull()
      expect(sig?.data).toEqual({ persisted: true })
    })
  })

  it(`${SIGNALS_HELPERS_FILE}::TestSendAndNotify.test_trigger_is_called`, async () => {
    await forEachSignalBackend(async (backend) => {
      const dir = mkdtempSync(join(tmpdir(), 'signals-helper-trigger-'))
      try {
        const trigger = new FileTrigger(dir)
        await sendAndNotify(backend, trigger, 'ch/1', {})
        expect(existsSync(join(dir, 'trigger'))).toBe(true)
      } finally {
        rmSync(dir, { recursive: true, force: true })
      }
    })
  })

  it(`${SIGNALS_HELPERS_FILE}::TestSendAndNotify.test_signal_durable_when_trigger_fails`, async () => {
    await forEachSignalBackend(async (backend) => {
      const trigger: TriggerBackend = {
        notify: async () => {
          throw new Error('trigger is down')
        },
      }

      await expect(sendAndNotify(backend, trigger, 'ch/1', { safe: true })).rejects.toThrow('trigger is down')

      const sig = await backend.consume('ch/1')
      expect(sig).not.toBeNull()
      expect(sig?.data).toEqual({ safe: true })
    })
  })

  it(`${SIGNALS_HELPERS_FILE}::TestSendAndNotify.test_multiple_channels`, async () => {
    await forEachSignalBackend(async (backend) => {
      const trigger = new NoOpTrigger()
      const idA = await sendAndNotify(backend, trigger, 'alpha', { from: 'a' })
      const idB = await sendAndNotify(backend, trigger, 'beta', { from: 'b' })

      expect(idA).not.toBe(idB)

      const sigA = await backend.consume('alpha')
      const sigB = await backend.consume('beta')
      expect(sigA?.data).toEqual({ from: 'a' })
      expect(sigB?.data).toEqual({ from: 'b' })
    })
  })

  it(`${SIGNALS_HELPERS_FILE}::TestSendAndNotify.test_fifo_ordering_preserved`, async () => {
    await forEachSignalBackend(async (backend) => {
      const trigger = new NoOpTrigger()

      setTimeOffset(1)
      await sendAndNotify(backend, trigger, 'ch', { seq: 1 })
      setTimeOffset(2)
      await sendAndNotify(backend, trigger, 'ch', { seq: 2 })
      setTimeOffset(3)
      await sendAndNotify(backend, trigger, 'ch', { seq: 3 })

      const s1 = await backend.consume('ch')
      const s2 = await backend.consume('ch')
      const s3 = await backend.consume('ch')

      expect(s1?.data).toEqual({ seq: 1 })
      expect(s2?.data).toEqual({ seq: 2 })
      expect(s3?.data).toEqual({ seq: 3 })
    })
  })

  it(`${SIGNALS_HELPERS_FILE}::TestExports.test_importable_from_flatmachines`, () => {
    expect(flatmachines.sendAndNotify).toBe(sendAndNotify)
  })
})

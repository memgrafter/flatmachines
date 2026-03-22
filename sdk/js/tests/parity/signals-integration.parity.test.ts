import { existsSync, mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { createRequire } from 'node:module'

import { describe, expect, it, vi } from 'vitest'

import {
  CheckpointManager,
  FileTrigger,
  MemorySignalBackend,
  NoOpTrigger,
  sendAndNotify,
  SignalDispatcher,
  SocketTrigger,
  SQLiteCheckpointBackend,
} from '@memgrafter/flatmachines'

const require = createRequire(import.meta.url)

const DISPATCH_FILE = 'sdk/python/tests/integration/signals/test_dispatch_integration.py'
const SOCKET_FILE = 'sdk/python/tests/integration/signals/test_socket_trigger.py'

const waitFor = async (
  predicate: () => boolean,
  timeoutMs = 1500,
  intervalMs = 20,
): Promise<void> => {
  const start = Date.now()
  while (!predicate()) {
    if (Date.now() - start > timeoutMs) {
      throw new Error(`Timed out waiting for condition after ${timeoutMs}ms`)
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs))
  }
}

const checkpointWaitingExecution = async (
  persistence: SQLiteCheckpointBackend,
  executionId: string,
  channel: string,
  step = 1,
): Promise<void> => {
  const manager = new CheckpointManager(persistence)
  await manager.checkpoint({
    execution_id: executionId,
    machine_name: 'dispatch-parity',
    spec_version: '1.1.1',
    current_state: 'wait',
    context: {},
    step,
    created_at: new Date().toISOString(),
    event: 'wait_for',
    waiting_channel: channel,
  })
}

describe('signals integration parity', () => {
  it(`${DISPATCH_FILE}::test_dispatch_integration`, async () => {
    const dir = mkdtempSync(join(tmpdir(), 'signals-int-dispatch-'))
    const persistence = new SQLiteCheckpointBackend(join(dir, 'checkpoints.sqlite'))
    const signals = new MemorySignalBackend()

    try {
      const channel = 'approval/task-1'
      await checkpointWaitingExecution(persistence, 'exec-1', channel)
      await sendAndNotify(signals, new NoOpTrigger(), channel, { approved: true })

      const resumed: Array<{ executionId: string; signalData: unknown }> = []
      const dispatcher = new SignalDispatcher(signals, persistence, {
        resumeFn: async (executionId, signalData) => {
          resumed.push({ executionId, signalData })
        },
      })

      const result = await dispatcher.dispatch(channel)

      expect(result).toEqual(['exec-1'])
      expect(resumed).toEqual([{ executionId: 'exec-1', signalData: { approved: true } }])
    } finally {
      persistence.close()
      rmSync(dir, { recursive: true, force: true })
    }
  })

  it(`${DISPATCH_FILE}::test_dispatch_all_integration`, async () => {
    const dir = mkdtempSync(join(tmpdir(), 'signals-int-dispatch-all-'))
    const persistence = new SQLiteCheckpointBackend(join(dir, 'checkpoints.sqlite'))
    const signals = new MemorySignalBackend()

    try {
      await checkpointWaitingExecution(persistence, 'exec-a', 'approval/a')
      await checkpointWaitingExecution(persistence, 'exec-b', 'approval/b')

      await signals.send('approval/a', { approved: true })
      await signals.send('approval/b', { approved: false })

      const resumed: string[] = []
      const dispatcher = new SignalDispatcher(signals, persistence, {
        resumeFn: async (executionId) => {
          resumed.push(executionId)
        },
      })

      const results = await dispatcher.dispatchAll()

      expect(results).toEqual({
        'approval/a': ['exec-a'],
        'approval/b': ['exec-b'],
      })
      expect(new Set(resumed)).toEqual(new Set(['exec-a', 'exec-b']))
    } finally {
      persistence.close()
      rmSync(dir, { recursive: true, force: true })
    }
  })

  it(`${DISPATCH_FILE}::test_dispatch_broadcast`, async () => {
    const dir = mkdtempSync(join(tmpdir(), 'signals-int-broadcast-'))
    const persistence = new SQLiteCheckpointBackend(join(dir, 'checkpoints.sqlite'))
    const signals = new MemorySignalBackend()

    try {
      const channel = 'broadcast/review'
      await checkpointWaitingExecution(persistence, 'exec-1', channel)
      await checkpointWaitingExecution(persistence, 'exec-2', channel)

      await signals.send(channel, { approved: true })

      const resumed: string[] = []
      const dispatcher = new SignalDispatcher(signals, persistence, {
        resumeFn: async (executionId) => {
          resumed.push(executionId)
        },
      })

      const result = await dispatcher.dispatch(channel)

      expect(new Set(result)).toEqual(new Set(['exec-1', 'exec-2']))
      expect(new Set(resumed)).toEqual(new Set(['exec-1', 'exec-2']))
    } finally {
      persistence.close()
      rmSync(dir, { recursive: true, force: true })
    }
  })

  it(`${DISPATCH_FILE}::test_dispatch_no_waiters`, async () => {
    const dir = mkdtempSync(join(tmpdir(), 'signals-int-no-waiters-'))
    const persistence = new SQLiteCheckpointBackend(join(dir, 'checkpoints.sqlite'))
    const signals = new MemorySignalBackend()

    try {
      await signals.send('orphan/channel', { orphaned: true })

      const dispatcher = new SignalDispatcher(signals, persistence)
      const resumed = await dispatcher.dispatch('orphan/channel')

      expect(resumed).toEqual([])

      const stillQueued = await signals.consume('orphan/channel')
      expect(stillQueued?.data).toEqual({ orphaned: true })
    } finally {
      persistence.close()
      rmSync(dir, { recursive: true, force: true })
    }
  })

  it(`${DISPATCH_FILE}::test_dispatch_stale_checkpoint_skipped`, async () => {
    const dir = mkdtempSync(join(tmpdir(), 'signals-int-stale-'))
    const persistence = new SQLiteCheckpointBackend(join(dir, 'checkpoints.sqlite'))
    const signals = new MemorySignalBackend()

    try {
      const manager = new CheckpointManager(persistence)
      await manager.checkpoint({
        execution_id: 'exec-stale',
        machine_name: 'dispatch-parity',
        spec_version: '1.1.1',
        current_state: 'wait',
        context: {},
        step: 1,
        created_at: new Date().toISOString(),
        event: 'wait_for',
        waiting_channel: 'approval/stale',
      })

      await manager.checkpoint({
        execution_id: 'exec-stale',
        machine_name: 'dispatch-parity',
        spec_version: '1.1.1',
        current_state: 'done',
        context: {},
        step: 2,
        created_at: new Date().toISOString(),
        event: 'machine_end',
      })

      await signals.send('approval/stale', { approved: true })

      const dispatcher = new SignalDispatcher(signals, persistence)
      const result = await dispatcher.dispatch('approval/stale')

      expect(result).toEqual([])

      const stillQueued = await signals.consume('approval/stale')
      expect(stillQueued?.data).toEqual({ approved: true })
    } finally {
      persistence.close()
      rmSync(dir, { recursive: true, force: true })
    }
  })

  it(`${DISPATCH_FILE}::test_dispatch_multiple_channels`, async () => {
    const dir = mkdtempSync(join(tmpdir(), 'signals-int-multi-channel-'))
    const persistence = new SQLiteCheckpointBackend(join(dir, 'checkpoints.sqlite'))
    const signals = new MemorySignalBackend()

    try {
      await checkpointWaitingExecution(persistence, 'exec-alpha', 'channel/alpha')
      await checkpointWaitingExecution(persistence, 'exec-beta', 'channel/beta')
      await checkpointWaitingExecution(persistence, 'exec-gamma', 'channel/gamma')

      await signals.send('channel/alpha', { value: 'a1' })
      await signals.send('channel/alpha', { value: 'a2' })
      await signals.send('channel/beta', { value: 'b1' })
      await signals.send('channel/gamma', { value: 'g1' })

      const resumed: Array<{ executionId: string; signalData: { value: string } }> = []
      const dispatcher = new SignalDispatcher(signals, persistence, {
        resumeFn: async (executionId, signalData) => {
          resumed.push({ executionId, signalData })
        },
      })

      const results = await dispatcher.dispatchAll()

      expect(results['channel/alpha']).toEqual(['exec-alpha', 'exec-alpha'])
      expect(results['channel/beta']).toEqual(['exec-beta'])
      expect(results['channel/gamma']).toEqual(['exec-gamma'])
      expect(resumed).toContainEqual({ executionId: 'exec-alpha', signalData: { value: 'a1' } })
      expect(resumed).toContainEqual({ executionId: 'exec-alpha', signalData: { value: 'a2' } })
    } finally {
      persistence.close()
      rmSync(dir, { recursive: true, force: true })
    }
  })

  it(`${DISPATCH_FILE}::test_dispatch_with_file_trigger`, async () => {
    const dispatchDir = mkdtempSync(join(tmpdir(), 'signals-int-file-trigger-'))
    const triggerDir = mkdtempSync(join(tmpdir(), 'signals-int-file-trigger-notify-'))
    const persistence = new SQLiteCheckpointBackend(join(dispatchDir, 'checkpoints.sqlite'))
    const signals = new MemorySignalBackend()

    try {
      const channel = 'approval/file'
      await checkpointWaitingExecution(persistence, 'exec-file', channel)

      await sendAndNotify(signals, new FileTrigger(triggerDir), channel, { approved: true })

      const resumed: string[] = []
      const dispatcher = new SignalDispatcher(signals, persistence, {
        resumeFn: async (executionId) => {
          resumed.push(executionId)
        },
      })

      const result = await dispatcher.dispatch(channel)

      expect(existsSync(join(triggerDir, 'trigger'))).toBe(true)
      expect(result).toEqual(['exec-file'])
      expect(resumed).toEqual(['exec-file'])
    } finally {
      persistence.close()
      rmSync(dispatchDir, { recursive: true, force: true })
      rmSync(triggerDir, { recursive: true, force: true })
    }
  })

  it(`${DISPATCH_FILE}::test_dispatch_with_socket_trigger`, async () => {
    const dispatchDir = mkdtempSync(join(tmpdir(), 'signals-int-socket-trigger-'))
    const persistence = new SQLiteCheckpointBackend(join(dispatchDir, 'checkpoints.sqlite'))
    const signals = new MemorySignalBackend()

    const dgram = require('node:dgram') as {
      createSocket: (...args: unknown[]) => {
        send: (payload: Buffer, socketPath: string, callback?: () => void) => void
        close: () => void
      }
    }

    const originalCreateSocket = dgram.createSocket
    const close = vi.fn()
    let notifiedPath = ''
    let notifiedChannel = ''

    dgram.createSocket = (() => ({
      send: (payload: Buffer, socketPath: string, callback?: () => void) => {
        notifiedPath = socketPath
        notifiedChannel = payload.toString('utf8')
        callback?.()
      },
      close,
    })) as typeof dgram.createSocket

    try {
      const channel = 'approval/socket'
      const socketPath = '/tmp/signals-integration-trigger.sock'
      await checkpointWaitingExecution(persistence, 'exec-socket', channel)

      await sendAndNotify(signals, new SocketTrigger(socketPath), channel, { approved: true })

      const resumed: string[] = []
      const dispatcher = new SignalDispatcher(signals, persistence, {
        resumeFn: async (executionId) => {
          resumed.push(executionId)
        },
      })

      const result = await dispatcher.dispatch(notifiedChannel)

      expect(notifiedChannel).toBe(channel)
      expect(notifiedPath).toBe(socketPath)
      expect(close).toHaveBeenCalledTimes(1)
      expect(result).toEqual(['exec-socket'])
      expect(resumed).toEqual(['exec-socket'])
    } finally {
      dgram.createSocket = originalCreateSocket
      persistence.close()
      rmSync(dispatchDir, { recursive: true, force: true })
    }
  })

  it(`${SOCKET_FILE}::test_socket_trigger_creates_listener`, async () => {
    const socketDir = mkdtempSync(join(tmpdir(), 'signals-int-listen-create-'))
    const socketPath = join(socketDir, 'dispatcher.sock')
    const persistence = new SQLiteCheckpointBackend(join(socketDir, 'checkpoints.sqlite'))
    const signals = new MemorySignalBackend()

    try {
      const dispatcher = new SignalDispatcher(signals, persistence)
      const maybeListen = (dispatcher as unknown as { listen?: (...args: any[]) => Promise<void> }).listen

      expect(typeof maybeListen).toBe('function')

      if (typeof maybeListen === 'function') {
        const stopEvent = {
          stopped: false,
          is_set() {
            return this.stopped
          },
          set() {
            this.stopped = true
          },
        }

        const listenTask = maybeListen.call(dispatcher, socketPath, stopEvent)
        await waitFor(() => existsSync(socketPath))
        stopEvent.set()
        await listenTask
      }
    } finally {
      persistence.close()
      rmSync(socketDir, { recursive: true, force: true })
    }
  })

  it(`${SOCKET_FILE}::test_socket_trigger_receives_message`, async () => {
    const dgram = require('node:dgram') as {
      createSocket: (...args: unknown[]) => {
        send: (payload: Buffer, socketPath: string, callback?: () => void) => void
        close: () => void
      }
    }

    const originalCreateSocket = dgram.createSocket
    const close = vi.fn()
    let sentChannel = ''
    let sentPath = ''

    dgram.createSocket = (() => ({
      send: (payload: Buffer, socketPath: string, callback?: () => void) => {
        sentChannel = payload.toString('utf8')
        sentPath = socketPath
        callback?.()
      },
      close,
    })) as typeof dgram.createSocket

    try {
      const socketPath = '/tmp/parity-socket-receive.sock'
      const trigger = new SocketTrigger(socketPath)
      await trigger.notify('approval/task-42')

      expect(sentChannel).toBe('approval/task-42')
      expect(sentPath).toBe(socketPath)
      expect(close).toHaveBeenCalledTimes(1)
    } finally {
      dgram.createSocket = originalCreateSocket
    }
  })

  it(`${SOCKET_FILE}::test_socket_trigger_cleanup_on_close`, async () => {
    const socketDir = mkdtempSync(join(tmpdir(), 'signals-int-listen-cleanup-'))
    const socketPath = join(socketDir, 'dispatcher.sock')
    const persistence = new SQLiteCheckpointBackend(join(socketDir, 'checkpoints.sqlite'))
    const signals = new MemorySignalBackend()

    try {
      const dispatcher = new SignalDispatcher(signals, persistence)
      const maybeListen = (dispatcher as unknown as { listen?: (...args: any[]) => Promise<void> }).listen

      expect(typeof maybeListen).toBe('function')

      if (typeof maybeListen === 'function') {
        const stopEvent = {
          stopped: false,
          is_set() {
            return this.stopped
          },
          set() {
            this.stopped = true
          },
        }

        const listenTask = maybeListen.call(dispatcher, socketPath, stopEvent)
        await waitFor(() => existsSync(socketPath))

        stopEvent.set()
        await listenTask

        expect(existsSync(socketPath)).toBe(false)
      }
    } finally {
      persistence.close()
      rmSync(socketDir, { recursive: true, force: true })
    }
  })

  it(`${SOCKET_FILE}::test_socket_trigger_handles_missing_socket`, async () => {
    const trigger = new SocketTrigger('/tmp/flatmachines-parity-missing.sock')

    await expect(trigger.notify('missing/socket/channel')).resolves.toBeUndefined()
  })
})

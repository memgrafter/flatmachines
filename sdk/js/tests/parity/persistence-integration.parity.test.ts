import { afterEach, describe, expect, it, vi } from 'vitest'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import {
  CheckpointManager,
  FlatMachine,
  MemoryBackend,
  SQLiteCheckpointBackend,
  SQLiteLeaseLock,
  WebhookHooks,
} from '@memgrafter/flatmachines'

const makeTempDir = () => mkdtempSync(join(tmpdir(), 'persistence-integration-parity-'))

const toEventList = (fetchMock: ReturnType<typeof vi.fn>) =>
  fetchMock.mock.calls.map((call) => {
    const body = (call[1] as RequestInit | undefined)?.body
    return JSON.parse(String(body ?? '{}')).event as string | undefined
  })

class CounterHooks {
  private crashAt?: number
  private crashed = false

  constructor(opts?: { crashAt?: number }) {
    this.crashAt = opts?.crashAt
  }

  async onAction(action: string, context: Record<string, any>) {
    if (action === 'increment') {
      context.count = (context.count ?? 0) + 1
      if (this.crashAt && context.count === this.crashAt && !this.crashed) {
        this.crashed = true
        throw new Error(`Crash at ${this.crashAt}`)
      }
    }
    return context
  }
}

class RetryHooks {
  async onAction(action: string, context: Record<string, any>) {
    if (action === 'work') {
      context.attempts = (context.attempts ?? 0) + 1
      if (context.attempts === 1) {
        throw new Error('transient failure')
      }
      context.count = (context.count ?? 0) + 1
    }
    if (action === 'mark_retry') {
      context.retries = (context.retries ?? 0) + 1
    }
    return context
  }
}

class AlwaysFailHooks {
  async onAction(action: string, context: Record<string, any>) {
    if (action === 'fail') {
      throw new Error('permanent failure')
    }
    if (action === 'retry_counter') {
      context.retries = (context.retries ?? 0) + 1
    }
    return context
  }
}

class ErrorContextHooks {
  async onAction(action: string, context: Record<string, any>) {
    if (action === 'explode') {
      throw new TypeError('boom!')
    }
    return context
  }
}

describe('persistence integration parity', () => {
  const tempDirs: string[] = []

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
    for (const dir of tempDirs.splice(0)) {
      rmSync(dir, { recursive: true, force: true })
    }
  })

  // backend lifecycle (2)
  it('test_backend_lifecycle.py::test_list_after_runs', async () => {
    const dir = makeTempDir()
    tempDirs.push(dir)
    const dbPath = join(dir, 'checkpoints.sqlite')
    const backend = new SQLiteCheckpointBackend(dbPath)

    const config = {
      spec: 'flatmachine',
      spec_version: '0.1.0',
      data: {
        name: 'counter',
        context: { count: 0 },
        states: {
          start: { type: 'initial', transitions: [{ to: 'count_up' }] },
          count_up: {
            action: 'increment',
            transitions: [
              { condition: 'context.count >= 3', to: 'end' },
              { to: 'count_up' },
            ],
          },
          end: { type: 'final', output: { final_count: 'context.count' } },
        },
      },
    }

    const m1 = new FlatMachine({ config, hooks: new CounterHooks(), persistence: backend })
    const m2 = new FlatMachine({ config, hooks: new CounterHooks(), persistence: backend })
    await m1.execute({})
    await m2.execute({})

    const ids = await backend.listExecutionIds()
    expect(new Set(ids)).toEqual(new Set([m1.executionId, m2.executionId]))

    backend.close()
  })

  it('test_backend_lifecycle.py::test_delete_after_run', async () => {
    const dir = makeTempDir()
    tempDirs.push(dir)
    const dbPath = join(dir, 'checkpoints.sqlite')
    const backend = new SQLiteCheckpointBackend(dbPath)

    const config = {
      spec: 'flatmachine',
      spec_version: '0.1.0',
      data: {
        name: 'counter',
        context: { count: 0 },
        states: {
          start: { type: 'initial', transitions: [{ to: 'count_up' }] },
          count_up: {
            action: 'increment',
            transitions: [
              { condition: 'context.count >= 2', to: 'end' },
              { to: 'count_up' },
            ],
          },
          end: { type: 'final', output: { final_count: 'context.count' } },
        },
      },
    }

    const m1 = new FlatMachine({ config, hooks: new CounterHooks(), persistence: backend })
    const m2 = new FlatMachine({ config, hooks: new CounterHooks(), persistence: backend })
    await m1.execute({})
    await m2.execute({})

    await backend.deleteExecution(m1.executionId)

    const ids = await backend.listExecutionIds()
    expect(ids).toEqual([m2.executionId])
    expect(await backend.loadLatest(m1.executionId)).toBeNull()
    expect(await backend.loadLatest(m2.executionId)).not.toBeNull()

    backend.close()
  })

  // locking (6)
  it('test_locking.py::test_acquire_release', async () => {
    const dir = makeTempDir()
    tempDirs.push(dir)
    const dbPath = join(dir, 'leases.sqlite')

    const lock = new SQLiteLeaseLock({ dbPath, ownerId: 'owner-a' })
    expect(await lock.acquire('exec-1')).toBe(true)
    await lock.release('exec-1')
    expect(await lock.acquire('exec-1')).toBe(true)
    await lock.release('exec-1')
    lock.close()
  })

  it('test_locking.py::test_acquire_twice_fails', async () => {
    const dir = makeTempDir()
    tempDirs.push(dir)
    const dbPath = join(dir, 'leases.sqlite')

    const a = new SQLiteLeaseLock({ dbPath, ownerId: 'owner-a' })
    const b = new SQLiteLeaseLock({ dbPath, ownerId: 'owner-b' })

    expect(await a.acquire('shared')).toBe(true)
    expect(await b.acquire('shared')).toBe(false)

    await a.release('shared')
    a.close()
    b.close()
  })

  it('test_locking.py::test_release_unowned', async () => {
    const dir = makeTempDir()
    tempDirs.push(dir)
    const dbPath = join(dir, 'leases.sqlite')

    const owner = new SQLiteLeaseLock({ dbPath, ownerId: 'owner' })
    const stranger = new SQLiteLeaseLock({ dbPath, ownerId: 'stranger' })
    const challenger = new SQLiteLeaseLock({ dbPath, ownerId: 'challenger' })

    expect(await owner.acquire('exec')).toBe(true)
    await stranger.release('exec')
    expect(await challenger.acquire('exec')).toBe(false)

    await owner.release('exec')
    owner.close()
    stranger.close()
    challenger.close()
  })

  it('test_locking.py::test_acquire_timeout', async () => {
    const dir = makeTempDir()
    tempDirs.push(dir)
    const dbPath = join(dir, 'leases.sqlite')

    const owner = new SQLiteLeaseLock({ dbPath, ownerId: 'owner' })
    const waiter = new SQLiteLeaseLock({ dbPath, ownerId: 'waiter' })

    expect(await owner.acquire('exec')).toBe(true)
    const started = Date.now()
    const acquired = await waiter.acquire('exec')
    const elapsedMs = Date.now() - started

    expect(acquired).toBe(false)
    expect(elapsedMs).toBeLessThan(2000)

    await owner.release('exec')
    owner.close()
    waiter.close()
  })

  it('test_locking.py::test_heartbeat_extends_lease', async () => {
    const dir = makeTempDir()
    tempDirs.push(dir)
    const dbPath = join(dir, 'leases.sqlite')

    const lock = new SQLiteLeaseLock({
      dbPath,
      ownerId: 'owner',
      ttlSeconds: 30,
      renewIntervalSeconds: 5,
    })

    const key = 'heartbeat-target'
    expect(await lock.acquire(key)).toBe(true)

    const db = (lock as any).db
    const first = db.prepare('SELECT lease_until FROM execution_leases WHERE execution_id = ?').get(key)
      .lease_until as number

    await new Promise((resolve) => setTimeout(resolve, 5300))

    const second = db.prepare('SELECT lease_until FROM execution_leases WHERE execution_id = ?').get(key)
      .lease_until as number

    expect(second).toBeGreaterThan(first)

    await lock.release(key)
    lock.close()
  }, 12000)

  it('test_locking.py::test_stale_lease_can_be_acquired', async () => {
    const dir = makeTempDir()
    tempDirs.push(dir)
    const dbPath = join(dir, 'leases.sqlite')

    const a = new SQLiteLeaseLock({ dbPath, ownerId: 'owner-a' })
    const b = new SQLiteLeaseLock({ dbPath, ownerId: 'owner-b' })
    const key = 'stale-key'

    expect(await a.acquire(key)).toBe(true)

    ;(a as any)._stopHeartbeat(key)
    const db = (a as any).db
    db.prepare('UPDATE execution_leases SET lease_until = ? WHERE execution_id = ?').run(
      Math.floor(Date.now() / 1000) - 1,
      key,
    )

    expect(await b.acquire(key)).toBe(true)

    await b.release(key)
    a.close()
    b.close()
  })

  // persistence (5)
  it('test_persistence.py::test_save_and_load', async () => {
    const dir = makeTempDir()
    tempDirs.push(dir)
    const backend = new SQLiteCheckpointBackend(join(dir, 'checkpoints.sqlite'))

    const snapshot = {
      execution_id: 'exec-save-load',
      machine_name: 'test',
      spec_version: '0.1.0',
      current_state: 'state-a',
      context: { count: 1 },
      step: 1,
      created_at: new Date('2026-01-01T00:00:00.000Z').toISOString(),
      event: 'execute',
    }

    await backend.save('exec-save-load/step_000001', snapshot)
    expect(await backend.load('exec-save-load/step_000001')).toEqual(snapshot)
    backend.close()
  })

  it('test_persistence.py::test_list_executions', async () => {
    const dir = makeTempDir()
    tempDirs.push(dir)
    const backend = new SQLiteCheckpointBackend(join(dir, 'checkpoints.sqlite'))

    const manager = new CheckpointManager(backend)
    await manager.checkpoint({
      execution_id: 'exec-a',
      machine_name: 'm',
      spec_version: '0.1.0',
      current_state: 'end',
      context: {},
      step: 1,
      created_at: new Date().toISOString(),
      event: 'machine_end',
    })
    await manager.checkpoint({
      execution_id: 'exec-b',
      machine_name: 'm',
      spec_version: '0.1.0',
      current_state: 'end',
      context: {},
      step: 1,
      created_at: new Date().toISOString(),
      event: 'machine_end',
    })

    expect(await backend.listExecutionIds()).toEqual(['exec-a', 'exec-b'])
    backend.close()
  })

  it('test_persistence.py::test_resume_from_checkpoint', async () => {
    const dir = makeTempDir()
    tempDirs.push(dir)
    const backend = new SQLiteCheckpointBackend(join(dir, 'checkpoints.sqlite'))

    const config = {
      spec: 'flatmachine',
      spec_version: '0.1.0',
      data: {
        name: 'resume-machine',
        context: { count: 0 },
        states: {
          start: { type: 'initial', transitions: [{ to: 'count' }] },
          count: {
            action: 'increment',
            transitions: [
              { condition: 'context.count >= 4', to: 'end' },
              { to: 'count' },
            ],
          },
          end: { type: 'final', output: { final_count: 'context.count' } },
        },
      },
    }

    const firstRun = new FlatMachine({
      config,
      hooks: new CounterHooks({ crashAt: 2 }),
      persistence: backend,
    })

    await expect(firstRun.execute({})).rejects.toThrow('Crash at 2')

    const resumed = new FlatMachine({
      config,
      hooks: new CounterHooks(),
      persistence: backend,
    })

    const output = await resumed.resume(firstRun.executionId)
    expect(output.final_count).toBe(4)

    backend.close()
  })

  it('test_persistence.py::test_checkpoint_metadata', async () => {
    const dir = makeTempDir()
    tempDirs.push(dir)
    const backend = new SQLiteCheckpointBackend(join(dir, 'checkpoints.sqlite'))

    const config = {
      spec: 'flatmachine',
      spec_version: '0.1.0',
      data: {
        name: 'metadata-machine',
        context: { count: 0 },
        persistence: {
          enabled: true,
          backend: 'sqlite',
          checkpoint_on: ['machine_start', 'execute', 'machine_end'],
        },
        states: {
          start: { type: 'initial', transitions: [{ to: 'count' }] },
          count: {
            action: 'increment',
            transitions: [{ condition: 'context.count >= 1', to: 'end' }, { to: 'count' }],
          },
          end: { type: 'final', output: { final_count: 'context.count' } },
        },
      },
    }

    const machine = new FlatMachine({
      config,
      hooks: new CounterHooks(),
      persistence: backend,
    })

    await machine.execute({})
    const latest = await backend.loadLatest(machine.executionId)

    expect(latest?.execution_id).toBe(machine.executionId)
    expect(latest?.machine_name).toBe('metadata-machine')
    expect(latest?.current_state).toBe('end')
    expect(latest?.event).toBe('machine_end')
    expect(latest?.output).toEqual({ final_count: 1 })

    backend.close()
  })

  it('test_persistence.py::test_delete_execution', async () => {
    const dir = makeTempDir()
    tempDirs.push(dir)
    const backend = new SQLiteCheckpointBackend(join(dir, 'checkpoints.sqlite'))

    const manager = new CheckpointManager(backend)
    await manager.checkpoint({
      execution_id: 'keep',
      machine_name: 'm',
      spec_version: '0.1.0',
      current_state: 'end',
      context: {},
      step: 1,
      created_at: new Date().toISOString(),
      event: 'machine_end',
    })
    await manager.checkpoint({
      execution_id: 'remove',
      machine_name: 'm',
      spec_version: '0.1.0',
      current_state: 'end',
      context: {},
      step: 1,
      created_at: new Date().toISOString(),
      event: 'machine_end',
    })

    await backend.deleteExecution('remove')
    expect(await backend.listExecutionIds()).toEqual(['keep'])
    expect(await backend.loadLatest('remove')).toBeNull()

    backend.close()
  })

  // error recovery (4)
  it('test_error_recovery.py::test_retry_after_error', async () => {
    const config = {
      spec: 'flatmachine',
      spec_version: '0.1.0',
      data: {
        name: 'retry-after-error',
        context: { attempts: 0, retries: 0, count: 0 },
        states: {
          start: { type: 'initial', transitions: [{ to: 'work' }] },
          work: {
            action: 'work',
            on_error: 'retry',
            transitions: [
              { condition: 'context.count >= 1', to: 'end' },
              { to: 'work' },
            ],
          },
          retry: {
            action: 'mark_retry',
            transitions: [{ to: 'work' }],
          },
          end: {
            type: 'final',
            output: {
              count: 'context.count',
              retries: 'context.retries',
              attempts: 'context.attempts',
            },
          },
        },
      },
    }

    const machine = new FlatMachine({ config, hooks: new RetryHooks() })
    const result = await machine.execute({})

    expect(result).toEqual({ count: 1, retries: 1, attempts: 2 })
  })

  it('test_error_recovery.py::test_error_state_preserved', async () => {
    const config = {
      spec: 'flatmachine',
      spec_version: '0.1.0',
      data: {
        name: 'error-context',
        states: {
          start: { type: 'initial', transitions: [{ to: 'boom' }] },
          boom: {
            action: 'explode',
            on_error: 'recover',
            transitions: [{ to: 'end' }],
          },
          recover: {
            transitions: [{ to: 'end' }],
          },
          end: {
            type: 'final',
            output: {
              last_error: 'context.last_error',
              last_error_type: 'context.last_error_type',
            },
          },
        },
      },
    }

    const machine = new FlatMachine({ config, hooks: new ErrorContextHooks() })
    const result = await machine.execute({})

    expect(result.last_error).toBe('boom!')
    expect(result.last_error_type).toBe('TypeError')
  })

  it('test_error_recovery.py::test_resume_after_crash', async () => {
    const dir = makeTempDir()
    tempDirs.push(dir)
    const backend = new SQLiteCheckpointBackend(join(dir, 'checkpoints.sqlite'))

    const config = {
      spec: 'flatmachine',
      spec_version: '0.1.0',
      data: {
        name: 'resume-after-crash',
        context: { count: 0 },
        states: {
          start: { type: 'initial', transitions: [{ to: 'count' }] },
          count: {
            action: 'increment',
            transitions: [
              { condition: 'context.count >= 3', to: 'end' },
              { to: 'count' },
            ],
          },
          end: { type: 'final', output: { final_count: 'context.count' } },
        },
      },
    }

    const crashing = new FlatMachine({
      config,
      hooks: new CounterHooks({ crashAt: 1 }),
      persistence: backend,
    })
    await expect(crashing.execute({})).rejects.toThrow('Crash at 1')

    const resumed = new FlatMachine({
      config,
      hooks: new CounterHooks(),
      persistence: backend,
    })

    const result = await resumed.resume(crashing.executionId)
    expect(result.final_count).toBe(3)

    backend.close()
  })

  it('test_error_recovery.py::test_max_retries_reached', async () => {
    const config = {
      spec: 'flatmachine',
      spec_version: '0.1.0',
      data: {
        name: 'max-retries',
        context: { retries: 0 },
        states: {
          start: { type: 'initial', transitions: [{ to: 'work' }] },
          work: {
            action: 'fail',
            on_error: 'retry',
            transitions: [{ to: 'work' }],
          },
          retry: {
            action: 'retry_counter',
            transitions: [
              { condition: 'context.retries >= 3', to: 'failed' },
              { to: 'work' },
            ],
          },
          failed: {
            type: 'final',
            output: {
              status: 'failed',
              retries: 'context.retries',
              last_error: 'context.last_error',
            },
          },
        },
      },
    }

    const machine = new FlatMachine({ config, hooks: new AlwaysFailHooks() })
    const result = await machine.execute({})

    expect(result).toEqual({
      status: 'failed',
      retries: 3,
      last_error: 'permanent failure',
    })
  })

  // webhooks (5)
  it('test_webhooks.py::test_on_complete_fires', async () => {
    const fetchMock = vi.fn(async () => new Response('{}', { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    const config = {
      spec: 'flatmachine',
      spec_version: '0.1.0',
      data: {
        name: 'webhook-complete',
        states: {
          start: { type: 'initial', transitions: [{ to: 'end' }] },
          end: { type: 'final', output: { done: true } },
        },
      },
    }

    const machine = new FlatMachine({
      config,
      hooks: new WebhookHooks('https://example.test/webhooks'),
    })

    await machine.execute({})

    const events = toEventList(fetchMock)
    expect(events).toContain('machine_end')
  })

  it('test_webhooks.py::test_on_error_fires', async () => {
    const fetchMock = vi.fn(async () => new Response('{}', { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    const config = {
      spec: 'flatmachine',
      spec_version: '0.1.0',
      data: {
        name: 'webhook-error',
        states: {
          start: { type: 'initial', transitions: [{ to: 'boom' }] },
          boom: {
            agent: 'missing-agent.yml',
            on_error: 'end',
            transitions: [{ to: 'end' }],
          },
          end: { type: 'final', output: { done: true } },
        },
      },
    }

    const machine = new FlatMachine({
      config,
      hooks: new WebhookHooks('https://example.test/webhooks'),
    })

    await machine.execute({})

    const events = toEventList(fetchMock)
    expect(events).toContain('error')
  })

  it('test_webhooks.py::test_on_checkpoint_fires', async () => {
    const fetchMock = vi.fn(async () => new Response('{}', { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    const config = {
      spec: 'flatmachine',
      spec_version: '0.1.0',
      data: {
        name: 'webhook-checkpoint',
        persistence: {
          enabled: true,
          backend: 'memory',
          checkpoint_on: ['machine_start', 'execute', 'machine_end'],
        },
        states: {
          start: { type: 'initial', transitions: [{ to: 'end' }] },
          end: { type: 'final', output: { done: true } },
        },
      },
    }

    const machine = new FlatMachine({
      config,
      hooks: new WebhookHooks('https://example.test/webhooks'),
      persistence: new MemoryBackend(),
    })

    await machine.execute({})

    const events = toEventList(fetchMock)
    expect(events).toContain('checkpoint')
  })

  it('test_webhooks.py::test_webhook_payload_format', async () => {
    const fetchMock = vi.fn(async () => new Response('{}', { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    const hooks = new WebhookHooks('https://example.test/webhooks')
    const context = { alpha: 1, nested: { beta: true } }
    await hooks.onMachineStart(context)

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0]!
    const payload = JSON.parse(String((init as RequestInit).body))

    expect(url).toBe('https://example.test/webhooks')
    expect(payload.event).toBe('machine_start')
    expect(payload.context).toEqual(context)
    expect(typeof payload.timestamp).toBe('string')
    expect(new Date(payload.timestamp).toString()).not.toBe('Invalid Date')
  })

  it('test_webhooks.py::test_webhook_failure_does_not_block', async () => {
    const fetchMock = vi.fn(async () => {
      throw new Error('network unavailable')
    })
    vi.stubGlobal('fetch', fetchMock)

    const config = {
      spec: 'flatmachine',
      spec_version: '0.1.0',
      data: {
        name: 'webhook-graceful-degradation',
        states: {
          start: { type: 'initial', transitions: [{ to: 'end' }] },
          end: { type: 'final', output: { done: true } },
        },
      },
    }

    const machine = new FlatMachine({
      config,
      hooks: new WebhookHooks('https://example.test/webhooks'),
    })

    const result = await machine.execute({})
    expect(result).toEqual({ done: true })
  })

  // machine launching (3)
  it('test_machine_launching.py::test_launch_creates_execution', async () => {
    const { inMemoryResultBackend } = await import('@memgrafter/flatmachines')

    const childConfig = {
      spec: 'flatmachine',
      spec_version: '0.1.0',
      data: {
        name: 'child',
        states: {
          start: { type: 'initial', transitions: [{ to: 'end' }] },
          end: { type: 'final', output: { child_value: 'input.value' } },
        },
      },
    }

    const parentConfig = {
      spec: 'flatmachine',
      spec_version: '0.1.0',
      data: {
        name: 'parent',
        context: { parent_value: 41 },
        machines: { child_machine: childConfig },
        states: {
          start: { type: 'initial', transitions: [{ to: 'call_child' }] },
          call_child: {
            machine: 'child_machine',
            input: { value: 'context.parent_value' },
            transitions: [{ to: 'end' }],
          },
          end: { type: 'final', output: { done: true } },
        },
      },
    }

    const writeSpy = vi.spyOn(inMemoryResultBackend, 'write')
    const parent = new FlatMachine({ config: parentConfig, resultBackend: inMemoryResultBackend })
    await parent.execute({})

    const uris = writeSpy.mock.calls.map(([uri]) => String(uri))
    const childResultUris = uris.filter(
      (uri) => uri.endsWith('/result') && !uri.includes(parent.executionId),
    )

    expect(childResultUris.length).toBeGreaterThanOrEqual(1)
  })

  it('test_machine_launching.py::test_launch_with_input', async () => {
    const { inMemoryResultBackend } = await import('@memgrafter/flatmachines')

    const childConfig = {
      spec: 'flatmachine',
      spec_version: '0.1.0',
      data: {
        name: 'child',
        states: {
          start: { type: 'initial', transitions: [{ to: 'end' }] },
          end: { type: 'final', output: { child_value: 'input.value' } },
        },
      },
    }

    const parentConfig = {
      spec: 'flatmachine',
      spec_version: '0.1.0',
      data: {
        name: 'parent',
        context: { parent_value: 99 },
        machines: { child_machine: childConfig },
        states: {
          start: { type: 'initial', transitions: [{ to: 'call_child' }] },
          call_child: {
            machine: 'child_machine',
            input: { value: 'context.parent_value' },
            output_to_context: { child_value: 'output.child_value' },
            transitions: [{ to: 'end' }],
          },
          end: { type: 'final', output: { final: 'context.child_value' } },
        },
      },
    }

    const machine = new FlatMachine({ config: parentConfig, resultBackend: inMemoryResultBackend })
    const result = await machine.execute({})

    expect(result).toEqual({ final: 99 })
  })

  it('test_machine_launching.py::test_launch_idempotent', async () => {
    const childUri = 'flatagents://child-exec/result'
    const writes: string[] = []
    const store = new Map<string, any>([[childUri, { child_value: 7 }]])

    const resultBackend = {
      async write(uri: string, data: any) {
        writes.push(uri)
        store.set(uri, data)
      },
      async read(uri: string) {
        return store.get(uri)
      },
      async exists(uri: string) {
        return store.has(uri)
      },
      async delete(uri: string) {
        store.delete(uri)
      },
    }

    const config = {
      spec: 'flatmachine',
      spec_version: '0.1.0',
      data: {
        name: 'idempotent-parent',
        states: {
          start: { type: 'initial', transitions: [{ to: 'end' }] },
          end: { type: 'final', output: { ok: true } },
        },
      },
    }

    const snapshot = {
      execution_id: 'parent-exec',
      machine_name: 'idempotent-parent',
      spec_version: '0.1.0',
      current_state: 'end',
      context: {},
      step: 1,
      created_at: new Date().toISOString(),
      pending_launches: [
        {
          execution_id: 'child-exec',
          machine: './missing-child.yml',
          input: { value: 7 },
          launched: false,
        },
      ],
    }

    const machine = new FlatMachine({ config, resultBackend: resultBackend as any })
    const output = await machine.execute(undefined, snapshot as any)

    expect(output).toEqual({ ok: true })
    expect(writes).not.toContain(childUri)
  })
})

import { mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'
import yaml from 'yaml'

import {
  CheckpointManager,
  FlatMachine,
  MemoryBackend,
  type MachineConfig,
  type ResultBackend,
} from '@memgrafter/flatmachines'

type CapturedWrite = { uri: string; data: any }

type CapturingResultBackend = ResultBackend & {
  writes: CapturedWrite[]
  waitForWrite(predicate: (write: CapturedWrite) => boolean): Promise<CapturedWrite>
}

function createCapturingResultBackend(): CapturingResultBackend {
  const store = new Map<string, any>()
  const readWaiters = new Map<string, Array<(value: any) => void>>()
  const writeWaiters: Array<{
    predicate: (write: CapturedWrite) => boolean
    resolve: (write: CapturedWrite) => void
    timer: ReturnType<typeof setTimeout>
  }> = []
  const writes: CapturedWrite[] = []

  return {
    writes,
    async write(uri: string, data: any): Promise<void> {
      store.set(uri, data)
      const write = { uri, data }
      writes.push(write)

      for (const resolve of readWaiters.get(uri) ?? []) {
        resolve(data)
      }
      readWaiters.delete(uri)

      for (const waiter of [...writeWaiters]) {
        if (!waiter.predicate(write)) continue
        clearTimeout(waiter.timer)
        writeWaiters.splice(writeWaiters.indexOf(waiter), 1)
        waiter.resolve(write)
      }
    },
    async read(uri: string, options?: { block?: boolean; timeout?: number }): Promise<any> {
      if (store.has(uri)) return store.get(uri)
      if (!options?.block) return undefined

      return new Promise((resolve, reject) => {
        const waiters = readWaiters.get(uri) ?? []
        waiters.push(resolve)
        readWaiters.set(uri, waiters)
        if (options.timeout !== undefined) {
          setTimeout(() => reject(new Error(`Timed out waiting for ${uri}`)), options.timeout)
        }
      })
    },
    async exists(uri: string): Promise<boolean> {
      return store.has(uri)
    },
    async delete(uri: string): Promise<void> {
      store.delete(uri)
    },
    async waitForWrite(predicate: (write: CapturedWrite) => boolean): Promise<CapturedWrite> {
      const existing = writes.find(predicate)
      if (existing) return existing
      return new Promise((resolve, reject) => {
        const timer = setTimeout(() => reject(new Error('Timed out waiting for result write')), 1000)
        writeWaiters.push({ predicate, resolve, timer })
      })
    },
  }
}

function leafMachine(name = 'leaf'): MachineConfig {
  return {
    spec: 'flatmachine',
    spec_version: '0.1.0',
    data: {
      name,
      states: {
        start: { type: 'initial', transitions: [{ to: 'done' }] },
        done: { type: 'final', output: { depth: 'context.machine.depth' } },
      },
    },
  }
}

function parentCallingChild(maxDepth: number): MachineConfig {
  return {
    spec: 'flatmachine',
    spec_version: '0.1.0',
    data: {
      name: 'parent',
      settings: { max_depth: maxDepth },
      machines: { child: leafMachine('child') },
      states: {
        start: { type: 'initial', transitions: [{ to: 'call_child' }] },
        call_child: {
          machine: 'child',
          output_to_context: { child_depth: 'output.depth' },
          transitions: [{ to: 'done' }],
        },
        done: { type: 'final', output: { child_depth: 'context.child_depth' } },
      },
    },
  }
}

function threeDeepMachine(maxDepth: number): MachineConfig {
  const grandchild = leafMachine('grandchild')
  const child: MachineConfig = {
    spec: 'flatmachine',
    spec_version: '0.1.0',
    data: {
      name: 'child',
      machines: { grandchild },
      states: {
        start: { type: 'initial', transitions: [{ to: 'call_grandchild' }] },
        call_grandchild: {
          machine: 'grandchild',
          output_to_context: { grandchild_depth: 'output.depth' },
          transitions: [{ to: 'done' }],
        },
        done: {
          type: 'final',
          output: {
            child_depth: 'context.machine.depth',
            grandchild_depth: 'context.grandchild_depth',
          },
        },
      },
    },
  }

  return {
    spec: 'flatmachine',
    spec_version: '0.1.0',
    data: {
      name: 'parent',
      settings: { max_depth: maxDepth },
      machines: { child },
      states: {
        start: { type: 'initial', transitions: [{ to: 'call_child' }] },
        call_child: {
          machine: 'child',
          output_to_context: {
            child_depth: 'output.child_depth',
            grandchild_depth: 'output.grandchild_depth',
          },
          transitions: [{ to: 'done' }],
        },
        done: {
          type: 'final',
          output: {
            child_depth: 'context.child_depth',
            grandchild_depth: 'context.grandchild_depth',
          },
        },
      },
    },
  }
}

describe('FlatMachine max_depth', () => {
  it('handles boundary behavior for depth=0, depth=1, and depth=max', async () => {
    const rootOnly: MachineConfig = {
      spec: 'flatmachine',
      spec_version: '0.1.0',
      data: {
        name: 'root-only',
        settings: { max_depth: 0 },
        states: {
          start: { type: 'initial', transitions: [{ to: 'done' }] },
          done: { type: 'final', output: { depth: 'context.machine.depth' } },
        },
      },
    }

    await expect(new FlatMachine({ config: rootOnly }).execute()).resolves.toEqual({ depth: 0 })
    await expect(new FlatMachine({ config: parentCallingChild(0) }).execute()).rejects.toThrow(
      'Machine depth limit exceeded: depth=1 > max_depth=0',
    )

    const childResult = await new FlatMachine({ config: parentCallingChild(1) }).execute()
    expect(Number(childResult.child_depth)).toBe(1)

    const maxDepthResult = await new FlatMachine({ config: threeDeepMachine(2) }).execute()
    expect(Number(maxDepthResult.child_depth)).toBe(1)
    expect(Number(maxDepthResult.grandchild_depth)).toBe(2)

    await expect(new FlatMachine({ config: threeDeepMachine(1) }).execute()).rejects.toThrow(
      'Machine depth limit exceeded: depth=2 > max_depth=1',
    )
  })

  it('limits recursive machine launches that hit max_depth', async () => {
    const dir = mkdtempSync(join(tmpdir(), 'flatmachine-max-depth-'))
    try {
      const recursiveConfig: MachineConfig = {
        spec: 'flatmachine',
        spec_version: '0.1.0',
        data: {
          name: 'recursive',
          settings: { max_depth: 2 },
          machines: { self: './recursive.yml' },
          states: {
            start: { type: 'initial', transitions: [{ to: 'call_self' }] },
            call_self: { machine: 'self', transitions: [{ to: 'done' }] },
            done: { type: 'final', output: { depth: 'context.machine.depth' } },
          },
        },
      }
      const configPath = join(dir, 'recursive.yml')
      writeFileSync(configPath, yaml.stringify(recursiveConfig), 'utf-8')

      await expect(new FlatMachine({ config: configPath }).execute()).rejects.toThrow(
        'Machine depth limit exceeded: depth=3 > max_depth=2',
      )
    } finally {
      rmSync(dir, { recursive: true, force: true })
    }
  })

  it('tracks depth for fire-and-forget launches', async () => {
    const resultBackend = createCapturingResultBackend()
    const config: MachineConfig = {
      spec: 'flatmachine',
      spec_version: '0.1.0',
      data: {
        name: 'launcher',
        settings: { max_depth: 1 },
        machines: { child: leafMachine('background-child') },
        states: {
          start: { type: 'initial', transitions: [{ to: 'launch_child' }] },
          launch_child: {
            launch: 'child',
            transitions: [{ to: 'done' }],
          },
          done: { type: 'final', output: { launched: true } },
        },
      },
    }

    const machine = new FlatMachine({ config, resultBackend })
    await expect(machine.execute()).resolves.toEqual({ launched: true })

    const parentUri = `flatagents://${machine.executionId}/result`
    const childWrite = await resultBackend.waitForWrite(
      ({ uri, data }) => uri !== parentUri && Number(data?.depth) === 1,
    )
    expect(Number(childWrite.data.depth)).toBe(1)

    const blockedConfig = { ...config, data: { ...config.data, settings: { max_depth: 0 } } }
    await expect(new FlatMachine({ config: blockedConfig, resultBackend }).execute()).rejects.toThrow(
      'Machine depth limit exceeded: depth=1 > max_depth=0',
    )
  })

  it('preserves depth in checkpoints and uses it on resume', async () => {
    const persistence = new MemoryBackend()
    const config: MachineConfig = {
      spec: 'flatmachine',
      spec_version: '0.1.0',
      data: {
        name: 'resumable-depth',
        settings: { max_depth: 1 },
        persistence: { enabled: true, backend: 'memory', checkpoint_on: ['execute'] },
        machines: { child: leafMachine('resume-child') },
        states: {
          start: { type: 'initial', transitions: [{ to: 'call_child' }] },
          call_child: { machine: 'child', transitions: [{ to: 'done' }] },
          done: { type: 'final', output: { ok: true } },
        },
      },
    }

    const firstRun = new FlatMachine({ config, persistence, depth: 1 } as any)
    await expect(firstRun.execute()).rejects.toThrow(
      'Machine depth limit exceeded: depth=2 > max_depth=1',
    )

    const manager = new CheckpointManager(persistence)
    const snapshot = await manager.restore(firstRun.executionId)
    expect(snapshot?.current_state).toBe('call_child')
    expect(snapshot?.depth).toBe(1)

    const resumed = new FlatMachine({ config, persistence })
    await expect(resumed.resume(firstRun.executionId)).rejects.toThrow(
      'Machine depth limit exceeded: depth=2 > max_depth=1',
    )
  })
})

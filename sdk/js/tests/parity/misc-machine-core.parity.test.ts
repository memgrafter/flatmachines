import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { describe, expect, it, vi } from 'vitest'
import yaml from 'yaml'

import {
  AgentAdapterRegistry,
  CheckpointManager,
  ClaudeCodeAdapter,
  CompositeHooks,
  FlatAgent,
  FlatMachine,
  FlatAgentAdapter,
  HooksRegistry,
  LocalFileBackend,
  MemoryBackend,
  ProfileManager,
  SQLiteCheckpointBackend,
  normalizeAgentRef,
  type ExecutionLock,
  type MachineConfig,
  type MachineHooks,
} from '@memgrafter/flatmachines'

const minimalMachine = (agents: Record<string, any>): MachineConfig => ({
  spec: 'flatmachine',
  spec_version: '0.8.0',
  data: {
    name: 'test-ref-resolution',
    agents,
    states: {
      start: {
        type: 'initial',
        agent: Object.keys(agents)[0] ?? 'noop',
        input: { task: 'hello' },
        transitions: [{ to: 'done' }],
      },
      done: {
        type: 'final',
        output: { ok: true },
      },
    },
  },
})

const writeJson = (dir: string, filename: string, data: unknown): string => {
  const path = join(dir, filename)
  writeFileSync(path, JSON.stringify(data, null, 2), 'utf-8')
  return path
}

const writeYaml = (dir: string, filename: string, data: unknown): string => {
  const path = join(dir, filename)
  writeFileSync(path, yaml.stringify(data), 'utf-8')
  return path
}

const withTempDir = async (prefix: string, run: (dir: string) => Promise<void> | void): Promise<void> => {
  const dir = mkdtempSync(join(tmpdir(), prefix))
  try {
    await run(dir)
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
}

const saveSnapshot = async (
  backend: any,
  executionId: string,
  event = 'state_exit',
  currentState = 'running',
  step = 1,
) => {
  const manager = new CheckpointManager(backend)
  await manager.checkpoint({
    execution_id: executionId,
    machine_name: 'test-machine',
    spec_version: '1.1.1',
    current_state: currentState,
    context: { some: 'data' },
    step,
    event,
    created_at: new Date('2026-03-20T08:38:22.000Z').toISOString(),
  })
}

class CounterHooks implements MachineHooks {
  async onAction(action: string, context: Record<string, any>): Promise<Record<string, any>> {
    if (action === 'increment') {
      context.count = (context.count ?? 0) + 1
    }
    return context
  }
}

class CounterWithStepHooks implements MachineHooks {
  public step: number

  constructor(args?: { step?: number }) {
    this.step = args?.step ?? 1
  }

  async onAction(action: string, context: Record<string, any>): Promise<Record<string, any>> {
    if (action === 'increment') {
      context.count = (context.count ?? 0) + this.step
    }
    return context
  }
}

class AppendHooks implements MachineHooks {
  async onAction(action: string, context: Record<string, any>): Promise<Record<string, any>> {
    if (action === 'append') {
      context.result = `${context.result ?? ''}${context.char ?? 'x'}`
    }
    return context
  }
}

class LifecycleTracker implements MachineHooks {
  public events: string[] = []

  async onMachineStart(context: Record<string, any>): Promise<Record<string, any>> {
    this.events.push('machine_start')
    return context
  }

  async onMachineEnd(context: Record<string, any>, output: any): Promise<any> {
    this.events.push('machine_end')
    return output
  }

  async onStateEnter(state: string, context: Record<string, any>): Promise<Record<string, any>> {
    this.events.push(`enter:${state}`)
    return context
  }

  async onStateExit(state: string, context: Record<string, any>, output: any): Promise<any> {
    this.events.push(`exit:${state}`)
    return output
  }

  async onAction(action: string, context: Record<string, any>): Promise<Record<string, any>> {
    this.events.push(`action:${action}`)
    if (action === 'increment') {
      context.count = (context.count ?? 0) + 1
    }
    return context
  }
}

const COUNTER_MACHINE: MachineConfig = {
  spec: 'flatmachine',
  spec_version: '1.2.0',
  data: {
    name: 'counter',
    hooks: 'counter' as any,
    context: { count: 0 },
    states: {
      start: { type: 'initial', transitions: [{ to: 'count_up' }] },
      count_up: {
        action: 'increment',
        transitions: [
          { condition: 'context.count >= 3', to: 'done' },
          { to: 'count_up' },
        ],
      },
      done: { type: 'final', output: { total: '{{ context.count }}' } },
    },
  },
}

const COUNTER_WITH_ARGS_MACHINE: MachineConfig = {
  spec: 'flatmachine',
  spec_version: '1.2.0',
  data: {
    name: 'counter-with-args',
    hooks: { name: 'counter-step', args: { step: 5 } } as any,
    context: { count: 0 },
    states: {
      start: { type: 'initial', transitions: [{ to: 'count_up' }] },
      count_up: {
        action: 'increment',
        transitions: [
          { condition: 'context.count >= 10', to: 'done' },
          { to: 'count_up' },
        ],
      },
      done: { type: 'final', output: { total: '{{ context.count }}' } },
    },
  },
}

const COMPOSITE_HOOKS_MACHINE: MachineConfig = {
  spec: 'flatmachine',
  spec_version: '1.2.0',
  data: {
    name: 'composite',
    hooks: ['lifecycle', 'counter'] as any,
    context: { count: 0 },
    states: {
      start: { type: 'initial', transitions: [{ to: 'count_up' }] },
      count_up: {
        action: 'increment',
        transitions: [
          { condition: 'context.count >= 2', to: 'done' },
          { to: 'count_up' },
        ],
      },
      done: { type: 'final', output: { total: '{{ context.count }}' } },
    },
  },
}

const NO_HOOKS_MACHINE: MachineConfig = {
  spec: 'flatmachine',
  spec_version: '1.2.0',
  data: {
    name: 'no-hooks',
    context: { value: 'hello' },
    states: {
      start: { type: 'initial', transitions: [{ to: 'done' }] },
      done: { type: 'final', output: { result: '{{ context.value }}' } },
    },
  },
}

const PARENT_CHILD_MACHINE: MachineConfig = {
  spec: 'flatmachine',
  spec_version: '1.2.0',
  data: {
    name: 'parent',
    hooks: 'append' as any,
    context: { result: '', char: 'P' },
    machines: {
      child: {
        spec: 'flatmachine',
        spec_version: '1.2.0',
        data: {
          name: 'child',
          hooks: 'append' as any,
          context: { result: '{{ input.prefix }}', char: 'C' },
          states: {
            start: { type: 'initial', transitions: [{ to: 'do_append' }] },
            do_append: { action: 'append', transitions: [{ to: 'done' }] },
            done: { type: 'final', output: { child_result: '{{ context.result }}' } },
          },
        },
      },
    },
    states: {
      start: { type: 'initial', transitions: [{ to: 'parent_append' }] },
      parent_append: { action: 'append', transitions: [{ to: 'call_child' }] },
      call_child: {
        machine: 'child',
        input: { prefix: '{{ context.result }}' },
        output_to_context: { child_result: '{{ output.child_result }}' },
        transitions: [{ to: 'done' }],
      },
      done: {
        type: 'final',
        output: {
          parent_result: '{{ context.result }}',
          child_result: '{{ context.child_result }}',
        },
      },
    },
  },
}

describe('helloworld machine parity', () => {
  it('sdk/python/tests/unit/test_helloworld_machine.py::TestHelloworldConditions.test_expected_char_computed_correctly', () => {
    const machine = new FlatMachine({ config: minimalMachine({}) })
    const result = (machine as any).render(
      '{{ context.target[context.current|length] }}',
      { context: { target: 'HELLO', current: 'HE' } },
    )
    expect(result).toBe('L')
  })

  it('sdk/python/tests/unit/test_helloworld_machine.py::TestHelloworldConditions.test_expected_char_at_start', () => {
    const machine = new FlatMachine({ config: minimalMachine({}) })
    const result = (machine as any).render(
      '{{ context.target[context.current|length] }}',
      { context: { target: 'HELLO', current: '' } },
    )
    expect(result).toBe('H')
  })

  it('sdk/python/tests/unit/test_helloworld_machine.py::TestHelloworldConditions.test_append_char_concatenation', () => {
    const machine = new FlatMachine({ config: minimalMachine({}) })
    const result = (machine as any).render(
      '{{ context.current }}{{ context.last_output }}',
      { context: { current: 'HEL', last_output: 'L' } },
    )
    expect(result).toBe('HELL')
  })

  it('sdk/python/tests/unit/test_helloworld_machine.py::TestHelloworldConditions.test_condition_correct_output', () => {
    const machine = new FlatMachine({ config: minimalMachine({}) })
    const ok = (machine as any).evaluateExpr(
      'context.last_output == context.expected_char',
      { context: { last_output: 'L', expected_char: 'L' }, input: {}, output: {} },
    )
    expect(ok).toBe(true)
  })

  it('sdk/python/tests/unit/test_helloworld_machine.py::TestHelloworldConditions.test_condition_wrong_output', () => {
    const machine = new FlatMachine({ config: minimalMachine({}) })
    const ok = (machine as any).evaluateExpr(
      'context.last_output == context.expected_char',
      { context: { last_output: 'X', expected_char: 'L' }, input: {}, output: {} },
    )
    expect(ok).toBe(false)
  })

  it('sdk/python/tests/unit/test_helloworld_machine.py::TestHelloworldConditions.test_condition_target_reached', () => {
    const machine = new FlatMachine({ config: minimalMachine({}) })
    const ok = (machine as any).evaluateExpr(
      'context.current == context.target',
      { context: { current: 'HELLO', target: 'HELLO' }, input: {}, output: {} },
    )
    expect(ok).toBe(true)
  })

  it('sdk/python/tests/unit/test_helloworld_machine.py::TestHelloworldConditions.test_condition_target_not_reached', () => {
    const machine = new FlatMachine({ config: minimalMachine({}) })
    const ok = (machine as any).evaluateExpr(
      'context.current == context.target',
      { context: { current: 'HELL', target: 'HELLO' }, input: {}, output: {} },
    )
    expect(ok).toBe(false)
  })

  it('sdk/python/tests/unit/test_helloworld_machine.py::TestHelloworldAppendAction.test_append_char_action', async () => {
    const hooks: MachineHooks = {
      async onAction(action, context) {
        if (action === 'append_char') {
          context.current = `${context.current}${context.last_output}`
        }
        return context
      },
    }

    const machine = new FlatMachine({
      config: {
        spec: 'flatmachine',
        spec_version: '0.8.0',
        data: {
          context: { current: 'HE', last_output: 'L' },
          states: {
            start: {
              type: 'initial',
              action: 'append_char',
              transitions: [{ to: 'done' }],
            },
            done: {
              type: 'final',
              output: { current: '{{ context.current }}' },
            },
          },
        },
      },
      hooks,
    })

    const result = await machine.execute()
    expect(result.current).toBe('HEL')
  })

  it('sdk/python/tests/unit/test_helloworld_machine.py::TestHelloworldAppendAction.test_append_char_from_empty', async () => {
    const hooks: MachineHooks = {
      async onAction(action, context) {
        if (action === 'append_char') {
          context.current = `${context.current}${context.last_output}`
        }
        return context
      },
    }

    const machine = new FlatMachine({
      config: {
        spec: 'flatmachine',
        spec_version: '0.8.0',
        data: {
          context: { current: '', last_output: 'H' },
          states: {
            start: {
              type: 'initial',
              action: 'append_char',
              transitions: [{ to: 'done' }],
            },
            done: {
              type: 'final',
              output: { current: '{{ context.current }}' },
            },
          },
        },
      },
      hooks,
    })

    const result = await machine.execute()
    expect(result.current).toBe('H')
  })
})

describe('machine is the job parity', () => {
  it('sdk/python/tests/unit/test_machine_is_the_job.py::TestListExecutionIdsFiltered.test_filter_by_event', async () => {
    await withTempDir('machine-job-filter-by-event-', async (dir) => {
      const sqlite = new SQLiteCheckpointBackend(join(dir, 'checkpoints.sqlite'))
      try {
        for (const backend of [new LocalFileBackend(join(dir, 'local')), new MemoryBackend(), sqlite]) {
          await saveSnapshot(backend, 'done-1', 'machine_end', 'final')
          await saveSnapshot(backend, 'running-1', 'state_exit', 'step_2')
          await saveSnapshot(backend, 'done-2', 'machine_end', 'final')

          const completed = await (backend as any).listExecutionIds({ event: 'machine_end' })
          expect(new Set(completed)).toEqual(new Set(['done-1', 'done-2']))
        }
      } finally {
        sqlite.close()
      }
    })
  })

  it('sdk/python/tests/unit/test_machine_is_the_job.py::TestListExecutionIdsFiltered.test_filter_no_match', async () => {
    await withTempDir('machine-job-filter-no-match-', async (dir) => {
      const sqlite = new SQLiteCheckpointBackend(join(dir, 'checkpoints.sqlite'))
      try {
        for (const backend of [new LocalFileBackend(join(dir, 'local')), new MemoryBackend(), sqlite]) {
          await saveSnapshot(backend, 'running-1', 'state_exit')
          await expect((backend as any).listExecutionIds({ event: 'machine_end' })).resolves.toEqual([])
        }
      } finally {
        sqlite.close()
      }
    })
  })

  it('sdk/python/tests/unit/test_machine_is_the_job.py::TestListExecutionIdsFiltered.test_filter_none_returns_all', async () => {
    await withTempDir('machine-job-filter-none-', async (dir) => {
      const sqlite = new SQLiteCheckpointBackend(join(dir, 'checkpoints.sqlite'))
      try {
        for (const backend of [new LocalFileBackend(join(dir, 'local')), new MemoryBackend(), sqlite]) {
          await saveSnapshot(backend, 'a', 'machine_end')
          await saveSnapshot(backend, 'b', 'state_exit')

          const allA = await (backend as any).listExecutionIds()
          const allB = await (backend as any).listExecutionIds({ event: null })
          expect(new Set(allA)).toEqual(new Set(['a', 'b']))
          expect(new Set(allB)).toEqual(new Set(['a', 'b']))
        }
      } finally {
        sqlite.close()
      }
    })
  })

  it('sdk/python/tests/unit/test_machine_is_the_job.py::TestListExecutionIdsFiltered.test_incomplete_is_set_difference', async () => {
    await withTempDir('machine-job-incomplete-', async (dir) => {
      const sqlite = new SQLiteCheckpointBackend(join(dir, 'checkpoints.sqlite'))
      try {
        for (const backend of [new LocalFileBackend(join(dir, 'local')), new MemoryBackend(), sqlite]) {
          await saveSnapshot(backend, 'done', 'machine_end')
          await saveSnapshot(backend, 'stuck', 'state_exit')
          await saveSnapshot(backend, 'new', 'machine_start')

          const allIds = new Set(await (backend as any).listExecutionIds())
          const doneIds = new Set(await (backend as any).listExecutionIds({ event: 'machine_end' }))
          const incomplete = [...allIds].filter((id) => !doneIds.has(id))
          expect(new Set(incomplete)).toEqual(new Set(['stuck', 'new']))
        }
      } finally {
        sqlite.close()
      }
    })
  })

  it('sdk/python/tests/unit/test_machine_is_the_job.py::TestLoadStatus.test_returns_event_and_state', async () => {
    await withTempDir('machine-job-load-status-event-state-', async (dir) => {
      const sqlite = new SQLiteCheckpointBackend(join(dir, 'checkpoints.sqlite'))
      try {
        for (const backend of [new LocalFileBackend(join(dir, 'local')), new MemoryBackend(), sqlite]) {
          await saveSnapshot(backend, 'exec-1', 'state_exit', 'step_2')
          const manager: any = new (CheckpointManager as any)(backend, 'exec-1')
          const status = await manager.loadStatus()
          expect(status).not.toBeNull()
          expect(status).toEqual(['state_exit', 'step_2'])
        }
      } finally {
        sqlite.close()
      }
    })
  })

  it('sdk/python/tests/unit/test_machine_is_the_job.py::TestLoadStatus.test_returns_none_for_missing', async () => {
    await withTempDir('machine-job-load-status-missing-', async (dir) => {
      const sqlite = new SQLiteCheckpointBackend(join(dir, 'checkpoints.sqlite'))
      try {
        for (const backend of [new LocalFileBackend(join(dir, 'local')), new MemoryBackend(), sqlite]) {
          const manager: any = new (CheckpointManager as any)(backend, 'nonexistent')
          await expect(manager.loadStatus()).resolves.toBeNull()
        }
      } finally {
        sqlite.close()
      }
    })
  })

  it('sdk/python/tests/unit/test_machine_is_the_job.py::TestLoadStatus.test_completed_execution', async () => {
    await withTempDir('machine-job-load-status-completed-', async (dir) => {
      const sqlite = new SQLiteCheckpointBackend(join(dir, 'checkpoints.sqlite'))
      try {
        for (const backend of [new LocalFileBackend(join(dir, 'local')), new MemoryBackend(), sqlite]) {
          await saveSnapshot(backend, 'exec-1', 'machine_end', 'done')
          const manager: any = new (CheckpointManager as any)(backend, 'exec-1')
          await expect(manager.loadStatus()).resolves.toEqual(['machine_end', 'done'])
        }
      } finally {
        sqlite.close()
      }
    })
  })

  it('sdk/python/tests/unit/test_machine_is_the_job.py::TestLoadStatus.test_reflects_latest_checkpoint', async () => {
    await withTempDir('machine-job-load-status-latest-', async (dir) => {
      const sqlite = new SQLiteCheckpointBackend(join(dir, 'checkpoints.sqlite'))
      try {
        for (const backend of [new LocalFileBackend(join(dir, 'local')), new MemoryBackend(), sqlite]) {
          await saveSnapshot(backend, 'exec-1', 'state_exit', 'step_1', 1)
          await saveSnapshot(backend, 'exec-1', 'state_exit', 'step_3', 2)
          const manager: any = new (CheckpointManager as any)(backend, 'exec-1')
          await expect(manager.loadStatus()).resolves.toEqual(['state_exit', 'step_3'])
        }
      } finally {
        sqlite.close()
      }
    })
  })

  it('sdk/python/tests/unit/test_machine_is_the_job.py::TestLoadStatus.test_cheaper_than_load_latest', async () => {
    await withTempDir('machine-job-load-status-cheaper-', async (dir) => {
      const sqlite = new SQLiteCheckpointBackend(join(dir, 'checkpoints.sqlite'))
      try {
        for (const backend of [new LocalFileBackend(join(dir, 'local')), new MemoryBackend(), sqlite]) {
          await saveSnapshot(backend, 'exec-1', 'machine_end', 'final')
          const manager: any = new (CheckpointManager as any)(backend, 'exec-1')
          const status = await manager.loadStatus()
          const full = await manager.loadLatest()
          expect(status).toEqual([full.event, full.current_state])
        }
      } finally {
        sqlite.close()
      }
    })
  })

  it('sdk/python/tests/unit/test_machine_is_the_job.py::TestPeerPropagation.test_launch_and_write_propagates_persistence', async () => {
    const childConfig: MachineConfig = {
      spec: 'flatmachine',
      spec_version: '1.1.1',
      data: {
        name: 'child',
        context: {},
        states: {
          start: { type: 'initial', transitions: [{ to: 'done' }] },
          done: { type: 'final', output: { done: true } },
        },
      },
    }

    const parentConfig: MachineConfig = {
      spec: 'flatmachine',
      spec_version: '1.1.1',
      data: {
        name: 'parent',
        machines: { child: childConfig },
        context: {},
        states: {
          start: { type: 'initial', machine: 'child', transitions: [{ to: 'done' }] },
          done: { type: 'final', output: {} },
        },
      },
    }

    const backend = new MemoryBackend()
    const lock: ExecutionLock = {
      acquire: vi.fn().mockResolvedValue(true),
      release: vi.fn().mockResolvedValue(undefined),
    }

    const parent = new FlatMachine({ config: parentConfig, persistence: backend, executionLock: lock })

    const originalCreateMachine = (FlatMachine.prototype as any).createMachine
    const createdPeers: FlatMachine[] = []
    ;(FlatMachine.prototype as any).createMachine = function (...args: any[]) {
      const created = originalCreateMachine.apply(this, args)
      if ((created as any).config?.data?.name === 'child') {
        createdPeers.push(created)
      }
      return created
    }

    try {
      await (parent as any).launchAndWrite('child', 'child-001', {})
    } finally {
      ;(FlatMachine.prototype as any).createMachine = originalCreateMachine
    }

    expect(createdPeers).toHaveLength(1)
    const peer: any = createdPeers[0]
    expect(peer.checkpointManager?.backend).toBe(backend)
    expect(peer.executionLock).toBe(lock)
  })
})

describe('agent ref resolution parity', () => {
  it('sdk/python/tests/unit/test_agent_ref_resolution.py::TestTypedRefResolution.test_claude_code_json_ref_resolved', async () => {
    await withTempDir('agent-ref-typed-json-', (dir) => {
      writeJson(dir, 'claude-coder.json', {
        model: 'sonnet',
        effort: 'high',
        permission_mode: 'bypassPermissions',
        tools: ['Bash', 'Read', 'Write', 'Edit'],
      })

      const machinePath = writeJson(dir, 'machine.json', minimalMachine({
        coder: { type: 'claude-code', ref: './claude-coder.json' },
      }))

      const machine = new FlatMachine({ config: machinePath })
      const agent = (machine.config.data.agents as any).coder

      expect(agent.ref).toBeUndefined()
      expect(agent.type).toBe('claude-code')
      expect(agent.config.model).toBe('sonnet')
      expect(agent.config.tools).toEqual(['Bash', 'Read', 'Write', 'Edit'])
      expect(agent.config.permission_mode).toBe('bypassPermissions')
    })
  })

  it('sdk/python/tests/unit/test_agent_ref_resolution.py::TestTypedRefResolution.test_inline_config_overrides_file', async () => {
    await withTempDir('agent-ref-inline-overrides-', (dir) => {
      writeJson(dir, 'base.json', {
        model: 'sonnet',
        max_budget_usd: 1.0,
        effort: 'low',
      })

      const machinePath = writeJson(dir, 'machine.json', minimalMachine({
        coder: {
          type: 'claude-code',
          ref: './base.json',
          config: { max_budget_usd: 5.0, timeout: 300 },
        },
      }))

      const machine = new FlatMachine({ config: machinePath })
      const agent = (machine.config.data.agents as any).coder

      expect(agent.config.model).toBe('sonnet')
      expect(agent.config.max_budget_usd).toBe(5.0)
      expect(agent.config.effort).toBe('low')
      expect(agent.config.timeout).toBe(300)
    })
  })

  it('sdk/python/tests/unit/test_agent_ref_resolution.py::TestTypedRefResolution.test_multiple_agents_different_refs', async () => {
    await withTempDir('agent-ref-multi-', (dir) => {
      writeJson(dir, 'planner.json', { model: 'opus', tools: ['Read', 'Grep', 'Glob'] })
      writeJson(dir, 'implementer.json', { model: 'sonnet', tools: ['Bash', 'Read', 'Write', 'Edit'] })

      const machinePath = writeJson(dir, 'machine.json', minimalMachine({
        planner: { type: 'claude-code', ref: './planner.json' },
        implementer: { type: 'claude-code', ref: './implementer.json' },
      }))

      const machine = new FlatMachine({ config: machinePath })

      expect(((machine.config.data.agents as any).planner.config.model)).toBe('opus')
      expect(((machine.config.data.agents as any).implementer.config.model)).toBe('sonnet')
      expect(((machine.config.data.agents as any).planner.ref)).toBeUndefined()
      expect(((machine.config.data.agents as any).implementer.ref)).toBeUndefined()
    })
  })

  it('sdk/python/tests/unit/test_agent_ref_resolution.py::TestTypedRefResolution.test_yaml_ref_resolved', async () => {
    await withTempDir('agent-ref-typed-yaml-', (dir) => {
      writeYaml(dir, 'agent.yml', { model: 'opus', effort: 'max' })

      const machinePath = writeJson(dir, 'machine.json', minimalMachine({
        coder: { type: 'claude-code', ref: './agent.yml' },
      }))

      const machine = new FlatMachine({ config: machinePath })
      const agent = (machine.config.data.agents as any).coder

      expect(agent.config.model).toBe('opus')
      expect(agent.ref).toBeUndefined()
    })
  })

  it('sdk/python/tests/unit/test_agent_ref_resolution.py::TestTypedRefResolution.test_nonexistent_ref_left_alone', async () => {
    await withTempDir('agent-ref-typed-missing-', (dir) => {
      const machinePath = writeJson(dir, 'machine.json', minimalMachine({
        coder: { type: 'claude-code', ref: './does-not-exist.json' },
      }))

      const machine = new FlatMachine({ config: machinePath })
      expect(((machine.config.data.agents as any).coder.ref)).toBe('./does-not-exist.json')
    })
  })

  it('sdk/python/tests/unit/test_agent_ref_resolution.py::TestStringRefResolution.test_flatagent_yaml_ref_resolved', async () => {
    await withTempDir('agent-ref-string-yaml-', (dir) => {
      writeYaml(dir, 'extractor.yml', {
        spec: 'flatagent',
        spec_version: '2.3.0',
        data: {
          name: 'extractor',
          model: { provider: 'anthropic', name: 'claude-sonnet-4-20250514' },
          system: 'Extract data.',
          user: '{{ input.text }}',
        },
      })

      const machinePath = writeJson(dir, 'machine.json', minimalMachine({ extractor: './extractor.yml' }))

      const machine = new FlatMachine({ config: machinePath })
      const agent = (machine.config.data.agents as any).extractor
      expect(agent.spec).toBe('flatagent')
      expect(agent.data.name).toBe('extractor')
    })
  })

  it('sdk/python/tests/unit/test_agent_ref_resolution.py::TestStringRefResolution.test_string_ref_nonexistent_left_alone', async () => {
    await withTempDir('agent-ref-string-missing-', (dir) => {
      const machinePath = writeJson(dir, 'machine.json', minimalMachine({ agent: 'not-a-file-path' }))
      const machine = new FlatMachine({ config: machinePath })
      expect(((machine.config.data.agents as any).agent)).toBe('not-a-file-path')
    })
  })

  it('sdk/python/tests/unit/test_agent_ref_resolution.py::TestInlineConfig.test_inline_claude_code_untouched', async () => {
    await withTempDir('agent-ref-inline-claude-', (dir) => {
      const machinePath = writeJson(dir, 'machine.json', minimalMachine({
        coder: {
          type: 'claude-code',
          config: { model: 'sonnet', tools: ['Bash', 'Read'] },
        },
      }))

      const machine = new FlatMachine({ config: machinePath })
      const agent = (machine.config.data.agents as any).coder
      expect(agent.config.model).toBe('sonnet')
      expect(agent.ref).toBeUndefined()
    })
  })

  it('sdk/python/tests/unit/test_agent_ref_resolution.py::TestInlineConfig.test_inline_flatagent_untouched', async () => {
    await withTempDir('agent-ref-inline-flatagent-', (dir) => {
      const machinePath = writeJson(dir, 'machine.json', minimalMachine({
        agent: {
          spec: 'flatagent',
          spec_version: '2.3.0',
          data: {
            model: { provider: 'openai', name: 'gpt-4' },
            system: 'Hello.',
            user: '{{ input.q }}',
          },
        },
      }))

      const machine = new FlatMachine({ config: machinePath })
      const agent = (machine.config.data.agents as any).agent
      expect(agent.spec).toBe('flatagent')
    })
  })

  it('sdk/python/tests/unit/test_agent_ref_resolution.py::TestConfigRawResolution.test_config_raw_contains_resolved_config', async () => {
    await withTempDir('agent-ref-config-raw-file-', (dir) => {
      writeJson(dir, 'claude.json', { model: 'opus', effort: 'high' })
      const machinePath = writeJson(dir, 'machine.json', minimalMachine({
        coder: { type: 'claude-code', ref: './claude.json' },
      }))

      const machine: any = new FlatMachine({ config: machinePath })
      expect(machine._config_raw).toBeDefined()
      expect(machine._config_raw).not.toContain('claude.json')
      expect(machine._config_raw).toContain('opus')
    })
  })

  it('sdk/python/tests/unit/test_agent_ref_resolution.py::TestConfigRawResolution.test_config_raw_from_dict_also_resolved', async () => {
    await withTempDir('agent-ref-config-raw-dict-', (dir) => {
      const absolute = writeJson(dir, 'cc.json', { model: 'sonnet', tools: ['Bash'] })
      const machine: any = new FlatMachine({
        config: minimalMachine({
          coder: { type: 'claude-code', ref: absolute },
        }),
      })

      expect(machine._config_raw).toBeDefined()
      expect(machine._config_raw).toContain('sonnet')
    })
  })

  it('sdk/python/tests/unit/test_agent_ref_resolution.py::TestClaudeCodeAdapterRefFallback.test_adapter_resolves_ref', async () => {
    await withTempDir('agent-ref-adapter-resolves-', (dir) => {
      writeJson(dir, 'agent.json', { model: 'opus', effort: 'max' })

      const adapter = new ClaudeCodeAdapter()
      const executor: any = adapter.create_executor({
        agent_name: 'coder',
        agent_ref: { type: 'claude-code', ref: './agent.json' },
        context: { config_dir: dir, settings: {}, machine_name: 'test' },
      })

      expect(executor.config.model).toBe('opus')
      expect(executor.config.effort).toBe('max')
    })
  })

  it('sdk/python/tests/unit/test_agent_ref_resolution.py::TestClaudeCodeAdapterRefFallback.test_adapter_prefers_config_over_ref', async () => {
    await withTempDir('agent-ref-adapter-prefers-config-', (dir) => {
      writeJson(dir, 'agent.json', { model: 'opus' })

      const adapter = new ClaudeCodeAdapter()
      const executor: any = adapter.create_executor({
        agent_name: 'coder',
        agent_ref: { type: 'claude-code', ref: './agent.json', config: { model: 'sonnet' } },
        context: { config_dir: dir, settings: {}, machine_name: 'test' },
      })

      expect(executor.config.model).toBe('sonnet')
    })
  })

  it('sdk/python/tests/unit/test_agent_ref_resolution.py::TestNormalizeAfterResolution.test_resolved_typed_ref', () => {
    const ref = normalizeAgentRef({ type: 'claude-code', config: { model: 'sonnet' } })
    expect(ref.type).toBe('claude-code')
    expect(ref.config).toEqual({ model: 'sonnet' })
    expect(ref.ref).toBeUndefined()
  })

  it('sdk/python/tests/unit/test_agent_ref_resolution.py::TestNormalizeAfterResolution.test_resolved_flatagent_inline', () => {
    const raw = {
      spec: 'flatagent',
      spec_version: '2.3.0',
      data: {
        model: { provider: 'openai', name: 'gpt-4' },
        system: 'Hello.',
        user: '{{ input.q }}',
      },
    }
    const ref = normalizeAgentRef(raw)
    expect(ref.type).toBe('flatagent')
    expect(ref.config).toEqual(raw)
    expect(ref.ref).toBeUndefined()
  })
})

describe('profiles discovery parity', () => {
  it('sdk/python/tests/unit/test_profiles_discovery.py::TestDiscoverProfilesFile.test_returns_explicit_path_when_provided', async () => {
    await withTempDir('profiles-discover-explicit-', (dir) => {
      const machine = new FlatMachine({ config: minimalMachine({}), configDir: dir })
      const explicit = '/some/explicit/path/profiles.yml'
      const resolved = (machine as any).resolveProfilesFile(explicit)
      expect(resolved).toBe(explicit)
    })
  })

  it('sdk/python/tests/unit/test_profiles_discovery.py::TestDiscoverProfilesFile.test_discovers_profiles_in_config_dir', async () => {
    await withTempDir('profiles-discover-in-config-dir-', (dir) => {
      writeFileSync(join(dir, 'profiles.yml'), 'spec: flatprofiles\ndata:\n  model_profiles: {}\n', 'utf-8')
      const machine = new FlatMachine({ config: minimalMachine({}), configDir: dir })
      const resolved = (machine as any).resolveProfilesFile(undefined)
      expect(resolved).toBe(join(dir, 'profiles.yml'))
    })
  })

  it('sdk/python/tests/unit/test_profiles_discovery.py::TestDiscoverProfilesFile.test_returns_none_when_no_profiles', async () => {
    await withTempDir('profiles-discover-none-', (dir) => {
      const machine = new FlatMachine({ config: minimalMachine({}), configDir: dir })
      const resolved = (machine as any).resolveProfilesFile(undefined)
      expect(resolved).toBeUndefined()
    })
  })

  it('sdk/python/tests/unit/test_profiles_discovery.py::TestDiscoverProfilesFile.test_explicit_path_takes_precedence', async () => {
    await withTempDir('profiles-discover-explicit-precedence-', (dir) => {
      writeFileSync(join(dir, 'profiles.yml'), 'spec: flatprofiles\ndata:\n  model_profiles: {}\n', 'utf-8')
      const machine = new FlatMachine({ config: minimalMachine({}), configDir: dir })
      const resolved = (machine as any).resolveProfilesFile('/explicit/profiles.yml')
      expect(resolved).toBe('/explicit/profiles.yml')
    })
  })

  it('sdk/python/tests/unit/test_profiles_discovery.py::TestDiscoverProfilesFile.test_empty_explicit_path_triggers_discovery', async () => {
    await withTempDir('profiles-discover-empty-explicit-', (dir) => {
      writeFileSync(join(dir, 'profiles.yml'), 'spec: flatprofiles\ndata:\n  model_profiles: {}\n', 'utf-8')
      const machine = new FlatMachine({ config: minimalMachine({}), configDir: dir })
      const resolved = (machine as any).resolveProfilesFile('')
      expect(resolved).toBe(join(dir, 'profiles.yml'))
    })
  })

  it('sdk/python/tests/unit/test_profiles_discovery.py::TestDiscoverProfilesFile.test_none_explicit_path_triggers_discovery', async () => {
    await withTempDir('profiles-discover-none-explicit-', (dir) => {
      writeFileSync(join(dir, 'profiles.yml'), 'spec: flatprofiles\ndata:\n  model_profiles: {}\n', 'utf-8')
      const machine = new FlatMachine({ config: minimalMachine({}), configDir: dir })
      const resolved = (machine as any).resolveProfilesFile(undefined)
      expect(resolved).toBe(join(dir, 'profiles.yml'))
    })
  })

  it('sdk/python/tests/unit/test_profiles_discovery.py::TestFlatAgentProfileDiscovery.test_agent_discovers_profiles_in_config_dir', async () => {
    await withTempDir('profiles-agent-discovers-', (dir) => {
      writeFileSync(join(dir, 'profiles.yml'), [
        'spec: flatprofiles',
        'spec_version: "0.7.1"',
        'data:',
        '  model_profiles:',
        '    test-profile:',
        '      provider: openai',
        '      name: gpt-4',
        '      temperature: 0.5',
        '  default: test-profile',
        '',
      ].join('\n'), 'utf-8')

      const agentPath = join(dir, 'agent.yml')
      writeFileSync(agentPath, [
        'spec: flatagent',
        'spec_version: "0.7.1"',
        'data:',
        '  name: test-agent',
        '  model: test-profile',
        '  system: "You are a test assistant."',
        '  user: "{{ input.query }}"',
        '',
      ].join('\n'), 'utf-8')

      const agent: any = new FlatAgent({ config: agentPath })
      expect(agent.profilesFile).toBe(join(dir, 'profiles.yml'))
      expect(agent.resolvedModelConfig).toMatchObject({ provider: 'openai', name: 'gpt-4', temperature: 0.5 })
    })
  })

  it('sdk/python/tests/unit/test_profiles_discovery.py::TestFlatAgentProfileDiscovery.test_agent_uses_explicit_profiles_file', async () => {
    await withTempDir('profiles-agent-explicit-', (dir) => {
      const profilesDir = join(dir, 'profiles')
      const agentsDir = join(dir, 'agents')
      mkdirSync(profilesDir, { recursive: true })
      mkdirSync(agentsDir, { recursive: true })

      const profilesPath = join(profilesDir, 'profiles.yml')
      writeFileSync(profilesPath, [
        'spec: flatprofiles',
        'spec_version: "0.7.1"',
        'data:',
        '  model_profiles:',
        '    explicit-profile:',
        '      provider: anthropic',
        '      name: claude-3-opus',
        '  default: explicit-profile',
        '',
      ].join('\n'), 'utf-8')

      const agentPath = join(agentsDir, 'agent.yml')
      writeFileSync(agentPath, [
        'spec: flatagent',
        'spec_version: "0.7.1"',
        'data:',
        '  name: test-agent',
        '  model: explicit-profile',
        '  system: "Test"',
        '  user: "{{ input.query }}"',
        '',
      ].join('\n'), 'utf-8')

      const agent: any = new FlatAgent({ config: agentPath, profilesFile: profilesPath })
      expect(agent.profilesFile).toBe(profilesPath)
      expect(agent.resolvedModelConfig).toMatchObject({ provider: 'anthropic', name: 'claude-3-opus' })
    })
  })

  it('sdk/python/tests/unit/test_profiles_discovery.py::TestFlatAgentProfileDiscovery.test_agent_works_without_profiles', async () => {
    await withTempDir('profiles-agent-no-profiles-', (dir) => {
      const agentPath = join(dir, 'agent.yml')
      writeFileSync(agentPath, [
        'spec: flatagent',
        'spec_version: "0.7.1"',
        'data:',
        '  name: test-agent',
        '  model:',
        '    provider: openai',
        '    name: gpt-4',
        '    temperature: 0.7',
        '  system: "Test"',
        '  user: "{{ input.query }}"',
        '',
      ].join('\n'), 'utf-8')

      const agent: any = new FlatAgent({ config: agentPath })
      expect(agent.profilesFile).toBeUndefined()
      expect(agent.resolvedModelConfig).toMatchObject({ provider: 'openai', name: 'gpt-4', temperature: 0.7 })
    })
  })

  it('sdk/python/tests/unit/test_profiles_discovery.py::TestFlatMachineProfileDiscovery.test_machine_discovers_profiles_in_config_dir', async () => {
    await withTempDir('profiles-machine-discovers-', (dir) => {
      writeFileSync(join(dir, 'profiles.yml'), [
        'spec: flatprofiles',
        'spec_version: "0.7.1"',
        'data:',
        '  model_profiles:',
        '    fast:',
        '      provider: openai',
        '      name: gpt-3.5-turbo',
        '  default: fast',
        '',
      ].join('\n'), 'utf-8')

      const machinePath = join(dir, 'machine.yml')
      writeFileSync(machinePath, [
        'spec: flatmachine',
        'spec_version: "0.7.1"',
        'data:',
        '  name: test-machine',
        '  states:',
        '    start:',
        '      type: initial',
        '      transitions:',
        '        - to: end',
        '    end:',
        '      type: final',
        '      output: {}',
        '',
      ].join('\n'), 'utf-8')

      const machine: any = new FlatMachine({ config: machinePath, configDir: dir })
      expect(machine.profilesFile).toBeUndefined()
    })
  })

  it('sdk/python/tests/unit/test_profiles_discovery.py::TestFlatMachineProfileDiscovery.test_machine_propagates_profiles_to_agents', async () => {
    await withTempDir('profiles-machine-propagates-', (dir) => {
      writeFileSync(join(dir, 'profiles.yml'), [
        'spec: flatprofiles',
        'spec_version: "0.7.1"',
        'data:',
        '  model_profiles:',
        '    smart:',
        '      provider: anthropic',
        '      name: claude-3-sonnet',
        '      temperature: 0.3',
        '  default: smart',
        '',
      ].join('\n'), 'utf-8')

      mkdirSync(join(dir, 'agents'), { recursive: true })
      const agentPath = join(dir, 'agents', 'child.yml')
      writeFileSync(agentPath, [
        'spec: flatagent',
        'spec_version: "0.7.1"',
        'data:',
        '  name: child-agent',
        '  model: smart',
        '  system: "You are helpful."',
        '  user: "{{ input.query }}"',
        '',
      ].join('\n'), 'utf-8')

      const machinePath = join(dir, 'machine.yml')
      writeFileSync(machinePath, [
        'spec: flatmachine',
        'spec_version: "0.7.1"',
        'data:',
        '  name: test-machine',
        '  agents:',
        '    child: ./agents/child.yml',
        '  states:',
        '    start:',
        '      type: initial',
        '      agent: child',
        '      input:',
        '        query: "test"',
        '      transitions:',
        '        - to: end',
        '    end:',
        '      type: final',
        '      output: {}',
        '',
      ].join('\n'), 'utf-8')

      const machine: any = new FlatMachine({ config: machinePath })
      const executor: any = machine.getExecutor('child')
      const agent: any = executor._agent

      expect(agent.resolvedModelConfig).toMatchObject({
        provider: 'anthropic',
        name: 'claude-3-sonnet',
        temperature: 0.3,
      })
    })
  })

  it('sdk/python/tests/unit/test_profiles_discovery.py::TestFlatMachineProfileDiscovery.test_machine_works_without_profiles', async () => {
    await withTempDir('profiles-machine-no-profiles-', (dir) => {
      const machinePath = join(dir, 'machine.yml')
      writeFileSync(machinePath, [
        'spec: flatmachine',
        'spec_version: "0.7.1"',
        'data:',
        '  name: test-machine',
        '  states:',
        '    start:',
        '      type: initial',
        '      transitions:',
        '        - to: end',
        '    end:',
        '      type: final',
        '      output: {}',
        '',
      ].join('\n'), 'utf-8')

      const machine: any = new FlatMachine({ config: machinePath, configDir: dir })
      expect(machine.profilesFile).toBeUndefined()
    })
  })

  it('sdk/python/tests/unit/test_profiles_discovery.py::TestProfileManagerCache.test_get_instance_caches_by_directory', async () => {
    await withTempDir('profiles-cache-same-instance-', (dir) => {
      writeFileSync(join(dir, 'profiles.yml'), [
        'spec: flatprofiles',
        'data:',
        '  model_profiles:',
        '    test: { provider: openai, name: gpt-4 }',
        '',
      ].join('\n'), 'utf-8')

      ProfileManager.clearCache()
      const manager1 = ProfileManager.getInstance(dir)
      const manager2 = ProfileManager.getInstance(dir)
      expect(manager1).toBe(manager2)
    })
  })

  it('sdk/python/tests/unit/test_profiles_discovery.py::TestProfileManagerCache.test_get_instance_returns_empty_when_no_profiles', async () => {
    await withTempDir('profiles-cache-empty-', (dir) => {
      ProfileManager.clearCache()
      const manager = ProfileManager.getInstance(dir)
      expect(manager.getProfiles()).toEqual({})
      expect(manager.getDefaultProfile()).toBeUndefined()
    })
  })
})

describe('hooks registry parity', () => {
  it('sdk/python/tests/integration/hooks_registry/test_hooks_registry.py::TestHooksRegistryUnit.test_register_and_has', () => {
    const registry = new HooksRegistry()
    expect(registry.has('counter')).toBe(false)
    registry.register('counter', CounterHooks)
    expect(registry.has('counter')).toBe(true)
  })

  it('sdk/python/tests/integration/hooks_registry/test_hooks_registry.py::TestHooksRegistryUnit.test_resolve_string', () => {
    const registry = new HooksRegistry()
    registry.register('counter', CounterHooks)
    const hooks = registry.resolve('counter')
    expect(hooks).toBeInstanceOf(CounterHooks)
  })

  it('sdk/python/tests/integration/hooks_registry/test_hooks_registry.py::TestHooksRegistryUnit.test_resolve_dict_with_args', () => {
    const registry = new HooksRegistry()
    registry.register('counter-step', CounterWithStepHooks as any)
    const hooks = registry.resolve({ name: 'counter-step', args: { step: 10 } } as any)
    expect(hooks).toBeInstanceOf(CounterWithStepHooks)
    expect((hooks as CounterWithStepHooks).step).toBe(10)
  })

  it('sdk/python/tests/integration/hooks_registry/test_hooks_registry.py::TestHooksRegistryUnit.test_resolve_list_creates_composite', () => {
    const registry = new HooksRegistry()
    registry.register('counter', CounterHooks)
    registry.register('lifecycle', LifecycleTracker)
    const hooks = registry.resolve(['lifecycle', 'counter'] as any)
    expect(hooks).toBeInstanceOf(CompositeHooks)
  })

  it('sdk/python/tests/integration/hooks_registry/test_hooks_registry.py::TestHooksRegistryUnit.test_resolve_unknown_name_raises', () => {
    const registry = new HooksRegistry()
    expect(() => registry.resolve('missing' as any)).toThrow("No hooks registered for name 'missing'")
  })

  it('sdk/python/tests/integration/hooks_registry/test_hooks_registry.py::TestHooksRegistryUnit.test_resolve_unknown_in_list_raises', () => {
    const registry = new HooksRegistry()
    registry.register('counter', CounterHooks)
    expect(() => registry.resolve(['counter', 'missing'] as any)).toThrow("No hooks registered for name 'missing'")
  })

  it('sdk/python/tests/integration/hooks_registry/test_hooks_registry.py::TestHooksRegistryUnit.test_factory_function', () => {
    const makeHooks = (args?: { step?: number }) => new CounterWithStepHooks(args)
    const registry = new HooksRegistry()
    registry.register('factory', makeHooks as any)
    const hooks = registry.resolve({ name: 'factory', args: { step: 7 } } as any)
    expect(hooks).toBeInstanceOf(CounterWithStepHooks)
    expect((hooks as CounterWithStepHooks).step).toBe(7)
  })

  it('sdk/python/tests/integration/hooks_registry/test_hooks_registry.py::TestHooksRegistryUnit.test_overwrite_registration', () => {
    const registry = new HooksRegistry()
    registry.register('x', CounterHooks)
    registry.register('x', AppendHooks)
    const hooks = registry.resolve('x')
    expect(hooks).toBeInstanceOf(AppendHooks)
  })

  it('sdk/python/tests/integration/hooks_registry/test_hooks_registry.py::TestHooksRegistryMachineIntegration.test_string_hooks_ref', async () => {
    const registry = new HooksRegistry()
    registry.register('counter', CounterHooks)
    const machine = new FlatMachine({ config: COUNTER_MACHINE, hooksRegistry: registry })
    const result = await machine.execute()
    expect(Number(result.total)).toBe(3)
  })

  it('sdk/python/tests/integration/hooks_registry/test_hooks_registry.py::TestHooksRegistryMachineIntegration.test_hooks_ref_with_args', async () => {
    const registry = new HooksRegistry()
    registry.register('counter-step', CounterWithStepHooks as any)
    const machine = new FlatMachine({ config: COUNTER_WITH_ARGS_MACHINE, hooksRegistry: registry })
    const result = await machine.execute()
    expect(Number(result.total)).toBe(10)
  })

  it('sdk/python/tests/integration/hooks_registry/test_hooks_registry.py::TestHooksRegistryMachineIntegration.test_composite_hooks_ref', async () => {
    const tracker = new LifecycleTracker()
    const registry = new HooksRegistry()
    registry.register('lifecycle', (() => tracker) as any)
    registry.register('counter', CounterHooks)

    const machine = new FlatMachine({ config: COMPOSITE_HOOKS_MACHINE, hooksRegistry: registry })
    const result = await machine.execute()

    expect(Number(result.total)).toBe(2)
    expect(tracker.events).toContain('machine_start')
    expect(tracker.events).toContain('machine_end')
    expect(tracker.events).toContain('action:increment')
  })

  it('sdk/python/tests/integration/hooks_registry/test_hooks_registry.py::TestHooksRegistryMachineIntegration.test_no_hooks_in_config', async () => {
    const machine = new FlatMachine({ config: NO_HOOKS_MACHINE })
    const result = await machine.execute()
    expect(result.result).toBe('hello')
  })

  it('sdk/python/tests/integration/hooks_registry/test_hooks_registry.py::TestHooksRegistryMachineIntegration.test_explicit_hooks_bypasses_registry', async () => {
    const hooks = new CounterWithStepHooks({ step: 100 })
    const machine = new FlatMachine({ config: COUNTER_MACHINE, hooks })
    const result = await machine.execute()
    expect(Number(result.total)).toBe(100)
  })

  it('sdk/python/tests/integration/hooks_registry/test_hooks_registry.py::TestHooksRegistryMachineIntegration.test_unregistered_hooks_raises', () => {
    expect(() => new FlatMachine({ config: COUNTER_MACHINE })).toThrow("No hooks registered for name 'counter'")
  })

  it('sdk/python/tests/integration/hooks_registry/test_hooks_registry.py::TestHooksRegistryMachineIntegration.test_registry_passed_to_constructor', async () => {
    const registry = new HooksRegistry()
    registry.register('counter', CounterHooks)
    const machine = new FlatMachine({ config: COUNTER_MACHINE, hooksRegistry: registry })
    const result = await machine.execute()
    expect(Number(result.total)).toBe(3)
  })

  it('sdk/python/tests/integration/hooks_registry/test_hooks_registry.py::TestHooksRegistryMachineIntegration.test_registry_shared_across_machines', async () => {
    const registry = new HooksRegistry()
    registry.register('counter', CounterHooks)

    const machine1 = new FlatMachine({ config: COUNTER_MACHINE, hooksRegistry: registry })
    const machine2 = new FlatMachine({ config: COUNTER_MACHINE, hooksRegistry: registry })

    const result1 = await machine1.execute()
    const result2 = await machine2.execute()
    expect(Number(result1.total)).toBe(3)
    expect(Number(result2.total)).toBe(3)
  })

  it('sdk/python/tests/integration/hooks_registry/test_hooks_registry.py::TestHooksRegistryChildPropagation.test_child_machine_inherits_registry', async () => {
    const registry = new HooksRegistry()
    registry.register('append', AppendHooks)

    const machine = new FlatMachine({ config: PARENT_CHILD_MACHINE, hooksRegistry: registry })
    const result = await machine.execute()

    expect(result.parent_result).toBe('P')
    expect(result.child_result).toBe('PC')
  })

  it('sdk/python/tests/integration/hooks_registry/test_hooks_registry.py::TestHooksRegistryProperty.test_property_returns_registry', () => {
    const machine = new FlatMachine({ config: NO_HOOKS_MACHINE })
    expect(machine.hooksRegistry).toBeInstanceOf(HooksRegistry)
  })

  it('sdk/python/tests/integration/hooks_registry/test_hooks_registry.py::TestHooksRegistryProperty.test_register_after_construction', () => {
    const machine = new FlatMachine({ config: NO_HOOKS_MACHINE })
    machine.hooksRegistry.register('counter', CounterHooks)
    expect(machine.hooksRegistry.has('counter')).toBe(true)
  })

  it('sdk/python/tests/integration/hooks_registry/test_hooks_registry.py::TestHooksRegistryProperty.test_register_before_execute_for_hooks_in_config', async () => {
    const registry = new HooksRegistry()
    registry.register('counter', CounterHooks)

    const machine = new FlatMachine({ config: COUNTER_MACHINE, hooksRegistry: registry })
    const result = await machine.execute()
    expect(Number(result.total)).toBe(3)
  })
})

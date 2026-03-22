import { describe, expect, it } from 'vitest'

import {
  CheckpointManager,
  FlatMachine,
  MemoryBackend,
  MemorySignalBackend,
  type MachineConfig,
  type MachineHooks,
} from '@memgrafter/flatmachines'

const PY_FILE = 'sdk/python/tests/unit/test_context_machine.py'

const simpleConfig = (states?: MachineConfig['data']['states']): MachineConfig => ({
  spec: 'flatmachine',
  spec_version: '2.0.0',
  data: {
    name: 'test-machine',
    context: {
      task: '{{ input.task }}',
    },
    agents: {},
    states:
      states ??
      {
        start: {
          type: 'initial',
          transitions: [{ to: 'middle' }],
        },
        middle: {
          transitions: [{ to: 'done' }],
        },
        done: {
          type: 'final',
          output: {
            result: 'ok',
          },
        },
      },
  },
})

const buildCaptureHooks = () => {
  const stateEntries: Record<string, Record<string, unknown>> = {}
  const hooks: MachineHooks = {
    async onStateEnter(state, context) {
      const machineMeta = context.machine as Record<string, unknown> | undefined
      if (machineMeta) {
        stateEntries[state] = { ...machineMeta }
      }
      return context
    },
  }
  return { hooks, stateEntries }
}

describe('context-machine parity (python unit test_context_machine.py)', () => {
  it(`${PY_FILE}::TestContextMachinePresent.test_context_machine_present_at_state_enter`, async () => {
    const { hooks, stateEntries } = buildCaptureHooks()
    const machine = new FlatMachine({ config: simpleConfig(), hooks })

    await machine.execute({ task: 'test' })

    expect(stateEntries.start).toBeDefined()
    expect(stateEntries.middle).toBeDefined()
  })

  it(`${PY_FILE}::TestContextMachinePresent.test_context_machine_has_all_fields`, async () => {
    const { hooks, stateEntries } = buildCaptureHooks()
    const machine = new FlatMachine({ config: simpleConfig(), hooks })

    await machine.execute({ task: 'test' })

    expect(Object.keys(stateEntries.start ?? {}).sort()).toEqual([
      'current_state',
      'execution_id',
      'machine_name',
      'parent_execution_id',
      'spec_version',
      'step',
      'total_api_calls',
      'total_cost',
    ])
  })

  it(`${PY_FILE}::TestContextMachinePresent.test_context_machine_values_correct`, async () => {
    const { hooks, stateEntries } = buildCaptureHooks()
    const machine = new FlatMachine({ config: simpleConfig(), hooks })

    await machine.execute({ task: 'test' })

    const meta = stateEntries.start ?? {}
    expect(meta.execution_id).toBe(machine.executionId)
    expect(meta.machine_name).toBe('test-machine')
    expect(meta.parent_execution_id).toBeNull()
    expect(meta.current_state).toBe('start')
    expect(meta.total_api_calls).toBe(0)
    expect(meta.total_cost).toBe(0)
  })

  it(`${PY_FILE}::TestContextMachineImmutable.test_mapping_proxy_type`, async () => {
    let capturedMachine: Record<string, unknown> | undefined
    const hooks: MachineHooks = {
      async onStateEnter(state, context) {
        if (state === 'start') {
          capturedMachine = context.machine as Record<string, unknown>
        }
        return context
      },
    }

    const machine = new FlatMachine({ config: simpleConfig(), hooks })
    await machine.execute({ task: 'test' })

    expect(capturedMachine).toBeDefined()
    expect(Object.isFrozen(capturedMachine as object)).toBe(true)
  })

  it(`${PY_FILE}::TestContextMachineImmutable.test_write_raises_type_error`, async () => {
    let errorRaised = false
    const hooks: MachineHooks = {
      async onStateEnter(state, context) {
        if (state === 'start') {
          try {
            ;(context.machine as Record<string, unknown>).execution_id = 'tampered'
          } catch (err) {
            errorRaised = err instanceof TypeError
          }
        }
        return context
      },
    }

    const machine = new FlatMachine({ config: simpleConfig(), hooks })
    await machine.execute({ task: 'test' })

    expect(errorRaised).toBe(true)
  })

  it(`${PY_FILE}::TestContextMachineOverwrite.test_overwrite_discarded_at_next_step`, async () => {
    let sawOverwrite = false
    const stateEntries: Record<string, Record<string, unknown>> = {}

    const hooks: MachineHooks = {
      async onStateEnter(state, context) {
        if (state === 'middle') {
          context.machine = { execution_id: 'tampered' }
          sawOverwrite = true
        }
        const machineMeta = context.machine as Record<string, unknown> | undefined
        if (machineMeta) {
          stateEntries[state] = { ...machineMeta }
        }
        return context
      },
    }

    const machine = new FlatMachine({ config: simpleConfig(), hooks })
    await machine.execute({ task: 'test' })

    expect(sawOverwrite).toBe(true)
    expect(stateEntries.done?.execution_id).toBe(machine.executionId)
    expect(stateEntries.done?.current_state).toBe('done')
  })

  it(`${PY_FILE}::TestContextMachineUpdates.test_step_increments`, async () => {
    const { hooks, stateEntries } = buildCaptureHooks()
    const machine = new FlatMachine({ config: simpleConfig(), hooks })

    await machine.execute({ task: 'test' })

    expect(stateEntries.start?.step).toBe(1)
    expect(stateEntries.middle?.step).toBe(2)
    expect(stateEntries.done?.step).toBe(3)
  })

  it(`${PY_FILE}::TestContextMachineUpdates.test_current_state_updates`, async () => {
    const { hooks, stateEntries } = buildCaptureHooks()
    const machine = new FlatMachine({ config: simpleConfig(), hooks })

    await machine.execute({ task: 'test' })

    expect(stateEntries.start?.current_state).toBe('start')
    expect(stateEntries.middle?.current_state).toBe('middle')
    expect(stateEntries.done?.current_state).toBe('done')
  })

  it(`${PY_FILE}::TestContextMachineInConditions.test_condition_on_step`, async () => {
    const machine = new FlatMachine({
      config: simpleConfig({
        start: {
          type: 'initial',
          transitions: [{ to: 'loop' }],
        },
        loop: {
          transitions: [
            { condition: 'context.machine.step >= 3', to: 'done' },
            { to: 'loop' },
          ],
        },
        done: {
          type: 'final',
          output: { result: 'ok' },
        },
      }),
    })

    const result = await machine.execute({ task: 'test' })
    expect(result).toEqual({ result: 'ok' })
  })

  it(`${PY_FILE}::TestContextMachineInConditions.test_condition_on_execution_id`, async () => {
    const hooks: MachineHooks = {
      async onStateEnter(state, context) {
        if (state === 'start') {
          context.my_id = (context.machine as Record<string, unknown>).execution_id
        }
        return context
      },
    }

    const machine = new FlatMachine({
      config: simpleConfig({
        start: {
          type: 'initial',
          transitions: [{ to: 'check' }],
        },
        check: {
          transitions: [
            { condition: 'context.machine.execution_id == context.my_id', to: 'done' },
            { to: 'fail' },
          ],
        },
        done: {
          type: 'final',
          output: { matched: true },
        },
        fail: {
          type: 'final',
          output: { matched: false },
        },
      }),
      hooks,
    })

    const result = await machine.execute({ task: 'test' })
    expect(result).toEqual({ matched: true })
  })

  it(`${PY_FILE}::TestContextMachineInConditions.test_condition_on_machine_name`, async () => {
    const machine = new FlatMachine({
      config: simpleConfig({
        start: {
          type: 'initial',
          transitions: [
            { condition: "context.machine.machine_name == 'test-machine'", to: 'done' },
            { to: 'fail' },
          ],
        },
        done: {
          type: 'final',
          output: { matched: true },
        },
        fail: {
          type: 'final',
          output: { matched: false },
        },
      }),
    })

    const result = await machine.execute({ task: 'test' })
    expect(result).toEqual({ matched: true })
  })

  it(`${PY_FILE}::TestContextMachineInTemplates.test_template_renders_execution_id`, async () => {
    const machine = new FlatMachine({
      config: simpleConfig({
        start: {
          type: 'initial',
          transitions: [{ to: 'done' }],
        },
        done: {
          type: 'final',
          output: {
            id: '{{ context.machine.execution_id }}',
            name: '{{ context.machine.machine_name }}',
          },
        },
      }),
    })

    const result = await machine.execute({ task: 'test' })
    expect(result.id).toBe(machine.executionId)
    expect(result.name).toBe('test-machine')
  })

  it(`${PY_FILE}::TestContextMachineSerialization.test_checkpoint_serializes_with_proxy`, async () => {
    const persistence = new MemoryBackend()
    const machine = new FlatMachine({
      config: simpleConfig(),
      persistence,
    })

    await machine.execute({ task: 'test' })

    const manager = new CheckpointManager(persistence)
    const snapshot = await manager.restore(machine.executionId)

    expect(snapshot).not.toBeNull()
    expect(typeof snapshot?.context.machine).toBe('object')
    expect(Object.isFrozen(snapshot?.context.machine as object)).toBe(false)
    expect((snapshot?.context.machine as Record<string, unknown>).machine_name).toBe('test-machine')
  })

  it(`${PY_FILE}::TestContextMachineResume.test_rebuilt_on_resume`, async () => {
    const persistence = new MemoryBackend()
    const signalBackend = new MemorySignalBackend()

    const waitConfig: MachineConfig = {
      spec: 'flatmachine',
      spec_version: '2.0.0',
      data: {
        name: 'resume-test',
        context: {},
        agents: {},
        states: {
          start: {
            type: 'initial',
            transitions: [{ to: 'wait_state' }],
          },
          wait_state: {
            wait_for: 'test/signal',
            output_to_context: {
              signal_value: '{{ output.value }}',
            },
            transitions: [{ to: 'done' }],
          },
          done: {
            type: 'final',
            output: {
              exec_id: '{{ context.machine.execution_id }}',
            },
          },
        },
      },
    }

    const machine1 = new FlatMachine({
      config: waitConfig,
      persistence,
      signalBackend,
    })

    const execId = machine1.executionId
    const result1 = await machine1.execute({})
    expect(result1._waiting).toBe(true)

    await signalBackend.send('test/signal', { value: 'hello' })

    const machine2 = new FlatMachine({
      config: waitConfig,
      persistence,
      signalBackend,
    })

    const result2 = await machine2.resume(execId)
    expect(result2.exec_id).toBe(execId)
  })
})

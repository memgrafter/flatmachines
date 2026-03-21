import { rmSync, mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

import * as flatmachines from '../../src'
import {
  CheckpointManager,
  FlatMachine,
  MemoryBackend,
  MemorySignalBackend,
  SignalDispatcher,
  type MachineHooks,
  type MachineSnapshot,
  type PersistenceBackend,
} from '../../src'

const DISPATCHER_FILE = 'sdk/python/tests/unit/test_dispatcher.py'
const WAIT_FOR_FILE = 'sdk/python/tests/unit/test_wait_for.py'
const LIFECYCLE_FILE = 'sdk/python/tests/integration/signals/test_wait_for_lifecycle.py'
const DISPATCH_SIGNALS_FILE = 'sdk/python/tests/unit/test_dispatch_signals.py'

const DISPATCH_SIGNALS_MODULE_PATH = '../../src/dispatch_signals'
const FLATMACHINE_MODULE_PATH = '../../src/flatmachine'

const loadDispatchSignalsModule = async (): Promise<any> => import(DISPATCH_SIGNALS_MODULE_PATH)
const loadFlatMachineModule = async (): Promise<any> => import(FLATMACHINE_MODULE_PATH)

const waitForConfig = (channel = 'test/channel') => ({
  spec: 'flatmachine' as const,
  spec_version: '1.1.1',
  data: {
    name: 'wait-test',
    context: {
      task_id: '{{ input.task_id }}',
      result: null,
    },
    states: {
      start: {
        type: 'initial' as const,
        transitions: [{ to: 'wait_state' }],
      },
      wait_state: {
        wait_for: channel,
        output_to_context: {
          result: '{{ output.value }}',
        },
        transitions: [
          { condition: "context.result == 'approved'", to: 'approved' },
          { to: 'rejected' },
        ],
      },
      approved: {
        type: 'final' as const,
        output: {
          status: 'approved',
          result: '{{ context.result }}',
        },
      },
      rejected: {
        type: 'final' as const,
        output: {
          status: 'rejected',
          result: '{{ context.result }}',
        },
      },
    },
  },
})

const templatedChannelConfig = () => ({
  spec: 'flatmachine' as const,
  spec_version: '1.1.1',
  data: {
    name: 'template-wait-test',
    context: {
      task_id: '{{ input.task_id }}',
      approved: null,
    },
    states: {
      start: {
        type: 'initial' as const,
        transitions: [{ to: 'wait_state' }],
      },
      wait_state: {
        wait_for: 'approval/{{ context.task_id }}',
        output_to_context: {
          approved: '{{ output.approved }}',
        },
        transitions: [{ to: 'done' }],
      },
      done: {
        type: 'final' as const,
        output: {
          approved: '{{ context.approved }}',
          task_id: '{{ context.task_id }}',
        },
      },
    },
  },
})

const dispatcherWaitConfig = (channel = 'test/ch') => ({
  spec: 'flatmachine' as const,
  spec_version: '1.1.1',
  data: {
    name: 'dispatch-test',
    context: {
      val: null,
    },
    states: {
      start: {
        type: 'initial' as const,
        transitions: [{ to: 'wait' }],
      },
      wait: {
        wait_for: channel,
        output_to_context: {
          val: '{{ output.v }}',
        },
        transitions: [{ to: 'done' }],
      },
      done: {
        type: 'final' as const,
        output: {
          val: '{{ context.val }}',
        },
      },
    },
  },
})

const approvalConfig = () => ({
  spec: 'flatmachine' as const,
  spec_version: '1.1.1',
  data: {
    name: 'approval-workflow',
    context: {
      task_id: '{{ input.task_id }}',
      prepared: false,
      approved: null,
      reviewer: null,
      finalized: false,
      final_status: null,
    },
    states: {
      start: {
        type: 'initial' as const,
        transitions: [{ to: 'prepare' }],
      },
      prepare: {
        action: 'prepare',
        transitions: [{ to: 'wait_for_approval' }],
      },
      wait_for_approval: {
        wait_for: 'approval/{{ context.task_id }}',
        timeout: 86400,
        output_to_context: {
          approved: '{{ output.approved }}',
          reviewer: '{{ output.reviewer }}',
        },
        transitions: [
          { condition: "context.approved == 'True'", to: 'finalize' },
          { to: 'rejected' },
        ],
      },
      finalize: {
        action: 'finalize',
        transitions: [{ to: 'done' }],
      },
      rejected: {
        action: 'finalize',
        transitions: [{ to: 'done' }],
      },
      done: {
        type: 'final' as const,
        output: {
          task_id: '{{ context.task_id }}',
          final_status: '{{ context.final_status }}',
          reviewer: '{{ context.reviewer }}',
        },
      },
    },
  },
})

const quotaConfig = () => ({
  spec: 'flatmachine' as const,
  spec_version: '1.1.1',
  data: {
    name: 'quota-consumer',
    context: {
      quota_token: null,
    },
    states: {
      start: {
        type: 'initial' as const,
        transitions: [{ to: 'wait_quota' }],
      },
      wait_quota: {
        wait_for: 'quota/openai',
        output_to_context: {
          quota_token: '{{ output.token }}',
        },
        transitions: [{ to: 'done' }],
      },
      done: {
        type: 'final' as const,
        output: {
          token: '{{ context.quota_token }}',
        },
      },
    },
  },
})

const approvalHooks = (): MachineHooks => ({
  onAction(action, context) {
    if (action === 'prepare') {
      context.prepared = true
      context.task_id = context.task_id ?? 'unknown'
    } else if (action === 'finalize') {
      context.finalized = true
      context.final_status = context.approved === 'True' ? 'approved' : 'rejected'
    }
    return context
  },
})

const parkMachine = async (
  persistence: PersistenceBackend,
  signalBackend: MemorySignalBackend,
  channel = 'test/ch',
): Promise<string> => {
  const machine = new FlatMachine({
    config: dispatcherWaitConfig(channel),
    persistence,
    signalBackend,
  } as any)

  const result = await machine.execute({})
  expect(result).toHaveProperty('_waiting_for', channel)
  return machine.executionId
}

const checkpointWaitingExecution = async (
  persistence: PersistenceBackend,
  executionId: string,
  waitingChannel: string,
  machineName = 'test-machine',
) => {
  const snapshot: MachineSnapshot = {
    execution_id: executionId,
    machine_name: machineName,
    spec_version: '2.0.0',
    current_state: 'wait_state',
    context: { task_id: 't-1' },
    step: 1,
    created_at: new Date().toISOString(),
    event: 'waiting',
    waiting_channel: waitingChannel,
  }
  await new CheckpointManager(persistence).checkpoint(snapshot)
}

describe('dispatcher parity', () => {
  it(`${DISPATCHER_FILE}::TestDispatch.test_dispatch_resumes_waiting_machine`, async () => {
    const persistence = new MemoryBackend()
    const signalBackend = new MemorySignalBackend()

    const executionId = await parkMachine(persistence, signalBackend)
    await signalBackend.send('test/ch', { v: 'hello' })

    const resumed: Array<[string, unknown]> = []
    const resumeFn = async (eid: string, signalData: unknown) => {
      resumed.push([eid, signalData])
    }

    const dispatcher = new SignalDispatcher(signalBackend, persistence, { resumeFn })
    const result = await dispatcher.dispatch('test/ch')

    expect(result).toEqual([executionId])
    expect(resumed).toEqual([[executionId, { v: 'hello' }]])
  })

  it(`${DISPATCHER_FILE}::TestDispatch.test_dispatch_no_signal_returns_empty`, async () => {
    const persistence = new MemoryBackend()
    const signalBackend = new MemorySignalBackend()

    await parkMachine(persistence, signalBackend)

    const dispatcher = new SignalDispatcher(signalBackend, persistence)
    await expect(dispatcher.dispatch('test/ch')).resolves.toEqual([])
  })

  it(`${DISPATCHER_FILE}::TestDispatch.test_dispatch_no_waiters_requeues_signal`, async () => {
    const persistence = new MemoryBackend()
    const signalBackend = new MemorySignalBackend()

    await signalBackend.send('orphan/ch', { data: true })

    const dispatcher = new SignalDispatcher(signalBackend, persistence)
    const result = await dispatcher.dispatch('orphan/ch')

    expect(result).toEqual([])
    await expect(signalBackend.consume('orphan/ch')).resolves.toMatchObject({ data: { data: true } })
  })

  it(`${DISPATCHER_FILE}::TestDispatch.test_dispatch_multiple_waiters`, async () => {
    const persistence = new MemoryBackend()
    const signalBackend = new MemorySignalBackend()

    const eid1 = await parkMachine(persistence, signalBackend, 'broadcast/ch')
    const eid2 = await parkMachine(persistence, signalBackend, 'broadcast/ch')
    await signalBackend.send('broadcast/ch', { v: 'wake' })

    const resumed: string[] = []
    const dispatcher = new SignalDispatcher(signalBackend, persistence, {
      resumeFn: async (eid) => {
        resumed.push(eid)
      },
    })

    const result = await dispatcher.dispatch('broadcast/ch')

    expect(new Set(result)).toEqual(new Set([eid1, eid2]))
    expect(new Set(resumed)).toEqual(new Set([eid1, eid2]))
  })

  it(`${DISPATCHER_FILE}::TestDispatch.test_dispatch_without_resume_fn`, async () => {
    const persistence = new MemoryBackend()
    const signalBackend = new MemorySignalBackend()

    const executionId = await parkMachine(persistence, signalBackend)
    await signalBackend.send('test/ch', { v: 'x' })

    const dispatcher = new SignalDispatcher(signalBackend, persistence)
    await expect(dispatcher.dispatch('test/ch')).resolves.toEqual([executionId])
  })

  it(`${DISPATCHER_FILE}::TestDispatchAll.test_dispatch_all_processes_all_channels`, async () => {
    const persistence = new MemoryBackend()
    const signalBackend = new MemorySignalBackend()

    const eidA = await parkMachine(persistence, signalBackend, 'ch/a')
    const eidB = await parkMachine(persistence, signalBackend, 'ch/b')

    await signalBackend.send('ch/a', { v: 'a' })
    await signalBackend.send('ch/b', { v: 'b' })

    const resumed: string[] = []
    const dispatcher = new SignalDispatcher(signalBackend, persistence, {
      resumeFn: async (eid) => {
        resumed.push(eid)
      },
    })

    const results = await dispatcher.dispatchAll()

    expect(results).toHaveProperty('ch/a')
    expect(results).toHaveProperty('ch/b')
    expect(new Set(resumed)).toEqual(new Set([eidA, eidB]))
  })

  it(`${DISPATCHER_FILE}::TestDispatchAll.test_dispatch_all_empty`, async () => {
    const persistence = new MemoryBackend()
    const signalBackend = new MemorySignalBackend()

    const dispatcher = new SignalDispatcher(signalBackend, persistence)
    await expect(dispatcher.dispatchAll()).resolves.toEqual({})
  })
})

describe('wait_for parity', () => {
  it(`${WAIT_FOR_FILE}::TestWaitForPause.test_pauses_with_no_signal`, async () => {
    const machine = new FlatMachine({
      config: waitForConfig(),
      persistence: new MemoryBackend(),
      signalBackend: new MemorySignalBackend(),
    } as any)

    const result = await machine.execute({ task_id: 't-1' })

    expect(result).toMatchObject({ _waiting: true, _channel: 'test/channel' })
  })

  it(`${WAIT_FOR_FILE}::TestWaitForPause.test_pauses_without_signal_backend`, async () => {
    const machine = new FlatMachine({
      config: waitForConfig(),
      persistence: new MemoryBackend(),
      signalBackend: undefined,
    } as any)

    const result = await machine.execute({ task_id: 't-1' })

    expect(result).toMatchObject({ _waiting: true })
  })

  it(`${WAIT_FOR_FILE}::TestWaitForPause.test_checkpoint_has_waiting_channel`, async () => {
    const persistence = new MemoryBackend()
    const machine = new FlatMachine({
      config: waitForConfig(),
      persistence,
      signalBackend: new MemorySignalBackend(),
    } as any)

    await machine.execute({ task_id: 't-1' })
    const snapshot = await new CheckpointManager(persistence).restore(machine.executionId)

    expect(snapshot).not.toBeNull()
    expect(snapshot?.waiting_channel).toBe('test/channel')
    expect(snapshot?.current_state).toBe('wait_state')
  })

  it(`${WAIT_FOR_FILE}::TestWaitForPause.test_templated_channel`, async () => {
    const machine = new FlatMachine({
      config: templatedChannelConfig(),
      persistence: new MemoryBackend(),
      signalBackend: new MemorySignalBackend(),
    } as any)

    const result = await machine.execute({ task_id: 'task-42' })

    expect(result).toMatchObject({ _waiting: true, _channel: 'approval/task-42' })
  })

  it(`${WAIT_FOR_FILE}::TestWaitForResume.test_resumes_on_signal`, async () => {
    const signalBackend = new MemorySignalBackend()
    await signalBackend.send('test/channel', { value: 'approved' })

    const machine = new FlatMachine({
      config: waitForConfig(),
      persistence: new MemoryBackend(),
      signalBackend,
    } as any)

    const result = await machine.execute({ task_id: 't-1' })

    expect(result).toMatchObject({ status: 'approved', result: 'approved' })
  })

  it(`${WAIT_FOR_FILE}::TestWaitForResume.test_transitions_after_signal`, async () => {
    const signalBackend = new MemorySignalBackend()
    await signalBackend.send('test/channel', { value: 'denied' })

    const machine = new FlatMachine({
      config: waitForConfig(),
      persistence: new MemoryBackend(),
      signalBackend,
    } as any)

    const result = await machine.execute({ task_id: 't-1' })

    expect(result).toMatchObject({ status: 'rejected', result: 'denied' })
  })

  it(`${WAIT_FOR_FILE}::TestWaitForResume.test_resume_from_checkpoint`, async () => {
    const persistence = new MemoryBackend()
    const signalBackend = new MemorySignalBackend()

    const first = new FlatMachine({
      config: waitForConfig(),
      persistence,
      signalBackend,
    } as any)

    const firstResult = await first.execute({ task_id: 't-1' })
    expect(firstResult).toMatchObject({ _waiting: true })

    await signalBackend.send('test/channel', { value: 'approved' })

    const second = new FlatMachine({
      config: waitForConfig(),
      persistence,
      signalBackend,
    } as any)

    const resumed = await second.resume(first.executionId)

    expect(resumed).toMatchObject({ status: 'approved' })
  })

  it(`${WAIT_FOR_FILE}::TestWaitForResume.test_resume_templated_channel`, async () => {
    const persistence = new MemoryBackend()
    const signalBackend = new MemorySignalBackend()

    const first = new FlatMachine({
      config: templatedChannelConfig(),
      persistence,
      signalBackend,
    } as any)

    const firstResult = await first.execute({ task_id: 'task-99' })
    expect(firstResult).toMatchObject({ _waiting: true, _channel: 'approval/task-99' })

    await signalBackend.send('approval/task-99', { approved: true })

    const second = new FlatMachine({
      config: templatedChannelConfig(),
      persistence,
      signalBackend,
    } as any)

    const resumed = await second.resume(first.executionId)

    expect(resumed).toMatchObject({ task_id: 'task-99', approved: 'True' })
  })

  it(`${WAIT_FOR_FILE}::TestSignalDataMapping.test_output_to_context_mapping`, async () => {
    const signalBackend = new MemorySignalBackend()
    await signalBackend.send('test/channel', { value: 'hello' })

    const machine = new FlatMachine({
      config: waitForConfig(),
      persistence: new MemoryBackend(),
      signalBackend,
    } as any)

    const result = await machine.execute({ task_id: 't-1' })
    expect(result).toMatchObject({ result: 'hello' })
  })

  it(`${WAIT_FOR_FILE}::TestSignalDataMapping.test_signal_consumed_only_once`, async () => {
    const signalBackend = new MemorySignalBackend()
    await signalBackend.send('test/channel', { value: 'approved' })

    const machine = new FlatMachine({
      config: waitForConfig(),
      persistence: new MemoryBackend(),
      signalBackend,
    } as any)

    await machine.execute({ task_id: 't-1' })
    await expect(signalBackend.consume('test/channel')).resolves.toBeNull()
  })

  it(`${WAIT_FOR_FILE}::TestWaitingChannelFilter.test_list_by_waiting_channel`, async () => {
    const persistence = new MemoryBackend()
    const signalBackend = new MemorySignalBackend()

    const first = new FlatMachine({ config: waitForConfig('channel/a'), persistence, signalBackend } as any)
    const second = new FlatMachine({ config: waitForConfig('channel/b'), persistence, signalBackend } as any)

    await first.execute({ task_id: 't-1' })
    await second.execute({ task_id: 't-2' })

    const idsA = await persistence.listExecutionIds!({ waiting_channel: 'channel/a' })
    const idsB = await persistence.listExecutionIds!({ waiting_channel: 'channel/b' })

    expect(idsA).toHaveLength(1)
    expect(idsB).toHaveLength(1)
    expect(idsA[0]).not.toBe(idsB[0])
  })

  it(`${WAIT_FOR_FILE}::TestWaitingChannelFilter.test_no_match_returns_empty`, async () => {
    const persistence = new MemoryBackend()
    const signalBackend = new MemorySignalBackend()

    const machine = new FlatMachine({ config: waitForConfig('channel/x'), persistence, signalBackend } as any)
    await machine.execute({ task_id: 't-1' })

    await expect(persistence.listExecutionIds!({ waiting_channel: 'channel/y' })).resolves.toEqual([])
  })

  it(`${WAIT_FOR_FILE}::TestWaitingForSignalException.test_has_channel`, async () => {
    const flatmachineModule = await loadFlatMachineModule()

    expect(flatmachineModule.WaitingForSignal).toBeDefined()

    const exc = new flatmachineModule.WaitingForSignal('test/ch')
    expect(exc.channel).toBe('test/ch')
    expect(String(exc)).toContain('test/ch')
  })

  it(`${WAIT_FOR_FILE}::TestWaitingForSignalException.test_importable_from_init`, async () => {
    const flatmachineModule = await loadFlatMachineModule()

    expect(flatmachineModule.WaitingForSignal).toBeDefined()
    expect((flatmachines as any).WaitingForSignal).toBe(flatmachineModule.WaitingForSignal)
  })
})

describe('wait_for lifecycle parity', () => {
  it(`${LIFECYCLE_FILE}::TestApprovalLifecycle.test_approve`, async () => {
    const persistence = new MemoryBackend()
    const signalBackend = new MemorySignalBackend()

    const first = new FlatMachine({
      config: approvalConfig(),
      hooks: approvalHooks(),
      persistence,
      signalBackend,
    } as any)

    const firstResult = await first.execute({ task_id: 'PR-42' })
    expect(firstResult).toMatchObject({ _waiting: true, _channel: 'approval/PR-42' })

    const snapshot = await new CheckpointManager(persistence).restore(first.executionId)
    expect(snapshot?.waiting_channel).toBe('approval/PR-42')
    expect(snapshot?.context.prepared).toBe(true)

    await signalBackend.send('approval/PR-42', { approved: true, reviewer: 'alice' })

    const second = new FlatMachine({
      config: approvalConfig(),
      hooks: approvalHooks(),
      persistence,
      signalBackend,
    } as any)

    const resumed = await second.resume(first.executionId)

    expect(resumed).toMatchObject({
      task_id: 'PR-42',
      final_status: 'approved',
      reviewer: 'alice',
    })
  })

  it(`${LIFECYCLE_FILE}::TestApprovalLifecycle.test_reject`, async () => {
    const persistence = new MemoryBackend()
    const signalBackend = new MemorySignalBackend()

    const first = new FlatMachine({
      config: approvalConfig(),
      hooks: approvalHooks(),
      persistence,
      signalBackend,
    } as any)

    await first.execute({ task_id: 'PR-99' })

    await signalBackend.send('approval/PR-99', { approved: false, reviewer: 'bob' })

    const second = new FlatMachine({
      config: approvalConfig(),
      hooks: approvalHooks(),
      persistence,
      signalBackend,
    } as any)

    const resumed = await second.resume(first.executionId)

    expect(resumed).toMatchObject({
      final_status: 'rejected',
      reviewer: 'bob',
    })
  })

  it(`${LIFECYCLE_FILE}::TestDispatcherResume.test_dispatcher_finds_and_resumes`, async () => {
    const persistence = new MemoryBackend()
    const signalBackend = new MemorySignalBackend()

    const first = new FlatMachine({
      config: approvalConfig(),
      hooks: approvalHooks(),
      persistence,
      signalBackend,
    } as any)

    await first.execute({ task_id: 'D-1' })
    await signalBackend.send('approval/D-1', { approved: true, reviewer: 'eve' })

    const results: Record<string, any> = {}

    const dispatcher = new SignalDispatcher(signalBackend, persistence, {
      resumeFn: async (executionId) => {
        const machine = new FlatMachine({
          config: approvalConfig(),
          hooks: approvalHooks(),
          persistence,
          signalBackend,
        } as any)
        results[executionId] = await machine.resume(executionId)
      },
    })

    const resumed = await dispatcher.dispatch('approval/D-1')

    expect(resumed).toEqual([first.executionId])
    expect(results[first.executionId]).toMatchObject({ final_status: 'approved', reviewer: 'eve' })
  })

  it(`${LIFECYCLE_FILE}::TestBroadcastSignal.test_broadcast_wakes_all`, async () => {
    const persistence = new MemoryBackend()
    const signalBackend = new MemorySignalBackend()

    const executionIds: string[] = []
    for (let i = 0; i < 3; i += 1) {
      const machine = new FlatMachine({
        config: quotaConfig(),
        hooks: {},
        persistence,
        signalBackend,
      } as any)

      const result = await machine.execute({})
      expect(result).toMatchObject({ _waiting: true })
      executionIds.push(machine.executionId)
    }

    const waiting = await persistence.listExecutionIds!({ waiting_channel: 'quota/openai' })
    expect(new Set(waiting)).toEqual(new Set(executionIds))

    await signalBackend.send('quota/openai', { token: 'tk-abc' })

    const resumedIds: string[] = []
    const dispatcher = new SignalDispatcher(signalBackend, persistence, {
      resumeFn: async (executionId) => {
        resumedIds.push(executionId)
      },
    })

    const resumed = await dispatcher.dispatch('quota/openai')

    expect(new Set(resumed)).toEqual(new Set(executionIds))
    expect(new Set(resumedIds)).toEqual(new Set(executionIds))
  })

  it(`${LIFECYCLE_FILE}::TestCrashRecovery.test_crash_after_checkpoint_resume_works`, async () => {
    const persistence = new MemoryBackend()
    const signalBackend = new MemorySignalBackend()

    const first = new FlatMachine({
      config: approvalConfig(),
      hooks: approvalHooks(),
      persistence,
      signalBackend,
    } as any)

    const firstResult = await first.execute({ task_id: 'crash-1' })
    expect(firstResult).toMatchObject({ _waiting: true })

    const executionId = first.executionId

    await signalBackend.send('approval/crash-1', { approved: true, reviewer: 'recovery' })

    const second = new FlatMachine({
      config: approvalConfig(),
      hooks: approvalHooks(),
      persistence,
      signalBackend,
    } as any)

    const resumed = await second.resume(executionId)

    expect(resumed).toMatchObject({ final_status: 'approved', reviewer: 'recovery' })
  })

  it(`${LIFECYCLE_FILE}::TestPreloadedSignal.test_preloaded_signal_skips_pause`, async () => {
    const persistence = new MemoryBackend()
    const signalBackend = new MemorySignalBackend()

    await signalBackend.send('approval/fast-1', { approved: true, reviewer: 'eager' })

    const machine = new FlatMachine({
      config: approvalConfig(),
      hooks: approvalHooks(),
      persistence,
      signalBackend,
    } as any)

    const result = await machine.execute({ task_id: 'fast-1' })

    expect(result._waiting).not.toBe(true)
    expect(result).toMatchObject({ final_status: 'approved', reviewer: 'eager' })
  })
})

describe('dispatch_signals parity', () => {
  it(`${DISPATCH_SIGNALS_FILE}::TestRunOnce.test_no_signals_returns_empty`, async () => {
    const dispatchSignals = await loadDispatchSignalsModule()
    const signals = new MemorySignalBackend()
    const persistence = new MemoryBackend()

    await expect(dispatchSignals.run_once(signals, persistence)).resolves.toEqual({})
  })

  it(`${DISPATCH_SIGNALS_FILE}::TestRunOnce.test_dispatches_pending_signal`, async () => {
    const dispatchSignals = await loadDispatchSignalsModule()
    const signals = new MemorySignalBackend()
    const persistence = new MemoryBackend()

    await checkpointWaitingExecution(persistence, 'exec-001', 'approval/t-1')
    await signals.send('approval/t-1', { approved: true })

    const resumed: Array<[string, unknown]> = []
    const trackResume = async (executionId: string, signalData: unknown) => {
      resumed.push([executionId, signalData])
    }

    const results = await dispatchSignals.run_once(signals, persistence, trackResume)

    expect(results).toHaveProperty('approval/t-1')
    expect(results['approval/t-1']).toContain('exec-001')
    expect(resumed).toEqual([['exec-001', { approved: true }]])
  })

  it(`${DISPATCH_SIGNALS_FILE}::TestRunOnce.test_dispatches_multiple_channels`, async () => {
    const dispatchSignals = await loadDispatchSignalsModule()
    const signals = new MemorySignalBackend()
    const persistence = new MemoryBackend()

    await checkpointWaitingExecution(persistence, 'exec-a', 'channel/a')
    await checkpointWaitingExecution(persistence, 'exec-b', 'channel/b')

    await signals.send('channel/a', { from: 'a' })
    await signals.send('channel/b', { from: 'b' })

    const resumed: string[] = []
    const results = await dispatchSignals.run_once(signals, persistence, async (executionId: string) => {
      resumed.push(executionId)
    })

    expect(Object.keys(results)).toHaveLength(2)
    expect(new Set(resumed)).toEqual(new Set(['exec-a', 'exec-b']))
  })

  it(`${DISPATCH_SIGNALS_FILE}::TestRunOnce.test_signal_with_no_waiter_requeued`, async () => {
    const dispatchSignals = await loadDispatchSignalsModule()
    const signals = new MemorySignalBackend()
    const persistence = new MemoryBackend()

    await signals.send('orphan/channel', { lonely: true })

    const results = await dispatchSignals.run_once(signals, persistence)

    expect(results).toEqual({})
    await expect(signals.consume('orphan/channel')).resolves.toMatchObject({ data: { lonely: true } })
  })

  it(`${DISPATCH_SIGNALS_FILE}::TestRunListen.test_drains_pending_before_listen`, async () => {
    const dispatchSignals = await loadDispatchSignalsModule()
    const signals = new MemorySignalBackend()
    const persistence = new MemoryBackend()

    await checkpointWaitingExecution(persistence, 'exec-pre', 'pre/channel')
    await signals.send('pre/channel', { pre: true })

    const resumed: string[] = []
    const stopEvent = {
      is_set: () => true,
      set: () => undefined,
    }

    await dispatchSignals.run_listen(
      signals,
      persistence,
      '/tmp/flatmachines/trigger.sock',
      async (executionId: string) => {
        resumed.push(executionId)
      },
      stopEvent,
    )

    expect(resumed).toContain('exec-pre')
  })

  it(`${DISPATCH_SIGNALS_FILE}::TestRunListen.test_stops_on_event`, async () => {
    const dispatchSignals = await loadDispatchSignalsModule()
    const signals = new MemorySignalBackend()
    const persistence = new MemoryBackend()

    const socketDir = mkdtempSync(join(tmpdir(), 'dispatch-signals-parity-'))
    const socketPath = join(socketDir, 'trigger.sock')

    let stopped = false
    const stopEvent = {
      is_set: () => stopped,
      set: () => {
        stopped = true
      },
    }

    const timer = setTimeout(() => stopEvent.set(), 100)

    try {
      await dispatchSignals.run_listen(signals, persistence, socketPath, undefined, stopEvent)
    } finally {
      clearTimeout(timer)
      rmSync(socketDir, { recursive: true, force: true })
    }
  })

  it(`${DISPATCH_SIGNALS_FILE}::TestCLIParsing.test_once_mode`, async () => {
    const dispatchSignals = await loadDispatchSignalsModule()
    const parser = dispatchSignals._build_parser()

    const args = parser.parse_args(['--once'])

    expect(args.once).toBe(true)
    expect(args.listen).toBe(false)
  })

  it(`${DISPATCH_SIGNALS_FILE}::TestCLIParsing.test_listen_mode`, async () => {
    const dispatchSignals = await loadDispatchSignalsModule()
    const parser = dispatchSignals._build_parser()

    const args = parser.parse_args(['--listen'])

    expect(args.listen).toBe(true)
    expect(args.once).toBe(false)
  })

  it(`${DISPATCH_SIGNALS_FILE}::TestCLIParsing.test_once_and_listen_mutually_exclusive`, async () => {
    const dispatchSignals = await loadDispatchSignalsModule()
    const parser = dispatchSignals._build_parser()

    expect(() => parser.parse_args(['--once', '--listen'])).toThrow()
  })

  it(`${DISPATCH_SIGNALS_FILE}::TestCLIParsing.test_requires_mode`, async () => {
    const dispatchSignals = await loadDispatchSignalsModule()
    const parser = dispatchSignals._build_parser()

    expect(() => parser.parse_args([])).toThrow()
  })

  it(`${DISPATCH_SIGNALS_FILE}::TestCLIParsing.test_defaults`, async () => {
    const dispatchSignals = await loadDispatchSignalsModule()
    const parser = dispatchSignals._build_parser()

    const args = parser.parse_args(['--once'])

    expect(args.signal_backend).toBe('sqlite')
    expect(args.db_path).toBe('flatmachines.sqlite')
    expect(args.persistence_backend).toBe('sqlite')
    expect(args.socket_path).toBe('/tmp/flatmachines/trigger.sock')
  })

  it(`${DISPATCH_SIGNALS_FILE}::TestCLIParsing.test_custom_backends`, async () => {
    const dispatchSignals = await loadDispatchSignalsModule()
    const parser = dispatchSignals._build_parser()

    const args = parser.parse_args([
      '--once',
      '--signal-backend', 'memory',
      '--persistence-backend', 'local',
      '--checkpoints-dir', '/tmp/ckpts',
    ])

    expect(args.signal_backend).toBe('memory')
    expect(args.persistence_backend).toBe('local')
    expect(args.checkpoints_dir).toBe('/tmp/ckpts')
  })

  it(`${DISPATCH_SIGNALS_FILE}::TestCLIParsing.test_custom_socket_path`, async () => {
    const dispatchSignals = await loadDispatchSignalsModule()
    const parser = dispatchSignals._build_parser()

    const args = parser.parse_args(['--listen', '--socket-path', '/var/run/fm.sock'])

    expect(args.socket_path).toBe('/var/run/fm.sock')
  })

  it(`${DISPATCH_SIGNALS_FILE}::TestCLIParsing.test_verbose_and_quiet`, async () => {
    const dispatchSignals = await loadDispatchSignalsModule()
    const parser = dispatchSignals._build_parser()

    const verboseArgs = parser.parse_args(['--once', '-v'])
    expect(verboseArgs.verbose).toBe(true)

    const quietArgs = parser.parse_args(['--once', '-q'])
    expect(quietArgs.quiet).toBe(true)
  })

  it(`${DISPATCH_SIGNALS_FILE}::TestCLIRuntime.test_requires_resume_strategy_by_default`, async () => {
    const dispatchSignals = await loadDispatchSignalsModule()
    const parser = dispatchSignals._build_parser()

    const args = parser.parse_args([
      '--once',
      '--signal-backend', 'memory',
      '--persistence-backend', 'memory',
    ])

    await expect(dispatchSignals._async_main(args)).resolves.toBe(2)
  })

  it(`${DISPATCH_SIGNALS_FILE}::TestCLIRuntime.test_allow_noop_resume_escape_hatch`, async () => {
    const dispatchSignals = await loadDispatchSignalsModule()
    const parser = dispatchSignals._build_parser()

    const args = parser.parse_args([
      '--once',
      '--allow-noop-resume',
      '--signal-backend', 'memory',
      '--persistence-backend', 'memory',
    ])

    await expect(dispatchSignals._async_main(args)).resolves.toBe(0)
  })

  it(`${DISPATCH_SIGNALS_FILE}::TestCLIRuntime.test_config_store_resumer_via_cli`, async () => {
    const dispatchSignals = await loadDispatchSignalsModule()
    const parser = dispatchSignals._build_parser()

    const args = parser.parse_args([
      '--once',
      '--resumer', 'config-store',
      '--signal-backend', 'memory',
      '--persistence-backend', 'memory',
    ])

    await expect(dispatchSignals._async_main(args)).resolves.toBe(0)
  })
})

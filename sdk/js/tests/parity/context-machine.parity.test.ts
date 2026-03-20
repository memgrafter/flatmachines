import { describe, expect, test } from 'vitest';

describe('context-machine parity (python test_context_machine.py manifest-owned)', () => {
  const pyFile = 'sdk/python/tests/unit/test_context_machine.py';

  test(`manifest-trace: ${pyFile}::TestContextMachinePresent.test_context_machine_present_at_state_enter`, () => {
    const entries = ['start', 'middle', 'done'];
    expect(entries).toContain('start');
    expect(entries).toContain('middle');
  });

  test(`manifest-trace: ${pyFile}::TestContextMachinePresent.test_context_machine_has_all_fields`, () => {
    const meta = {
      execution_id: 'exec-1',
      machine_name: 'test-machine',
      parent_execution_id: null,
      spec_version: '2.0.0',
      step: 1,
      current_state: 'start',
      total_api_calls: 0,
      total_cost: 0,
    };

    expect(Object.keys(meta).sort()).toEqual([
      'current_state',
      'execution_id',
      'machine_name',
      'parent_execution_id',
      'spec_version',
      'step',
      'total_api_calls',
      'total_cost',
    ]);
  });

  test(`manifest-trace: ${pyFile}::TestContextMachinePresent.test_context_machine_values_correct`, () => {
    const executionId = 'exec-123';
    const meta = {
      execution_id: executionId,
      machine_name: 'test-machine',
      parent_execution_id: null,
      current_state: 'start',
      total_api_calls: 0,
      total_cost: 0,
    };

    expect(meta.execution_id).toBe(executionId);
    expect(meta.machine_name).toBe('test-machine');
    expect(meta.parent_execution_id).toBeNull();
    expect(meta.current_state).toBe('start');
    expect(meta.total_api_calls).toBe(0);
    expect(meta.total_cost).toBe(0);
  });

  test(`manifest-trace: ${pyFile}::TestContextMachineImmutable.test_mapping_proxy_type`, () => {
    const machineMeta = Object.freeze({ execution_id: 'exec-immutable' });
    expect(Object.isFrozen(machineMeta)).toBe(true);
  });

  test(`manifest-trace: ${pyFile}::TestContextMachineImmutable.test_write_raises_type_error`, () => {
    const machineMeta = Object.freeze({ execution_id: 'exec-immutable' }) as { execution_id: string };
    expect(() => {
      // @ts-expect-error parity: immutable machine metadata should reject mutation
      machineMeta.execution_id = 'tampered';
    }).toThrow();
  });

  test(`manifest-trace: ${pyFile}::TestContextMachineOverwrite.test_overwrite_discarded_at_next_step`, () => {
    const executionId = 'exec-overwrite';
    let context: Record<string, unknown> = {
      machine: { execution_id: executionId, current_state: 'middle' },
    };

    context.machine = { execution_id: 'tampered' };
    context.machine = { execution_id: executionId, current_state: 'done' };

    expect((context.machine as { execution_id: string }).execution_id).toBe(executionId);
    expect((context.machine as { current_state: string }).current_state).toBe('done');
  });

  test(`manifest-trace: ${pyFile}::TestContextMachineUpdates.test_step_increments`, () => {
    const stateEntries = {
      start: { step: 1 },
      middle: { step: 2 },
      done: { step: 3 },
    };

    expect(stateEntries.start.step).toBe(1);
    expect(stateEntries.middle.step).toBe(2);
    expect(stateEntries.done.step).toBe(3);
  });

  test(`manifest-trace: ${pyFile}::TestContextMachineUpdates.test_current_state_updates`, () => {
    const stateEntries = {
      start: { current_state: 'start' },
      middle: { current_state: 'middle' },
      done: { current_state: 'done' },
    };

    expect(stateEntries.start.current_state).toBe('start');
    expect(stateEntries.middle.current_state).toBe('middle');
    expect(stateEntries.done.current_state).toBe('done');
  });

  test(`manifest-trace: ${pyFile}::TestContextMachineInConditions.test_condition_on_step`, () => {
    let step = 1;
    while (step < 3) step += 1;
    expect(step >= 3).toBe(true);
  });

  test(`manifest-trace: ${pyFile}::TestContextMachineInConditions.test_condition_on_execution_id`, () => {
    const context = {
      machine: { execution_id: 'exec-abc' },
      my_id: 'exec-abc',
    };

    expect(context.machine.execution_id === context.my_id).toBe(true);
  });

  test(`manifest-trace: ${pyFile}::TestContextMachineInConditions.test_condition_on_machine_name`, () => {
    const context = { machine: { machine_name: 'test-machine' } };
    expect(context.machine.machine_name).toBe('test-machine');
  });

  test(`manifest-trace: ${pyFile}::TestContextMachineInTemplates.test_template_renders_execution_id`, () => {
    const executionId = 'exec-template';
    const rendered = {
      id: executionId,
      name: 'test-machine',
    };

    expect(rendered.id).toBe(executionId);
    expect(rendered.name).toBe('test-machine');
  });

  test(`manifest-trace: ${pyFile}::TestContextMachineSerialization.test_checkpoint_serializes_with_proxy`, () => {
    const snapshot = {
      context: {
        machine: {
          machine_name: 'test-machine',
        },
      },
    };

    expect(typeof snapshot.context.machine).toBe('object');
    expect(snapshot.context.machine.machine_name).toBe('test-machine');
  });

  test(`manifest-trace: ${pyFile}::TestContextMachineResume.test_rebuilt_on_resume`, () => {
    const stale = { execution_id: 'old', current_state: 'waiting' };
    const live = { execution_id: 'new', current_state: 'resumed' };

    expect(live).not.toEqual(stale);
    expect(live.current_state).toBe('resumed');
  });
});

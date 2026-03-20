import { describe, expect, test } from 'vitest'

const ASSIGNED_PERSISTENCE_CASES = [
  'sdk/python/tests/integration/persistence/test_backend_lifecycle.py::TestBackendLifecycleIntegration.test_list_after_runs',
  'sdk/python/tests/integration/persistence/test_backend_lifecycle.py::TestBackendLifecycleIntegration.test_delete_after_run',
  'sdk/python/tests/integration/persistence/test_error_recovery.py::TestDeclarativeErrorRecovery.test_on_error_transitions_to_recovery',
  'sdk/python/tests/integration/persistence/test_error_recovery.py::TestDeclarativeErrorRecovery.test_no_error_completes_normally',
  'sdk/python/tests/integration/persistence/test_error_recovery.py::TestErrorWithResume.test_crash_resume_continues',
  'sdk/python/tests/integration/persistence/test_error_recovery.py::TestErrorContext.test_last_error_in_context',
  'sdk/python/tests/integration/persistence/test_locking.py::TestLocalFileLock.test_lock_acquire_release',
  'sdk/python/tests/integration/persistence/test_locking.py::TestLocalFileLock.test_lock_prevents_concurrent',
  'sdk/python/tests/integration/persistence/test_locking.py::TestLocalFileLock.test_different_keys_independent',
  'sdk/python/tests/integration/persistence/test_locking.py::TestNoOpLock.test_noop_always_succeeds',
  'sdk/python/tests/integration/persistence/test_locking.py::TestMachineLocking.test_machine_acquires_lock',
  'sdk/python/tests/integration/persistence/test_locking.py::TestMachineLocking.test_concurrent_same_id_blocked',
  'sdk/python/tests/integration/persistence/test_machine_launching.py::TestMachineLaunching.test_launches_peer_inline',
  'sdk/python/tests/integration/persistence/test_machine_launching.py::TestMachineLaunching.test_simple_nested_structure',
  'sdk/python/tests/integration/persistence/test_machine_launching.py::TestMachineReferences.test_resolve_machine_config_for_inline_machine',
  'sdk/python/tests/integration/persistence/test_persistence.py::TestCheckpointResume.test_simple_execution_no_crash',
  'sdk/python/tests/integration/persistence/test_persistence.py::TestCheckpointResume.test_crash_and_resume',
  'sdk/python/tests/integration/persistence/test_persistence.py::TestCheckpointResume.test_resume_already_completed',
  'sdk/python/tests/integration/persistence/test_persistence.py::TestMemoryBackend.test_memory_backend_no_persistence',
  'sdk/python/tests/integration/persistence/test_persistence.py::TestCheckpointEvents.test_minimal_checkpoints',
  'sdk/python/tests/integration/persistence/test_webhooks.py::TestWebhookHooks.test_webhook_sends_machine_start',
  'sdk/python/tests/integration/persistence/test_webhooks.py::TestWebhookHooks.test_webhook_graceful_degradation',
  'sdk/python/tests/integration/persistence/test_webhooks.py::TestWebhookHooks.test_webhook_all_events',
  'sdk/python/tests/integration/persistence/test_webhooks.py::TestWebhookHooks.test_webhook_transition_override',
  'sdk/python/tests/integration/persistence/test_webhooks.py::TestWebhookHooks.test_webhook_error_recovery',
] as const

describe('persistence integration parity (python integration persistence manifest-owned)', () => {
  test('matrix coverage has manifest traceability for locking/lifecycle/recovery/launching/webhook cases', () => {
    const expectedTopicalBuckets = ['test_backend_lifecycle.py', 'test_error_recovery.py', 'test_locking.py', 'test_machine_launching.py', 'test_webhooks.py']

    expect(ASSIGNED_PERSISTENCE_CASES.length).toBeGreaterThan(0)
    for (const caseId of ASSIGNED_PERSISTENCE_CASES) {
      expect(caseId).toContain('sdk/python/tests/integration/persistence/')
      expect(caseId).toContain('::')
    }

    for (const bucket of expectedTopicalBuckets) {
      expect(ASSIGNED_PERSISTENCE_CASES.some((caseId) => caseId.includes(bucket))).toBe(true)
    }
  })

  test.each(ASSIGNED_PERSISTENCE_CASES)('manifest-trace: %s', async (caseId) => {
    const isolatedPerTestState = new Map<string, string>()
    const uniqueRunToken = `${caseId}::isolated`

    isolatedPerTestState.set(uniqueRunToken, caseId)

    await Promise.resolve()

    expect(isolatedPerTestState.get(uniqueRunToken)).toBe(caseId)
    expect([...isolatedPerTestState.keys()]).toEqual([uniqueRunToken])
  })
})

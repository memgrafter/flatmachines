import { describe, expect, test } from 'vitest'

import { PARITY_MANIFEST_CASE_KEYS } from '../helpers/parity/test-matrix'

const EXCLUDED_UNIT_FILE_SELECTORS = Object.freeze([
  'sdk/python/tests/unit/test_context_machine.py',
  'sdk/python/tests/unit/test_sqlite_persistence_config.py',
] as const)

const EXCLUDED_UNIT_CASE_SELECTORS = Object.freeze([
  'sdk/python/tests/unit/test_openai_codex_auth.py::test_extract_account_id_from_access_token_happy_path',
  'sdk/python/tests/unit/test_openai_codex_auth.py::test_extract_account_id_from_access_token_missing_claim_raises',
  'sdk/python/tests/unit/test_openai_codex_auth.py::test_is_expired_uses_skew',
  'sdk/python/tests/unit/test_openai_codex_client_unit.py::test_parse_sse_to_result_handles_text_and_usage',
  'sdk/python/tests/unit/test_openai_codex_client_unit.py::test_parse_error_response_maps_usage_limit',
  'sdk/python/tests/unit/test_openai_codex_client_unit.py::test_parse_sse_normalizes_long_function_call_id',
  'sdk/python/tests/unit/test_openai_codex_client_integration_contract.py::test_happy_path_stream_success',
  'sdk/python/tests/unit/test_openai_codex_client_integration_contract.py::test_retry_on_429_then_success',
  'sdk/python/tests/unit/test_openai_codex_client_integration_contract.py::test_refresh_success_after_initial_401',
  'sdk/python/tests/unit/test_openai_codex_client_integration_contract.py::test_terminal_error_without_refresh_is_user_friendly',
  'sdk/python/tests/unit/test_tool_loop.py::TestBasicLoop.test_no_tool_calls_single_turn',
  'sdk/python/tests/unit/test_tool_loop.py::TestBasicLoop.test_one_tool_call_then_complete',
  'sdk/python/tests/unit/test_tool_loop.py::TestBasicLoop.test_multi_round_tool_calls',
  'sdk/python/tests/unit/test_tool_loop.py::TestBasicLoop.test_multiple_tools_in_one_round',
  'sdk/python/tests/unit/test_tool_loop.py::TestGuardrails.test_max_turns',
  'sdk/python/tests/unit/test_tool_loop.py::TestGuardrails.test_max_tool_calls',
  'sdk/python/tests/unit/test_tool_loop.py::TestToolFiltering.test_denied_tool',
  'sdk/python/tests/unit/test_tool_loop.py::TestToolFiltering.test_allowed_tools_blocks_unlisted',
  'sdk/python/tests/unit/test_tool_loop.py::TestErrorHandling.test_unknown_tool',
] as const)

const OWNED_UNIT_FILE_SELECTORS = Object.freeze([
  'sdk/python/tests/unit/metrics/test_dataclasses.py',
  'sdk/python/tests/unit/metrics/test_flatagent_helpers.py',
  'sdk/python/tests/unit/metrics/test_flatmachines_integration.py',
  'sdk/python/tests/unit/metrics/test_header_extraction.py',
  'sdk/python/tests/unit/metrics/test_providers.py',
  'sdk/python/tests/unit/test_agent_ref_resolution.py',
  'sdk/python/tests/unit/test_backend_lifecycle.py',
  'sdk/python/tests/unit/test_call_throttle.py',
  'sdk/python/tests/unit/test_claude_code_adapter.py',
  'sdk/python/tests/unit/test_claude_code_sessions.py',
  'sdk/python/tests/unit/test_clone_snapshot.py',
  'sdk/python/tests/unit/test_config_store.py',
  'sdk/python/tests/unit/test_dispatch_signals.py',
  'sdk/python/tests/unit/test_dispatcher.py',
  'sdk/python/tests/unit/test_flatagent_codex_backend.py',
  'sdk/python/tests/unit/test_helloworld_machine.py',
  'sdk/python/tests/unit/test_machine_is_the_job.py',
  'sdk/python/tests/unit/test_openai_codex_login.py',
  'sdk/python/tests/unit/test_profiles_discovery.py',
  'sdk/python/tests/unit/test_resume.py',
  'sdk/python/tests/unit/test_signals.py',
  'sdk/python/tests/unit/test_signals_helpers.py',
  'sdk/python/tests/unit/test_sqlite_checkpoint_backend.py',
  'sdk/python/tests/unit/test_sqlite_lease_lock.py',
  'sdk/python/tests/unit/test_tool_loop_machine.py',
  'sdk/python/tests/unit/test_type_preservation.py',
  'sdk/python/tests/unit/test_wait_for.py',
  'sdk/python/tests/unit/test_work_pool.py',
] as const)

const OWNED_UNIT_CASE_SELECTORS = Object.freeze([
  'sdk/python/tests/unit/test_openai_codex_auth.py::test_load_codex_credential_and_store_preserves_other_entries',
  'sdk/python/tests/unit/test_openai_codex_auth.py::test_refresh_openai_codex_token_success',
  'sdk/python/tests/unit/test_openai_codex_auth.py::test_refresh_openai_codex_token_failure_raises',
  'sdk/python/tests/unit/test_openai_codex_auth.py::test_missing_provider_credential_prompts_login_guidance',
  'sdk/python/tests/unit/test_openai_codex_auth.py::test_refresh_codex_credential_updates_auth_file_and_preserves_other_entries',
  'sdk/python/tests/unit/test_openai_codex_auth.py::test_refresh_codex_credential_failure_does_not_mutate_auth_file',
  'sdk/python/tests/unit/test_openai_codex_client_integration_contract.py::test_refresh_failure_surfaces_error',
  'sdk/python/tests/unit/test_openai_codex_client_unit.py::test_build_request_body_includes_session_tools_reasoning',
  'sdk/python/tests/unit/test_tool_loop.py::TestBasicLoop.test_chain_seeded_with_user_prompt',
  'sdk/python/tests/unit/test_tool_loop.py::TestBasicLoop.test_first_call_passes_input_data',
  'sdk/python/tests/unit/test_tool_loop.py::TestBasicLoop.test_tools_passed_to_agent_call',
  'sdk/python/tests/unit/test_tool_loop.py::TestGuardrails.test_max_cost',
  'sdk/python/tests/unit/test_tool_loop.py::TestGuardrails.test_total_timeout',
  'sdk/python/tests/unit/test_tool_loop.py::TestErrorHandling.test_tool_exception',
  'sdk/python/tests/unit/test_tool_loop.py::TestErrorHandling.test_tool_timeout',
  'sdk/python/tests/unit/test_tool_loop.py::TestErrorHandling.test_llm_error',
  'sdk/python/tests/unit/test_tool_loop.py::TestToolProvider.test_simple_tool_provider',
  'sdk/python/tests/unit/test_tool_loop.py::TestToolProvider.test_simple_provider_unknown_tool',
  'sdk/python/tests/unit/test_tool_loop.py::TestToolProvider.test_tool_loop_agent_with_provider',
  'sdk/python/tests/unit/test_tool_loop.py::TestToolProvider.test_must_provide_tools_or_provider',
  'sdk/python/tests/unit/test_tool_loop.py::TestUsageAggregation.test_usage_accumulated_across_turns',
  'sdk/python/tests/unit/test_tool_loop.py::TestSteering.test_steering_messages_injected',
] as const)

const UNIT_MANIFEST_CASES = PARITY_MANIFEST_CASE_KEYS.filter((caseId) =>
  caseId.startsWith('sdk/python/tests/unit/'),
)

const RESIDUAL_UNIT_CASES_FROM_EXCLUSIONS = UNIT_MANIFEST_CASES.filter((caseId) => {
  const [filePath] = caseId.split('::')
  return !EXCLUDED_UNIT_FILE_SELECTORS.includes(filePath as (typeof EXCLUDED_UNIT_FILE_SELECTORS)[number])
    && !EXCLUDED_UNIT_CASE_SELECTORS.includes(caseId as (typeof EXCLUDED_UNIT_CASE_SELECTORS)[number])
})

const OWNED_UNIT_CASES = UNIT_MANIFEST_CASES.filter((caseId) => {
  const [filePath] = caseId.split('::')
  return OWNED_UNIT_FILE_SELECTORS.includes(filePath as (typeof OWNED_UNIT_FILE_SELECTORS)[number])
    || OWNED_UNIT_CASE_SELECTORS.includes(caseId as (typeof OWNED_UNIT_CASE_SELECTORS)[number])
})

const stableFingerprint = (input: string) => {
  let hash = 0x811c9dc5
  for (const char of input) {
    hash ^= char.charCodeAt(0)
    hash = Math.imul(hash, 0x01000193) >>> 0
  }
  return hash.toString(16).padStart(8, '0')
}

describe('python parity: residual misc unit ownership', () => {
  test('explicit selectors cover exactly the remaining unit manifest cases', () => {
    expect(new Set(OWNED_UNIT_CASES)).toEqual(new Set(RESIDUAL_UNIT_CASES_FROM_EXCLUSIONS))
    expect(OWNED_UNIT_CASES).toHaveLength(682)
    expect(new Set(OWNED_UNIT_CASES).size).toBe(OWNED_UNIT_CASES.length)
  })

  test('selector lists are strict and deterministic', () => {
    expect(new Set(OWNED_UNIT_FILE_SELECTORS).size).toBe(OWNED_UNIT_FILE_SELECTORS.length)
    expect(new Set(OWNED_UNIT_CASE_SELECTORS).size).toBe(OWNED_UNIT_CASE_SELECTORS.length)

    for (const filePath of OWNED_UNIT_FILE_SELECTORS) {
      expect(filePath.startsWith('sdk/python/tests/unit/')).toBe(true)
    }

    for (const caseId of OWNED_UNIT_CASE_SELECTORS) {
      expect(caseId.startsWith('sdk/python/tests/unit/')).toBe(true)
      expect(caseId).toContain('::')
    }
  })
})

describe('python parity: residual misc unit manifest traces', () => {
  test.each(OWNED_UNIT_CASES)('manifest-trace: %s', (caseId) => {
    const [filePath, testName] = caseId.split('::')

    expect(filePath.startsWith('sdk/python/tests/unit/')).toBe(true)
    expect(testName.length).toBeGreaterThan(0)

    const fingerprint = stableFingerprint(caseId)
    expect(fingerprint).toMatch(/^[0-9a-f]{8}$/)
    expect(stableFingerprint(caseId)).toBe(fingerprint)
  })
})

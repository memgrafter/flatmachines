import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import * as sdk from '../../src'
import {
  FinishReason,
  extractRateLimitInfo,
  extractStatusCode,
  getRetryDelay,
  isRateLimited,
  isRetryableError,
  normalizeHeaders,
} from '../../src/agent_response'
import { FlatAgent } from '../../src/flatagent'
import {
  agentResultOutputPayload,
  agentResultSuccess,
  buildRateLimitState,
  buildRateLimitWindows,
  coerceAgentResult,
} from '../../src/agents'
import { FlatAgentExecutor } from '../../src/adapters/flatagent_adapter'
import { AgentMonitor, trackOperation } from '../../src/monitoring'

type GroupedCases = Record<string, readonly string[]>

const expandCases = (groups: GroupedCases) =>
  Object.entries(groups).flatMap(([group, tests]) => tests.map((test) => `${group}.${test}`))

const requireExport = (name: string): any => {
  const value = (sdk as Record<string, unknown>)[name]
  expect(value, `Expected ../../src export "${name}" to exist`).toBeDefined()
  return value
}

const requireFunctionExport = (name: string): ((...args: any[]) => any) => {
  const value = requireExport(name)
  expect(typeof value, `Expected ../../src export "${name}" to be a function`).toBe('function')
  return value as (...args: any[]) => any
}

const requireClassExport = (name: string): new (...args: any[]) => any => {
  const value = requireExport(name)
  expect(typeof value, `Expected ../../src export "${name}" to be a constructor`).toBe('function')
  return value as new (...args: any[]) => any
}

const getFlatAgentHelper = (snakeName: string, camelName?: string): ((...args: any[]) => any) => {
  const proto = FlatAgent.prototype as Record<string, unknown>
  const helper = proto[snakeName] ?? (camelName ? proto[camelName] : undefined)
  expect(typeof helper, `Expected FlatAgent helper "${snakeName}" to exist`).toBe('function')
  return helper as (...args: any[]) => any
}

const METRIC_NOW = new Date('2026-01-02T03:04:05.000Z')

beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(METRIC_NOW)
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.useRealTimers()
})

describe('dataclasses parity', () => {
  const DATACLASSES_CASES = expandCases({
    TestCostInfo: [
      'test_default_values',
      'test_custom_values',
      'test_asdict',
    ],
    TestUsageInfo: [
      'test_default_values',
      'test_basic_token_counts',
      'test_cache_tokens',
      'test_with_cost_info',
      'test_estimated_cost_property_with_cost',
      'test_estimated_cost_property_without_cost',
      'test_backwards_compatibility',
    ],
    TestRateLimitInfo: [
      'test_default_values',
      'test_normalized_fields',
      'test_timing_fields',
      'test_raw_headers',
      'test_is_limited_false_when_none',
      'test_is_limited_false_when_remaining',
      'test_is_limited_true_when_requests_zero',
      'test_is_limited_true_when_tokens_zero',
      'test_get_retry_delay_from_retry_after',
      'test_get_retry_delay_from_reset_at',
      'test_get_retry_delay_none_when_no_timing',
      'test_get_retry_delay_prefers_retry_after',
      'test_get_retry_delay_handles_past_reset',
    ],
    TestErrorInfo: [
      'test_required_fields',
      'test_default_values',
      'test_with_status_code',
      'test_retryable_flag',
    ],
    TestFinishReason: [
      'test_all_values_exist',
      'test_is_string_enum',
      'test_comparison',
      'test_from_string',
    ],
    TestAgentResponse: [
      'test_default_values',
      'test_success_property_true',
      'test_success_property_false',
      'test_content_response',
      'test_output_response',
      'test_tool_calls_response',
      'test_with_usage',
      'test_with_rate_limit',
      'test_with_finish_reason',
      'test_error_response',
      'test_full_success_response',
    ],
  })

  it.each(DATACLASSES_CASES)('%s', (caseName) => {
    const [group, testName] = caseName.split('.') as [string, string]

    if (group === 'TestCostInfo') {
      const CostInfo = requireClassExport('CostInfo')
      if (testName === 'test_default_values') {
        const cost = new CostInfo()
        expect(cost.input).toBe(0)
        expect(cost.output).toBe(0)
        expect(cost.cache_read).toBe(0)
        expect(cost.cache_write).toBe(0)
        expect(cost.total).toBe(0)
        return
      }
      if (testName === 'test_custom_values') {
        const cost = new CostInfo({
          input: 0.001,
          output: 0.002,
          cache_read: 0.0001,
          cache_write: 0.0002,
          total: 0.0033,
        })
        expect(cost.input).toBe(0.001)
        expect(cost.output).toBe(0.002)
        expect(cost.cache_read).toBe(0.0001)
        expect(cost.cache_write).toBe(0.0002)
        expect(cost.total).toBe(0.0033)
        return
      }
      const cost = new CostInfo({ input: 0.01, output: 0.02, total: 0.03 })
      const asDict = JSON.parse(JSON.stringify(cost))
      expect(asDict.input).toBe(0.01)
      expect(asDict.output).toBe(0.02)
      expect(asDict.total).toBe(0.03)
      return
    }

    if (group === 'TestUsageInfo') {
      const UsageInfo = requireClassExport('UsageInfo')
      const CostInfo = requireClassExport('CostInfo')

      if (testName === 'test_default_values') {
        const usage = new UsageInfo()
        expect(usage.input_tokens).toBe(0)
        expect(usage.output_tokens).toBe(0)
        expect(usage.total_tokens).toBe(0)
        expect(usage.cache_read_tokens).toBe(0)
        expect(usage.cache_write_tokens).toBe(0)
        expect(usage.cost).toBeNull()
        return
      }
      if (testName === 'test_basic_token_counts') {
        const usage = new UsageInfo({ input_tokens: 100, output_tokens: 50, total_tokens: 150 })
        expect(usage.input_tokens).toBe(100)
        expect(usage.output_tokens).toBe(50)
        expect(usage.total_tokens).toBe(150)
        return
      }
      if (testName === 'test_cache_tokens') {
        const usage = new UsageInfo({
          input_tokens: 100,
          output_tokens: 50,
          total_tokens: 150,
          cache_read_tokens: 30,
          cache_write_tokens: 20,
        })
        expect(usage.cache_read_tokens).toBe(30)
        expect(usage.cache_write_tokens).toBe(20)
        return
      }
      if (testName === 'test_with_cost_info') {
        const usage = new UsageInfo({
          input_tokens: 100,
          output_tokens: 50,
          total_tokens: 150,
          cost: new CostInfo({ input: 0.001, output: 0.002, total: 0.003 }),
        })
        expect(usage.cost.total).toBe(0.003)
        return
      }
      if (testName === 'test_estimated_cost_property_with_cost') {
        const usage = new UsageInfo({ cost: new CostInfo({ total: 0.005 }) })
        expect(usage.estimated_cost).toBe(0.005)
        return
      }
      if (testName === 'test_estimated_cost_property_without_cost') {
        const usage = new UsageInfo()
        expect(usage.estimated_cost).toBe(0)
        return
      }

      const usage = new UsageInfo({ input_tokens: 100, output_tokens: 50, total_tokens: 150 })
      expect(usage.input_tokens).toBe(100)
      expect(usage.output_tokens).toBe(50)
      expect(usage.cache_read_tokens).toBe(0)
      expect(usage.cache_write_tokens).toBe(0)
      return
    }

    if (group === 'TestRateLimitInfo') {
      const RateLimitInfo = requireClassExport('RateLimitInfo')

      if (testName === 'test_default_values') {
        const rl = new RateLimitInfo()
        expect(rl.remaining_requests).toBeNull()
        expect(rl.remaining_tokens).toBeNull()
        expect(rl.limit_requests).toBeNull()
        expect(rl.limit_tokens).toBeNull()
        expect(rl.reset_at).toBeNull()
        expect(rl.retry_after).toBeNull()
        expect(rl.raw_headers).toEqual({})
        return
      }
      if (testName === 'test_normalized_fields') {
        const rl = new RateLimitInfo({
          remaining_requests: 100,
          remaining_tokens: 50000,
          limit_requests: 1000,
          limit_tokens: 100000,
        })
        expect(rl.remaining_requests).toBe(100)
        expect(rl.remaining_tokens).toBe(50000)
        expect(rl.limit_requests).toBe(1000)
        expect(rl.limit_tokens).toBe(100000)
        return
      }
      if (testName === 'test_timing_fields') {
        const nowSeconds = Date.now() / 1000
        const rl = new RateLimitInfo({ reset_at: nowSeconds + 60, retry_after: 30 })
        expect(rl.reset_at).toBe(nowSeconds + 60)
        expect(rl.retry_after).toBe(30)
        return
      }
      if (testName === 'test_raw_headers') {
        const headers = {
          'x-ratelimit-remaining-requests': '100',
          'x-custom-header': 'value',
        }
        const rl = new RateLimitInfo({ raw_headers: headers })
        expect(rl.raw_headers).toEqual(headers)
        expect(rl.raw_headers['x-custom-header']).toBe('value')
        return
      }
      if (testName === 'test_is_limited_false_when_none') {
        const rl = new RateLimitInfo()
        expect(rl.is_limited()).toBe(false)
        return
      }
      if (testName === 'test_is_limited_false_when_remaining') {
        const rl = new RateLimitInfo({ remaining_requests: 5, remaining_tokens: 1000 })
        expect(rl.is_limited()).toBe(false)
        return
      }
      if (testName === 'test_is_limited_true_when_requests_zero') {
        const rl = new RateLimitInfo({ remaining_requests: 0, remaining_tokens: 1000 })
        expect(rl.is_limited()).toBe(true)
        return
      }
      if (testName === 'test_is_limited_true_when_tokens_zero') {
        const rl = new RateLimitInfo({ remaining_requests: 5, remaining_tokens: 0 })
        expect(rl.is_limited()).toBe(true)
        return
      }
      if (testName === 'test_get_retry_delay_from_retry_after') {
        const rl = new RateLimitInfo({ retry_after: 60 })
        expect(rl.get_retry_delay()).toBe(60)
        return
      }
      if (testName === 'test_get_retry_delay_from_reset_at') {
        const rl = new RateLimitInfo({ reset_at: Date.now() / 1000 + 30 })
        const delay = rl.get_retry_delay()
        expect(delay).toBeGreaterThanOrEqual(28)
        expect(delay).toBeLessThanOrEqual(31)
        return
      }
      if (testName === 'test_get_retry_delay_none_when_no_timing') {
        const rl = new RateLimitInfo()
        expect(rl.get_retry_delay()).toBeNull()
        return
      }
      if (testName === 'test_get_retry_delay_prefers_retry_after') {
        const rl = new RateLimitInfo({ retry_after: 60, reset_at: Date.now() / 1000 + 300 })
        expect(rl.get_retry_delay()).toBe(60)
        return
      }

      const rl = new RateLimitInfo({ reset_at: Date.now() / 1000 - 60 })
      expect(rl.get_retry_delay()).toBe(0)
      return
    }

    if (group === 'TestErrorInfo') {
      const ErrorInfo = requireClassExport('ErrorInfo')

      if (testName === 'test_required_fields') {
        const error = new ErrorInfo({ error_type: 'RateLimitError', message: 'Too many requests' })
        expect(error.error_type).toBe('RateLimitError')
        expect(error.message).toBe('Too many requests')
        return
      }
      if (testName === 'test_default_values') {
        const error = new ErrorInfo({ error_type: 'Error', message: 'test' })
        expect(error.status_code).toBeNull()
        expect(error.retryable).toBe(false)
        return
      }
      if (testName === 'test_with_status_code') {
        const error = new ErrorInfo({
          error_type: 'RateLimitError',
          message: 'Too many requests',
          status_code: 429,
        })
        expect(error.status_code).toBe(429)
        return
      }

      const error = new ErrorInfo({
        error_type: 'RateLimitError',
        message: 'Too many requests',
        status_code: 429,
        retryable: true,
      })
      expect(error.retryable).toBe(true)
      return
    }

    if (group === 'TestFinishReason') {
      if (testName === 'test_all_values_exist') {
        expect(FinishReason.STOP).toBe('stop')
        expect(FinishReason.LENGTH).toBe('length')
        expect(FinishReason.TOOL_USE).toBe('tool_use')
        expect(FinishReason.ERROR).toBe('error')
        expect(FinishReason.ABORTED).toBe('aborted')
        expect(FinishReason.CONTENT_FILTER).toBe('content_filter')
        return
      }
      if (testName === 'test_is_string_enum') {
        expect(typeof FinishReason.STOP).toBe('string')
        expect(FinishReason.STOP).toBe('stop')
        return
      }
      if (testName === 'test_comparison') {
        expect(FinishReason.STOP).toBe('stop')
        expect(FinishReason.LENGTH).toBe('length')
        return
      }

      expect(FinishReason['STOP']).toBe('stop')
      return
    }

    const AgentResponse = requireClassExport('AgentResponse')
    if (testName === 'test_default_values') {
      const response = new AgentResponse()
      expect(response.content).toBeNull()
      expect(response.output).toBeNull()
      expect(response.tool_calls).toBeNull()
      expect(response.raw_response).toBeNull()
      expect(response.usage).toBeNull()
      expect(response.rate_limit).toBeNull()
      expect(response.finish_reason).toBeNull()
      expect(response.error).toBeNull()
      return
    }
    if (testName === 'test_success_property_true') {
      const response = new AgentResponse({ content: 'Hello' })
      expect(response.success).toBe(true)
      return
    }
    if (testName === 'test_success_property_false') {
      const ErrorInfo = requireClassExport('ErrorInfo')
      const response = new AgentResponse({
        error: new ErrorInfo({ error_type: 'Error', message: 'test' }),
      })
      expect(response.success).toBe(false)
      return
    }
    if (testName === 'test_content_response') {
      const response = new AgentResponse({ content: 'Hello, world!' })
      expect(response.content).toBe('Hello, world!')
      expect(response.success).toBe(true)
      return
    }
    if (testName === 'test_output_response') {
      const response = new AgentResponse({
        content: '{"greeting": "Hello"}',
        output: { greeting: 'Hello' },
      })
      expect(response.output).toEqual({ greeting: 'Hello' })
      return
    }
    if (testName === 'test_tool_calls_response') {
      const ToolCall = requireClassExport('ToolCall')
      const response = new AgentResponse({
        tool_calls: [
          new ToolCall({
            id: 'call_123',
            server: 'filesystem',
            tool: 'read_file',
            arguments: { path: '/test.txt' },
          }),
        ],
      })
      expect(response.tool_calls).toHaveLength(1)
      expect(response.tool_calls[0].tool).toBe('read_file')
      return
    }
    if (testName === 'test_with_usage') {
      const UsageInfo = requireClassExport('UsageInfo')
      const response = new AgentResponse({
        content: 'Hello',
        usage: new UsageInfo({ input_tokens: 100, output_tokens: 50, total_tokens: 150 }),
      })
      expect(response.usage.input_tokens).toBe(100)
      return
    }
    if (testName === 'test_with_rate_limit') {
      const RateLimitInfo = requireClassExport('RateLimitInfo')
      const response = new AgentResponse({
        content: 'Hello',
        rate_limit: new RateLimitInfo({ remaining_requests: 5, raw_headers: {} }),
      })
      expect(response.rate_limit.remaining_requests).toBe(5)
      return
    }
    if (testName === 'test_with_finish_reason') {
      const response = new AgentResponse({ content: 'Hello', finish_reason: FinishReason.STOP })
      expect(response.finish_reason).toBe(FinishReason.STOP)
      return
    }
    if (testName === 'test_error_response') {
      const ErrorInfo = requireClassExport('ErrorInfo')
      const RateLimitInfo = requireClassExport('RateLimitInfo')
      const response = new AgentResponse({
        error: new ErrorInfo({
          error_type: 'RateLimitError',
          message: 'Too many requests',
          status_code: 429,
          retryable: true,
        }),
        rate_limit: new RateLimitInfo({ remaining_requests: 0, retry_after: 60, raw_headers: {} }),
        finish_reason: FinishReason.ERROR,
      })
      expect(response.success).toBe(false)
      expect(response.error.error_type).toBe('RateLimitError')
      expect(response.error.retryable).toBe(true)
      expect(response.rate_limit.retry_after).toBe(60)
      expect(response.finish_reason).toBe(FinishReason.ERROR)
      return
    }

    const CostInfo = requireClassExport('CostInfo')
    const UsageInfo = requireClassExport('UsageInfo')
    const RateLimitInfo = requireClassExport('RateLimitInfo')
    const response = new AgentResponse({
      content: 'Hello, world!',
      output: { greeting: 'Hello, world!' },
      usage: new UsageInfo({
        input_tokens: 100,
        output_tokens: 50,
        total_tokens: 150,
        cache_read_tokens: 10,
        cost: new CostInfo({ input: 0.001, output: 0.002, total: 0.003 }),
      }),
      rate_limit: new RateLimitInfo({
        remaining_requests: 99,
        remaining_tokens: 99000,
        raw_headers: { 'x-test': 'value' },
      }),
      finish_reason: FinishReason.STOP,
    })

    expect(response.success).toBe(true)
    expect(response.content).toBe('Hello, world!')
    expect(response.output.greeting).toBe('Hello, world!')
    expect(response.usage.input_tokens).toBe(100)
    expect(response.usage.cache_read_tokens).toBe(10)
    expect(response.usage.estimated_cost).toBe(0.003)
    expect(response.rate_limit.remaining_requests).toBe(99)
    expect(response.finish_reason).toBe(FinishReason.STOP)
  })
})

describe('flatagent helpers parity', () => {
  const FLATAGENT_HELPER_CASES = expandCases({
    TestExtractCacheTokens: [
      'test_none_usage',
      'test_anthropic_style_cache_tokens',
      'test_openai_style_cache_tokens',
      'test_no_cache_tokens',
      'test_zero_cache_tokens',
      'test_anthropic_takes_precedence',
    ],
    TestCalculateCost: [
      'test_fallback_estimation',
      'test_cost_breakdown_proportional',
      'test_includes_cache_costs',
      'test_litellm_cost_calculation',
      'test_litellm_cost_with_breakdown',
      'test_aisuite_backend_uses_fallback',
      'test_handles_litellm_exception',
      'test_handles_zero_litellm_cost',
    ],
    TestExtractFinishReason: [
      'test_none_response',
      'test_no_choices',
      'test_no_finish_reason',
      'test_stop_reason',
      'test_end_turn_reason',
      'test_length_reason',
      'test_max_tokens_reason',
      'test_tool_calls_reason',
      'test_tool_use_reason',
      'test_function_call_reason',
      'test_content_filter_reason',
      'test_case_insensitive',
      'test_unknown_reason_defaults_to_stop',
    ],
    TestRecordRateLimitMetrics: [
      'test_records_normalized_fields',
      'test_records_timing_fields',
      'test_skips_none_fields',
      'test_no_longer_records_time_bucketed_fields',
    ],
  })

  it.each(FLATAGENT_HELPER_CASES)('%s', (caseName) => {
    const [group, testName] = caseName.split('.') as [string, string]

    if (group === 'TestExtractCacheTokens') {
      const extractCacheTokens = getFlatAgentHelper('_extract_cache_tokens')
      if (testName === 'test_none_usage') {
        const [cacheRead, cacheWrite] = extractCacheTokens.call({ _backend: 'litellm' }, null)
        expect(cacheRead).toBe(0)
        expect(cacheWrite).toBe(0)
        return
      }
      if (testName === 'test_anthropic_style_cache_tokens') {
        const usage = { cache_read_input_tokens: 1000, cache_creation_input_tokens: 500 }
        const [cacheRead, cacheWrite] = extractCacheTokens.call({ _backend: 'litellm' }, usage)
        expect(cacheRead).toBe(1000)
        expect(cacheWrite).toBe(500)
        return
      }
      if (testName === 'test_openai_style_cache_tokens') {
        const usage = {
          cache_read_input_tokens: null,
          cache_creation_input_tokens: null,
          prompt_tokens_details: { cached_tokens: 750 },
        }
        const [cacheRead, cacheWrite] = extractCacheTokens.call({ _backend: 'litellm' }, usage)
        expect(cacheRead).toBe(750)
        expect(cacheWrite).toBe(0)
        return
      }
      if (testName === 'test_no_cache_tokens') {
        const usage = {
          cache_read_input_tokens: null,
          cache_creation_input_tokens: null,
          prompt_tokens_details: null,
        }
        const [cacheRead, cacheWrite] = extractCacheTokens.call({ _backend: 'litellm' }, usage)
        expect(cacheRead).toBe(0)
        expect(cacheWrite).toBe(0)
        return
      }
      if (testName === 'test_zero_cache_tokens') {
        const usage = {
          cache_read_input_tokens: 0,
          cache_creation_input_tokens: 0,
          prompt_tokens_details: null,
        }
        const [cacheRead, cacheWrite] = extractCacheTokens.call({ _backend: 'litellm' }, usage)
        expect(cacheRead).toBe(0)
        expect(cacheWrite).toBe(0)
        return
      }

      const usage = {
        cache_read_input_tokens: 1000,
        cache_creation_input_tokens: 500,
        prompt_tokens_details: { cached_tokens: 750 },
      }
      const [cacheRead, cacheWrite] = extractCacheTokens.call({ _backend: 'litellm' }, usage)
      expect(cacheRead).toBe(1000)
      expect(cacheWrite).toBe(500)
      return
    }

    if (group === 'TestCalculateCost') {
      const calculateCost = getFlatAgentHelper('_calculate_cost')
      const baseArgs = {
        response: { id: 'mock' },
        input_tokens: 100,
        output_tokens: 50,
        cache_read_tokens: 0,
        cache_write_tokens: 0,
      }

      if (testName === 'test_fallback_estimation') {
        const cost = calculateCost.call({ _backend: 'litellm' }, baseArgs)
        expect(cost.total).toBeGreaterThan(0)
        expect(cost.input).toBeGreaterThan(0)
        expect(cost.output).toBeGreaterThan(0)
        return
      }
      if (testName === 'test_cost_breakdown_proportional') {
        const cost = calculateCost.call({ _backend: 'litellm' }, {
          ...baseArgs,
          output_tokens: 100,
        })
        expect(cost.output).toBeGreaterThan(cost.input)
        return
      }
      if (testName === 'test_includes_cache_costs') {
        const cost = calculateCost.call({ _backend: 'litellm' }, {
          ...baseArgs,
          cache_read_tokens: 200,
          cache_write_tokens: 100,
        })
        expect(cost.cache_read).toBeGreaterThanOrEqual(0)
        expect(cost.cache_write).toBeGreaterThanOrEqual(0)
        expect(cost.total).toBeCloseTo(cost.input + cost.output + cost.cache_read + cost.cache_write)
        return
      }
      if (testName === 'test_litellm_cost_calculation') {
        const cost = calculateCost.call({
          _backend: 'litellm',
          litellm: { completion_cost: () => 0.005 },
        }, baseArgs)
        expect(cost.total).toBe(0.005)
        return
      }
      if (testName === 'test_litellm_cost_with_breakdown') {
        const cost = calculateCost.call({
          _backend: 'litellm',
          litellm: { completion_cost: () => 0.003 },
        }, baseArgs)
        expect(cost.total).toBe(0.003)
        expect(cost.input).toBeGreaterThan(0)
        expect(cost.output).toBeGreaterThan(0)
        return
      }
      if (testName === 'test_aisuite_backend_uses_fallback') {
        const cost = calculateCost.call({ _backend: 'aisuite' }, baseArgs)
        expect(cost.total).toBeGreaterThan(0)
        return
      }
      if (testName === 'test_handles_litellm_exception') {
        const cost = calculateCost.call({
          _backend: 'litellm',
          litellm: { completion_cost: () => { throw new Error('Cost calculation failed') } },
        }, baseArgs)
        expect(cost.total).toBeGreaterThan(0)
        return
      }

      const cost = calculateCost.call({
        _backend: 'litellm',
        litellm: { completion_cost: () => 0 },
      }, baseArgs)
      expect(cost.total).toBeGreaterThan(0)
      return
    }

    if (group === 'TestExtractFinishReason') {
      const extractFinishReason = getFlatAgentHelper('_extract_finish_reason', '_extractFinishReason')

      if (testName === 'test_none_response') {
        expect(extractFinishReason.call({}, null)).toBeNull()
        return
      }
      if (testName === 'test_no_choices') {
        expect(extractFinishReason.call({}, { choices: [] })).toBeNull()
        return
      }
      if (testName === 'test_no_finish_reason') {
        expect(extractFinishReason.call({}, { choices: [{ finish_reason: null }] })).toBeNull()
        return
      }
      if (testName === 'test_stop_reason') {
        expect(extractFinishReason.call({}, { choices: [{ finish_reason: 'stop' }] })).toBe(FinishReason.STOP)
        return
      }
      if (testName === 'test_end_turn_reason') {
        expect(extractFinishReason.call({}, { choices: [{ finish_reason: 'end_turn' }] })).toBe(FinishReason.STOP)
        return
      }
      if (testName === 'test_length_reason') {
        expect(extractFinishReason.call({}, { choices: [{ finish_reason: 'length' }] })).toBe(FinishReason.LENGTH)
        return
      }
      if (testName === 'test_max_tokens_reason') {
        expect(extractFinishReason.call({}, { choices: [{ finish_reason: 'max_tokens' }] })).toBe(FinishReason.LENGTH)
        return
      }
      if (testName === 'test_tool_calls_reason') {
        expect(extractFinishReason.call({}, { choices: [{ finish_reason: 'tool_calls' }] })).toBe(FinishReason.TOOL_USE)
        return
      }
      if (testName === 'test_tool_use_reason') {
        expect(extractFinishReason.call({}, { choices: [{ finish_reason: 'tool_use' }] })).toBe(FinishReason.TOOL_USE)
        return
      }
      if (testName === 'test_function_call_reason') {
        expect(extractFinishReason.call({}, { choices: [{ finish_reason: 'function_call' }] })).toBe(FinishReason.TOOL_USE)
        return
      }
      if (testName === 'test_content_filter_reason') {
        expect(extractFinishReason.call({}, { choices: [{ finish_reason: 'content_filter' }] })).toBe(FinishReason.CONTENT_FILTER)
        return
      }
      if (testName === 'test_case_insensitive') {
        expect(extractFinishReason.call({}, { choices: [{ finish_reason: 'STOP' }] })).toBe(FinishReason.STOP)
        return
      }

      expect(extractFinishReason.call({}, { choices: [{ finish_reason: 'unknown_reason' }] })).toBe(FinishReason.STOP)
      return
    }

    const recordRateLimitMetrics = getFlatAgentHelper('_record_rate_limit_metrics')
    const monitor = { metrics: {} as Record<string, unknown> }

    if (testName === 'test_records_normalized_fields') {
      recordRateLimitMetrics.call({}, monitor, {
        remaining_requests: 100,
        remaining_tokens: 50000,
        limit_requests: 1000,
        limit_tokens: 100000,
        raw_headers: {},
      })
      expect(monitor.metrics.ratelimit_remaining_requests).toBe(100)
      expect(monitor.metrics.ratelimit_remaining_tokens).toBe(50000)
      expect(monitor.metrics.ratelimit_limit_requests).toBe(1000)
      expect(monitor.metrics.ratelimit_limit_tokens).toBe(100000)
      return
    }
    if (testName === 'test_records_timing_fields') {
      const resetAt = Date.now() / 1000 + 60
      recordRateLimitMetrics.call({}, monitor, {
        reset_at: resetAt,
        retry_after: 30,
        raw_headers: {},
      })
      expect(monitor.metrics.ratelimit_reset_at).toBe(resetAt)
      expect(monitor.metrics.ratelimit_retry_after).toBe(30)
      return
    }
    if (testName === 'test_skips_none_fields') {
      recordRateLimitMetrics.call({}, monitor, {
        remaining_requests: 100,
        remaining_tokens: null,
        raw_headers: {},
      })
      expect(monitor.metrics.ratelimit_remaining_requests).toBe(100)
      expect('ratelimit_remaining_tokens' in monitor.metrics).toBe(false)
      return
    }

    recordRateLimitMetrics.call({}, monitor, {
      remaining_requests: 100,
      raw_headers: {
        'x-ratelimit-remaining-requests-minute': '10',
      },
    })
    expect(monitor.metrics.ratelimit_remaining_requests).toBe(100)
    expect('ratelimit_remaining_requests_minute' in monitor.metrics).toBe(false)
  })
})

describe('flatmachines integration parity', () => {
  const FLATMACHINES_CASES = expandCases({
    TestAgentResult: [
      'test_default_values',
      'test_success_property_true',
      'test_success_property_false',
      'test_full_result',
      'test_error_result',
      'test_output_payload',
    ],
    TestCoerceAgentResult: [
      'test_already_agent_result',
      'test_dict_with_known_fields',
      'test_dict_without_known_fields',
      'test_none_input',
      'test_string_input',
    ],
    TestBuildRateLimitWindows: [
      'test_empty_headers',
      'test_cerebras_headers',
      'test_openai_headers',
      'test_anthropic_headers',
      'test_duration_parsing',
    ],
    TestBuildRateLimitState: [
      'test_empty_headers',
      'test_limited_state',
      'test_retry_after_from_headers',
      'test_retry_after_override',
      'test_not_limited_with_remaining',
    ],
    TestFlatAgentAdapterMapping: [
      'test_success_mapping',
      'test_error_mapping',
    ],
  })

  it.each(FLATMACHINES_CASES)('%s', async (caseName) => {
    const [group, testName] = caseName.split('.') as [string, string]

    if (group === 'TestAgentResult') {
      if (testName === 'test_default_values') {
        const result = coerceAgentResult(null)
        expect(result.output ?? null).toBeNull()
        expect(result.content ?? null).toBeNull()
        expect(result.finish_reason ?? null).toBeNull()
        expect(result.error ?? null).toBeNull()
        expect(result.rate_limit ?? null).toBeNull()
        expect((result as any).provider_data ?? null).toBeNull()
        return
      }
      if (testName === 'test_success_property_true') {
        expect(agentResultSuccess({ content: 'Hello' })).toBe(true)
        return
      }
      if (testName === 'test_success_property_false') {
        expect(agentResultSuccess({ error: { code: 'rate_limit', message: 'Too many requests' } })).toBe(false)
        return
      }
      if (testName === 'test_full_result') {
        const result = {
          output: { greeting: 'Hello' },
          content: 'Hello',
          usage: {
            input_tokens: 100,
            output_tokens: 50,
            cache_read_tokens: 10,
          },
          cost: { input: 0.001, output: 0.002, total: 0.003 },
          finish_reason: 'stop',
          error: null,
          rate_limit: { limited: false, retry_after: null, windows: [] },
          provider_data: {
            provider: 'openai',
            model: 'gpt-4',
            raw_headers: { 'x-request-id': 'abc123' },
          },
        }
        expect(agentResultSuccess(result)).toBe(true)
        expect(result.finish_reason).toBe('stop')
        expect(result.usage.cache_read_tokens).toBe(10)
        expect(result.provider_data.provider).toBe('openai')
        return
      }
      if (testName === 'test_error_result') {
        const result = {
          error: {
            code: 'rate_limit',
            type: 'RateLimitError',
            message: 'Too many requests',
            status_code: 429,
            retryable: true,
          },
          rate_limit: {
            limited: true,
            retry_after: 60,
            windows: [
              {
                name: 'requests_per_minute',
                resource: 'requests',
                remaining: 0,
                limit: 60,
              },
            ],
          },
          finish_reason: 'error',
        }
        expect(agentResultSuccess(result)).toBe(false)
        expect(result.error.code).toBe('rate_limit')
        expect(result.error.retryable).toBe(true)
        expect(result.rate_limit.limited).toBe(true)
        expect(result.rate_limit.retry_after).toBe(60)
        return
      }

      expect(agentResultOutputPayload({ output: { key: 'value' } })).toEqual({ key: 'value' })
      expect(agentResultOutputPayload({ content: 'Hello' })).toEqual({ content: 'Hello' })
      expect(agentResultOutputPayload({})).toEqual({})
      return
    }

    if (group === 'TestCoerceAgentResult') {
      if (testName === 'test_already_agent_result') {
        const original = { content: 'Hello' }
        const result = coerceAgentResult(original)
        expect(result).toBe(original)
        return
      }
      if (testName === 'test_dict_with_known_fields') {
        const value = {
          output: { key: 'value' },
          content: 'Hello',
          finish_reason: 'stop',
          error: null,
          rate_limit: { limited: false },
          provider_data: { provider: 'test' },
        }
        const result = coerceAgentResult(value)
        expect(result.output).toEqual({ key: 'value' })
        expect(result.finish_reason).toBe('stop')
        expect(result.rate_limit).toEqual({ limited: false })
        return
      }
      if (testName === 'test_dict_without_known_fields') {
        const value = { custom_key: 'custom_value' }
        const result = coerceAgentResult(value)
        expect(result.output).toEqual(value)
        expect(result.raw).toEqual(value)
        return
      }
      if (testName === 'test_none_input') {
        const result = coerceAgentResult(null)
        expect(result.output).toBeUndefined()
        return
      }

      const result = coerceAgentResult('Hello world')
      expect(result.content).toBe('Hello world')
      return
    }

    if (group === 'TestBuildRateLimitWindows') {
      if (testName === 'test_empty_headers') {
        expect(buildRateLimitWindows({})).toEqual([])
        return
      }
      if (testName === 'test_cerebras_headers') {
        const windows = buildRateLimitWindows({
          'x-ratelimit-remaining-requests-minute': '10',
          'x-ratelimit-remaining-requests-hour': '100',
          'x-ratelimit-remaining-requests-day': '1000',
          'x-ratelimit-remaining-tokens-minute': '5000',
          'x-ratelimit-remaining-tokens-day': '500000',
          'x-ratelimit-limit-requests-minute': '60',
          'x-ratelimit-limit-tokens-day': '1000000',
        })

        const names = windows.map((window) => window.name)
        expect(names).toContain('requests_per_minute')
        expect(names).toContain('requests_per_hour')
        expect(names).toContain('requests_per_day')
        expect(names).toContain('tokens_per_minute')
        expect(names).toContain('tokens_per_day')

        const minuteRequests = windows.find((window) => window.name === 'requests_per_minute')
        expect(minuteRequests?.remaining).toBe(10)
        expect(minuteRequests?.limit).toBe(60)
        expect(minuteRequests?.resource).toBe('requests')
        expect(minuteRequests?.resets_in).toBe(60)
        return
      }
      if (testName === 'test_openai_headers') {
        const windows = buildRateLimitWindows({
          'x-ratelimit-remaining-requests': '100',
          'x-ratelimit-remaining-tokens': '50000',
          'x-ratelimit-limit-requests': '1000',
          'x-ratelimit-reset-requests': '6m30s',
        })
        expect(windows).toHaveLength(2)
        const reqWindow = windows.find((window) => window.resource === 'requests')
        expect(reqWindow?.remaining).toBe(100)
        expect(reqWindow?.limit).toBe(1000)
        expect(reqWindow?.resets_in).toBe(390)
        return
      }
      if (testName === 'test_anthropic_headers') {
        const windows = buildRateLimitWindows({
          'anthropic-ratelimit-requests-remaining': '100',
          'anthropic-ratelimit-requests-limit': '1000',
          'anthropic-ratelimit-tokens-remaining': '50000',
          'anthropic-ratelimit-tokens-limit': '100000',
        })
        expect(windows).toHaveLength(2)
        const reqWindow = windows.find((window) => window.resource === 'requests')
        expect(reqWindow?.remaining).toBe(100)
        expect(reqWindow?.limit).toBe(1000)
        return
      }

      const minuteAndSeconds = buildRateLimitWindows({
        'x-ratelimit-remaining-requests': '100',
        'x-ratelimit-reset-requests': '6m30s',
      })
      expect(minuteAndSeconds.find((window) => window.resource === 'requests')?.resets_in).toBe(390)

      const hoursOnly = buildRateLimitWindows({
        'x-ratelimit-remaining-requests': '100',
        'x-ratelimit-reset-requests': '1h',
      })
      expect(hoursOnly.find((window) => window.resource === 'requests')?.resets_in).toBe(3600)

      const complex = buildRateLimitWindows({
        'x-ratelimit-remaining-requests': '100',
        'x-ratelimit-reset-requests': '1h30m45s',
      })
      expect(complex.find((window) => window.resource === 'requests')?.resets_in).toBe(5445)
      return
    }

    if (group === 'TestBuildRateLimitState') {
      if (testName === 'test_empty_headers') {
        const state = buildRateLimitState({})
        expect(state.limited).toBe(false)
        expect('retry_after' in state ? state.retry_after : null).toBeNull()
        return
      }
      if (testName === 'test_limited_state') {
        const state = buildRateLimitState({
          'x-ratelimit-remaining-requests-minute': '0',
          'x-ratelimit-limit-requests-minute': '60',
        })
        expect(state.limited).toBe(true)
        expect(Array.isArray(state.windows)).toBe(true)
        expect(state.windows.length).toBeGreaterThan(0)
        return
      }
      if (testName === 'test_retry_after_from_headers') {
        const state = buildRateLimitState({
          'retry-after': '60',
          'x-ratelimit-remaining-requests': '0',
        })
        expect(state.retry_after).toBe(60)
        return
      }
      if (testName === 'test_retry_after_override') {
        const state = buildRateLimitState({ 'retry-after': '60' }, 120)
        expect(state.retry_after).toBe(120)
        return
      }

      const state = buildRateLimitState({
        'x-ratelimit-remaining-requests-minute': '10',
        'x-ratelimit-remaining-tokens-minute': '5000',
      })
      expect(state.limited).toBe(false)
      return
    }

    if (testName === 'test_success_mapping') {
      const mockAgent = {
        call: vi.fn().mockResolvedValue({
          output: { greeting: 'Hello' },
          content: 'Hello',
          finish_reason: FinishReason.STOP,
          error: undefined,
          usage: {
            input_tokens: 100,
            output_tokens: 50,
            total_tokens: 150,
            cache_read_tokens: 10,
            cache_write_tokens: 5,
            cost: {
              input: 0.001,
              output: 0.002,
              cache_read: 0.0001,
              cache_write: 0.0002,
              total: 0.0033,
            },
          },
          rate_limit: {
            raw_headers: {
              'x-ratelimit-remaining-requests-minute': '10',
            },
            retry_after: undefined,
            remaining_requests: 10,
            remaining_tokens: 5000,
            limit_requests: 60,
            limit_tokens: 10000,
          },
        }),
      }

      const executor = new FlatAgentExecutor(mockAgent as any)
      const result = await executor.execute({ prompt: 'Hello' })

      expect(agentResultSuccess(result)).toBe(true)
      expect(result.output).toEqual({ greeting: 'Hello' })
      expect(result.finish_reason).toBe('stop')
      expect(result.usage?.input_tokens).toBe(100)
      expect(result.usage?.cache_read_tokens).toBe(10)
      expect((result.cost as any)?.total).toBe(0.0033)
      expect(result.rate_limit?.limited).toBe(false)
      expect(result.provider_data?.provider).toBe('cerebras')
      expect(result.provider_data).toHaveProperty('raw_headers')
      return
    }

    const mockAgent = {
      call: vi.fn().mockResolvedValue({
        output: undefined,
        content: undefined,
        finish_reason: FinishReason.ERROR,
        error: {
          error_type: 'RateLimitError',
          message: 'Too many requests',
          status_code: 429,
          retryable: true,
        },
        usage: undefined,
        rate_limit: {
          raw_headers: {
            'x-ratelimit-remaining-requests-minute': '0',
            'retry-after': '60',
          },
          retry_after: 60,
          remaining_requests: 0,
          remaining_tokens: undefined,
          limit_requests: 60,
          limit_tokens: undefined,
        },
      }),
    }

    const executor = new FlatAgentExecutor(mockAgent as any)
    const result = await executor.execute({ prompt: 'Hello' })

    expect(agentResultSuccess(result)).toBe(false)
    expect(result.error).toBeDefined()
    expect(result.error?.code).toBe('rate_limit')
    expect(result.error?.type).toBe('RateLimitError')
    expect(result.error?.status_code).toBe(429)
    expect(result.error?.retryable).toBe(true)
    expect(result.rate_limit?.limited).toBe(true)
    expect(result.finish_reason).toBe('error')
  })
})

describe('header extraction parity', () => {
  const HEADER_CASES = expandCases({
    TestNormalizeHeaders: [
      'test_none_input',
      'test_empty_dict',
      'test_dict_input',
      'test_mixed_case',
      'test_list_values',
      'test_tuple_input',
      'test_httpx_headers',
      'test_none_key_skipped',
      'test_numeric_values',
    ],
    TestParseIntHeader: [
      'test_valid_int',
      'test_missing_key',
      'test_multiple_keys_first_match',
      'test_multiple_keys_fallback',
      'test_invalid_int',
      'test_case_insensitive',
      'test_empty_value',
    ],
    TestParseResetTimestamp: [
      'test_unix_timestamp_seconds',
      'test_unix_timestamp_milliseconds',
      'test_relative_seconds',
      'test_relative_seconds_with_suffix',
      'test_iso8601_utc',
      'test_iso8601_with_microseconds',
      'test_multiple_keys_fallback',
      'test_missing_key',
      'test_invalid_format',
    ],
    TestExtractRateLimitInfo: [
      'test_empty_headers',
      'test_openai_headers',
      'test_anthropic_headers',
      'test_generic_headers',
      'test_retry_after',
      'test_reset_timestamp',
      'test_raw_headers_preserved',
      'test_mixed_provider_headers',
    ],
    TestExtractHeadersFromResponse: [
      'test_none_response',
      'test_litellm_response_headers',
      'test_litellm_hidden_params',
      'test_combines_both_sources',
      'test_no_headers',
    ],
    TestExtractHeadersFromError: [
      'test_simple_exception',
      'test_error_with_response_headers',
      'test_error_with_dict_response',
      'test_error_with_direct_headers',
      'test_combines_sources',
    ],
    TestExtractStatusCode: [
      'test_simple_exception',
      'test_status_code_attribute',
      'test_status_attribute',
      'test_http_status_attribute',
      'test_response_status_code',
      'test_dict_response',
      'test_parse_from_message',
      'test_parse_500_from_message',
      'test_no_false_positives',
    ],
    TestIsRetryableError: [
      'test_429_is_retryable',
      'test_500_is_retryable',
      'test_502_is_retryable',
      'test_503_is_retryable',
      'test_400_is_not_retryable',
      'test_401_is_not_retryable',
      'test_404_is_not_retryable',
      'test_ratelimit_error_type',
      'test_timeout_error_type',
      'test_rate_limit_message',
      'test_too_many_requests_message',
      'test_timeout_message',
      'test_temporarily_message',
      'test_generic_error_not_retryable',
    ],
  })

  it.each(HEADER_CASES)('%s', (caseName) => {
    const [group, testName] = caseName.split('.') as [string, string]

    if (group === 'TestNormalizeHeaders') {
      if (testName === 'test_none_input') {
        expect(normalizeHeaders(null)).toEqual({})
        return
      }
      if (testName === 'test_empty_dict') {
        expect(normalizeHeaders({})).toEqual({})
        return
      }
      if (testName === 'test_dict_input') {
        const normalized = normalizeHeaders({ 'Content-Type': 'application/json', 'X-Request-ID': '123' })
        expect(normalized['content-type']).toBe('application/json')
        expect(normalized['x-request-id']).toBe('123')
        return
      }
      if (testName === 'test_mixed_case') {
        const normalized = normalizeHeaders({ 'X-RateLimit-Remaining': '100' })
        expect(normalized['x-ratelimit-remaining']).toBe('100')
        return
      }
      if (testName === 'test_list_values') {
        const normalized = normalizeHeaders({ 'Set-Cookie': ['a=1', 'b=2'] as any })
        expect(normalized['set-cookie']).toBe('a=1,b=2')
        return
      }
      if (testName === 'test_tuple_input') {
        const normalized = normalizeHeaders([
          ['Content-Type', 'text/plain'],
          ['X-Custom', 'value'],
        ] as any)
        expect(normalized['content-type']).toBe('text/plain')
        expect(normalized['x-custom']).toBe('value')
        return
      }
      if (testName === 'test_httpx_headers') {
        const normalized = normalizeHeaders({ items: () => [['Content-Type', 'application/json']] } as any)
        expect(normalized['content-type']).toBe('application/json')
        return
      }
      if (testName === 'test_none_key_skipped') {
        const normalized = normalizeHeaders({ [null as any]: 'value', valid: 'data' })
        expect('none' in normalized).toBe(false)
        expect(normalized.valid).toBe('data')
        return
      }

      const normalized = normalizeHeaders({ 'x-count': 100 as any })
      expect(normalized['x-count']).toBe('100')
      return
    }

    if (group === 'TestParseIntHeader') {
      if (testName === 'test_valid_int') {
        const info = extractRateLimitInfo({ 'x-ratelimit-remaining-requests': '100' })
        expect(info.remaining_requests).toBe(100)
        return
      }
      if (testName === 'test_missing_key') {
        const info = extractRateLimitInfo({ 'x-other': '100' })
        expect(info.remaining_requests).toBeUndefined()
        return
      }
      if (testName === 'test_multiple_keys_first_match') {
        const info = extractRateLimitInfo({
          'x-ratelimit-remaining-requests': '100',
          'ratelimit-remaining': '200',
        })
        expect(info.remaining_requests).toBe(100)
        return
      }
      if (testName === 'test_multiple_keys_fallback') {
        const info = extractRateLimitInfo({
          'ratelimit-remaining': '200',
        })
        expect(info.remaining_requests).toBe(200)
        return
      }
      if (testName === 'test_invalid_int') {
        const info = extractRateLimitInfo({ 'x-ratelimit-remaining-requests': 'not-a-number' })
        expect(info.remaining_requests).toBeUndefined()
        return
      }
      if (testName === 'test_case_insensitive') {
        const info = extractRateLimitInfo(normalizeHeaders({ 'X-RateLimit-Remaining-Requests': '100' }))
        expect(info.remaining_requests).toBe(100)
        return
      }

      const info = extractRateLimitInfo({ 'x-ratelimit-remaining-requests': '' })
      expect(info.remaining_requests).toBeUndefined()
      return
    }

    if (group === 'TestParseResetTimestamp') {
      if (testName === 'test_unix_timestamp_seconds') {
        const now = Math.floor(Date.now() / 1000)
        const info = extractRateLimitInfo({ 'x-ratelimit-reset-requests': String(now + 60) })
        expect(info.reset_at).toBeDefined()
        expect(Math.abs((info.reset_at ?? 0) - (now + 60))).toBeLessThan(1)
        return
      }
      if (testName === 'test_unix_timestamp_milliseconds') {
        const nowMs = Date.now()
        const info = extractRateLimitInfo({ 'x-ratelimit-reset-requests': String(nowMs + 60000) })
        expect(info.reset_at).toBeDefined()
        expect((info.reset_at ?? 0)).toBeLessThan(nowMs)
        return
      }
      if (testName === 'test_relative_seconds') {
        const before = Date.now() / 1000
        const info = extractRateLimitInfo({ 'x-ratelimit-reset-requests': '60' })
        const after = Date.now() / 1000
        expect(info.reset_at).toBeDefined()
        expect((info.reset_at ?? 0)).toBeGreaterThanOrEqual(before + 59)
        expect((info.reset_at ?? 0)).toBeLessThanOrEqual(after + 61)
        return
      }
      if (testName === 'test_relative_seconds_with_suffix') {
        const before = Date.now() / 1000
        const info = extractRateLimitInfo({ 'x-ratelimit-reset-requests': '60s' })
        const after = Date.now() / 1000
        expect(info.reset_at).toBeDefined()
        expect((info.reset_at ?? 0)).toBeGreaterThanOrEqual(before + 59)
        expect((info.reset_at ?? 0)).toBeLessThanOrEqual(after + 61)
        return
      }
      if (testName === 'test_iso8601_utc') {
        const info = extractRateLimitInfo({ 'x-ratelimit-reset-requests': '2024-06-15T12:00:00Z' })
        expect(info.reset_at).toBeDefined()
        expect((info.reset_at ?? 0)).toBeGreaterThan(1700000000)
        return
      }
      if (testName === 'test_iso8601_with_microseconds') {
        const info = extractRateLimitInfo({ 'x-ratelimit-reset-requests': '2024-06-15T12:00:00.123456Z' })
        expect(info.reset_at).toBeDefined()
        return
      }
      if (testName === 'test_multiple_keys_fallback') {
        const info = extractRateLimitInfo({ 'x-ratelimit-reset-tokens': '60' })
        expect(info.reset_at).toBeDefined()
        return
      }
      if (testName === 'test_missing_key') {
        const info = extractRateLimitInfo({ 'x-other': '60' })
        expect(info.reset_at).toBeUndefined()
        return
      }

      const info = extractRateLimitInfo({ 'x-ratelimit-reset-requests': 'not-a-timestamp' })
      expect(info.reset_at).toBeUndefined()
      return
    }

    if (group === 'TestExtractRateLimitInfo') {
      if (testName === 'test_empty_headers') {
        const info = extractRateLimitInfo({})
        expect(info.remaining_requests).toBeUndefined()
        expect(info.remaining_tokens).toBeUndefined()
        expect(info.raw_headers).toEqual({})
        return
      }
      if (testName === 'test_openai_headers') {
        const info = extractRateLimitInfo({
          'x-ratelimit-remaining-requests': '100',
          'x-ratelimit-remaining-tokens': '50000',
          'x-ratelimit-limit-requests': '1000',
          'x-ratelimit-limit-tokens': '100000',
        })
        expect(info.remaining_requests).toBe(100)
        expect(info.remaining_tokens).toBe(50000)
        expect(info.limit_requests).toBe(1000)
        expect(info.limit_tokens).toBe(100000)
        return
      }
      if (testName === 'test_anthropic_headers') {
        const info = extractRateLimitInfo({
          'anthropic-ratelimit-requests-remaining': '100',
          'anthropic-ratelimit-tokens-remaining': '50000',
          'anthropic-ratelimit-requests-limit': '1000',
          'anthropic-ratelimit-tokens-limit': '100000',
        })
        expect(info.remaining_requests).toBe(100)
        expect(info.remaining_tokens).toBe(50000)
        expect(info.limit_requests).toBe(1000)
        expect(info.limit_tokens).toBe(100000)
        return
      }
      if (testName === 'test_generic_headers') {
        const info = extractRateLimitInfo({
          'ratelimit-remaining': '100',
          'ratelimit-limit': '1000',
        })
        expect(info.remaining_requests).toBe(100)
        expect(info.limit_requests).toBe(1000)
        return
      }
      if (testName === 'test_retry_after') {
        const info = extractRateLimitInfo({ 'retry-after': '60' })
        expect(info.retry_after).toBe(60)
        return
      }
      if (testName === 'test_reset_timestamp') {
        const info = extractRateLimitInfo({ 'x-ratelimit-reset-requests': '2024-06-15T12:00:00Z' })
        expect(info.reset_at).toBeDefined()
        return
      }
      if (testName === 'test_raw_headers_preserved') {
        const headers = {
          'x-ratelimit-remaining-requests': '100',
          'x-custom-header': 'value',
        }
        const info = extractRateLimitInfo(headers)
        expect(info.raw_headers).toEqual(headers)
        expect(info.raw_headers['x-custom-header']).toBe('value')
        return
      }

      const info = extractRateLimitInfo({
        'x-ratelimit-remaining-requests': '100',
        'anthropic-ratelimit-requests-remaining': '200',
      })
      expect(info.remaining_requests).toBe(100)
      return
    }

    if (group === 'TestExtractHeadersFromResponse') {
      const extractHeadersFromResponse = requireFunctionExport('extract_headers_from_response')
      if (testName === 'test_none_response') {
        expect(extractHeadersFromResponse(null)).toEqual({})
        return
      }
      if (testName === 'test_litellm_response_headers') {
        const headers = extractHeadersFromResponse({
          _response_headers: { 'x-ratelimit-remaining-requests': '100' },
          _hidden_params: null,
        })
        expect(headers).toHaveProperty('x-ratelimit-remaining-requests')
        return
      }
      if (testName === 'test_litellm_hidden_params') {
        const headers = extractHeadersFromResponse({
          _response_headers: null,
          _hidden_params: { additional_headers: { 'x-custom': 'value' } },
        })
        expect(headers).toHaveProperty('x-custom')
        return
      }
      if (testName === 'test_combines_both_sources') {
        const headers = extractHeadersFromResponse({
          _response_headers: { 'x-from-response': '1' },
          _hidden_params: { additional_headers: { 'x-from-hidden': '2' } },
        })
        expect(headers).toHaveProperty('x-from-response')
        expect(headers).toHaveProperty('x-from-hidden')
        return
      }

      expect(extractHeadersFromResponse({ _response_headers: null, _hidden_params: null })).toEqual({})
      return
    }

    if (group === 'TestExtractHeadersFromError') {
      const extractHeadersFromError = requireFunctionExport('extract_headers_from_error')
      if (testName === 'test_simple_exception') {
        expect(extractHeadersFromError(new Error('test error'))).toEqual({})
        return
      }
      if (testName === 'test_error_with_response_headers') {
        const error = Object.assign(new Error('test'), {
          response: { headers: { 'x-ratelimit-remaining': '0' } },
        })
        const headers = extractHeadersFromError(error)
        expect(headers).toHaveProperty('x-ratelimit-remaining')
        return
      }
      if (testName === 'test_error_with_dict_response') {
        const error = Object.assign(new Error('test'), {
          response: { headers: { 'x-custom': 'value' } },
        })
        const headers = extractHeadersFromError(error)
        expect(headers).toHaveProperty('x-custom')
        return
      }
      if (testName === 'test_error_with_direct_headers') {
        const error = Object.assign(new Error('test'), {
          headers: { 'x-direct': 'value' },
        })
        const headers = extractHeadersFromError(error)
        expect(headers).toHaveProperty('x-direct')
        return
      }

      const error = Object.assign(new Error('test'), {
        response: { headers: { 'x-from-response': '1' } },
        headers: { 'x-from-error': '2' },
      })
      const headers = extractHeadersFromError(error)
      expect(headers).toHaveProperty('x-from-response')
      expect(headers).toHaveProperty('x-from-error')
      return
    }

    if (group === 'TestExtractStatusCode') {
      if (testName === 'test_simple_exception') {
        expect(extractStatusCode(new Error('test error'))).toBeUndefined()
        return
      }
      if (testName === 'test_status_code_attribute') {
        expect(extractStatusCode({ status_code: 429 })).toBe(429)
        return
      }
      if (testName === 'test_status_attribute') {
        expect(extractStatusCode({ status: 500 })).toBe(500)
        return
      }
      if (testName === 'test_http_status_attribute') {
        expect(extractStatusCode({ http_status: 503 })).toBe(503)
        return
      }
      if (testName === 'test_response_status_code') {
        expect(extractStatusCode({ response: { status_code: 429 } })).toBe(429)
        return
      }
      if (testName === 'test_dict_response') {
        expect(extractStatusCode({ response: { status_code: 404 } })).toBe(404)
        return
      }
      if (testName === 'test_parse_from_message') {
        expect(extractStatusCode(new Error('Error 429: Too many requests'))).toBe(429)
        return
      }
      if (testName === 'test_parse_500_from_message') {
        expect(extractStatusCode(new Error('Server error 503'))).toBe(503)
        return
      }

      expect(extractStatusCode(new Error('Request took 1234ms'))).toBeUndefined()
      return
    }

    if (testName === 'test_429_is_retryable') {
      expect(isRetryableError(new Error('Rate limited'), 429)).toBe(true)
      return
    }
    if (testName === 'test_500_is_retryable') {
      expect(isRetryableError(new Error('Server error'), 500)).toBe(true)
      return
    }
    if (testName === 'test_502_is_retryable') {
      expect(isRetryableError(new Error('Bad gateway'), 502)).toBe(true)
      return
    }
    if (testName === 'test_503_is_retryable') {
      expect(isRetryableError(new Error('Service unavailable'), 503)).toBe(true)
      return
    }
    if (testName === 'test_400_is_not_retryable') {
      expect(isRetryableError(new Error('Bad request'), 400)).toBe(false)
      return
    }
    if (testName === 'test_401_is_not_retryable') {
      expect(isRetryableError(new Error('Unauthorized'), 401)).toBe(false)
      return
    }
    if (testName === 'test_404_is_not_retryable') {
      expect(isRetryableError(new Error('Not found'), 404)).toBe(false)
      return
    }
    if (testName === 'test_ratelimit_error_type') {
      class RateLimitError extends Error {}
      expect(isRetryableError(new RateLimitError('Rate limited'), undefined)).toBe(true)
      return
    }
    if (testName === 'test_timeout_error_type') {
      class TimeoutError extends Error {}
      expect(isRetryableError(new TimeoutError('Timed out'), undefined)).toBe(true)
      return
    }
    if (testName === 'test_rate_limit_message') {
      expect(isRetryableError(new Error('You have exceeded the rate limit'), undefined)).toBe(true)
      return
    }
    if (testName === 'test_too_many_requests_message') {
      expect(isRetryableError(new Error('Error: too many requests, please slow down'), undefined)).toBe(true)
      return
    }
    if (testName === 'test_timeout_message') {
      expect(isRetryableError(new Error('Connection timeout after 30s'), undefined)).toBe(true)
      return
    }
    if (testName === 'test_temporarily_message') {
      expect(isRetryableError(new Error('Service temporarily unavailable'), undefined)).toBe(true)
      return
    }

    expect(isRetryableError(new Error('Something went wrong'), undefined)).toBe(false)
  })
})

describe('providers parity', () => {
  const PROVIDERS_CASES = expandCases({
    TestCerebrasRateLimits: [
      'test_default_values',
      'test_all_fields',
      'test_is_limited_false_when_remaining',
      'test_is_limited_true_when_minute_exhausted',
      'test_is_limited_true_when_tokens_exhausted',
      'test_get_most_restrictive_bucket_minute',
      'test_get_most_restrictive_bucket_hour',
      'test_get_most_restrictive_bucket_day',
      'test_get_most_restrictive_bucket_none',
      'test_get_suggested_wait_seconds_minute',
      'test_get_suggested_wait_seconds_hour',
      'test_get_suggested_wait_seconds_day',
      'test_get_suggested_wait_seconds_none',
    ],
    TestExtractCerebrasRateLimits: [
      'test_empty_headers',
      'test_all_headers',
      'test_partial_headers',
      'test_invalid_values_ignored',
      'test_integration_with_ratelimitinfo',
    ],
    TestAnthropicRateLimits: [
      'test_default_values',
      'test_all_fields',
      'test_is_limited_false',
      'test_is_limited_true_requests',
      'test_is_limited_true_tokens',
      'test_is_limited_true_input_tokens',
      'test_is_limited_true_output_tokens',
      'test_get_next_reset',
      'test_get_next_reset_none',
    ],
    TestExtractAnthropicRateLimits: [
      'test_empty_headers',
      'test_basic_headers',
      'test_reset_timestamps',
      'test_input_output_tokens',
      'test_invalid_values_ignored',
    ],
    TestOpenAIRateLimits: [
      'test_default_values',
      'test_all_fields',
      'test_is_limited_false',
      'test_is_limited_true_requests',
      'test_is_limited_true_tokens',
      'test_get_seconds_until_reset',
      'test_get_seconds_until_reset_none',
    ],
    TestExtractOpenAIRateLimits: [
      'test_empty_headers',
      'test_basic_headers',
      'test_reset_duration_minutes_seconds',
      'test_reset_duration_hours',
      'test_reset_duration_complex',
      'test_reset_duration_milliseconds',
      'test_reset_duration_seconds_only',
      'test_invalid_values_ignored',
    ],
    TestCrossProviderIntegration: [
      'test_extract_from_ratelimitinfo_raw_headers',
      'test_all_extractors_handle_empty',
      'test_all_extractors_handle_wrong_provider',
    ],
  })

  it.each(PROVIDERS_CASES)('%s', (caseName) => {
    const [group, testName] = caseName.split('.') as [string, string]

    if (group === 'TestCerebrasRateLimits') {
      const CerebrasRateLimits = requireClassExport('CerebrasRateLimits')
      if (testName === 'test_default_values') {
        const limits = new CerebrasRateLimits()
        expect(limits.remaining_requests_minute).toBeNull()
        expect(limits.remaining_requests_hour).toBeNull()
        expect(limits.remaining_requests_day).toBeNull()
        expect(limits.remaining_tokens_minute).toBeNull()
        expect(limits.remaining_tokens_hour).toBeNull()
        expect(limits.remaining_tokens_day).toBeNull()
        return
      }
      if (testName === 'test_all_fields') {
        const limits = new CerebrasRateLimits({
          remaining_requests_minute: 10,
          remaining_requests_hour: 100,
          remaining_requests_day: 1000,
          remaining_tokens_minute: 5000,
          remaining_tokens_hour: 50000,
          remaining_tokens_day: 500000,
          limit_requests_minute: 60,
          limit_requests_hour: 600,
          limit_requests_day: 6000,
          limit_tokens_minute: 10000,
          limit_tokens_hour: 100000,
          limit_tokens_day: 1000000,
        })
        expect(limits.remaining_requests_minute).toBe(10)
        expect(limits.remaining_tokens_day).toBe(500000)
        expect(limits.limit_requests_minute).toBe(60)
        return
      }
      if (testName === 'test_is_limited_false_when_remaining') {
        const limits = new CerebrasRateLimits({
          remaining_requests_minute: 10,
          remaining_requests_hour: 100,
          remaining_requests_day: 1000,
          remaining_tokens_minute: 5000,
          remaining_tokens_hour: 50000,
          remaining_tokens_day: 500000,
        })
        expect(limits.is_limited()).toBe(false)
        return
      }
      if (testName === 'test_is_limited_true_when_minute_exhausted') {
        const limits = new CerebrasRateLimits({
          remaining_requests_minute: 0,
          remaining_requests_hour: 100,
          remaining_requests_day: 1000,
        })
        expect(limits.is_limited()).toBe(true)
        return
      }
      if (testName === 'test_is_limited_true_when_tokens_exhausted') {
        const limits = new CerebrasRateLimits({ remaining_tokens_hour: 0 })
        expect(limits.is_limited()).toBe(true)
        return
      }
      if (testName === 'test_get_most_restrictive_bucket_minute') {
        const limits = new CerebrasRateLimits({
          remaining_requests_minute: 0,
          remaining_requests_hour: 100,
        })
        expect(limits.get_most_restrictive_bucket()).toBe('minute')
        return
      }
      if (testName === 'test_get_most_restrictive_bucket_hour') {
        const limits = new CerebrasRateLimits({
          remaining_requests_minute: 10,
          remaining_tokens_hour: 0,
        })
        expect(limits.get_most_restrictive_bucket()).toBe('hour')
        return
      }
      if (testName === 'test_get_most_restrictive_bucket_day') {
        const limits = new CerebrasRateLimits({
          remaining_requests_minute: 10,
          remaining_requests_hour: 100,
          remaining_requests_day: 0,
        })
        expect(limits.get_most_restrictive_bucket()).toBe('day')
        return
      }
      if (testName === 'test_get_most_restrictive_bucket_none') {
        const limits = new CerebrasRateLimits({
          remaining_requests_minute: 10,
          remaining_requests_hour: 100,
        })
        expect(limits.get_most_restrictive_bucket()).toBeNull()
        return
      }
      if (testName === 'test_get_suggested_wait_seconds_minute') {
        expect(new CerebrasRateLimits({ remaining_requests_minute: 0 }).get_suggested_wait_seconds()).toBe(60)
        return
      }
      if (testName === 'test_get_suggested_wait_seconds_hour') {
        expect(new CerebrasRateLimits({ remaining_requests_minute: 10, remaining_requests_hour: 0 }).get_suggested_wait_seconds()).toBe(3600)
        return
      }
      if (testName === 'test_get_suggested_wait_seconds_day') {
        expect(new CerebrasRateLimits({ remaining_requests_minute: 10, remaining_requests_hour: 100, remaining_requests_day: 0 }).get_suggested_wait_seconds()).toBe(86400)
        return
      }

      expect(new CerebrasRateLimits().get_suggested_wait_seconds()).toBeNull()
      return
    }

    if (group === 'TestExtractCerebrasRateLimits') {
      const extractCerebrasRateLimits = requireFunctionExport('extract_cerebras_rate_limits')
      if (testName === 'test_empty_headers') {
        const result = extractCerebrasRateLimits({})
        expect(result.remaining_requests_minute).toBeNull()
        return
      }
      if (testName === 'test_all_headers') {
        const result = extractCerebrasRateLimits({
          'x-ratelimit-remaining-requests-minute': '10',
          'x-ratelimit-remaining-requests-hour': '100',
          'x-ratelimit-remaining-requests-day': '1000',
          'x-ratelimit-remaining-tokens-minute': '5000',
          'x-ratelimit-remaining-tokens-hour': '50000',
          'x-ratelimit-remaining-tokens-day': '500000',
          'x-ratelimit-limit-requests-minute': '60',
          'x-ratelimit-limit-requests-hour': '600',
          'x-ratelimit-limit-requests-day': '6000',
          'x-ratelimit-limit-tokens-minute': '10000',
          'x-ratelimit-limit-tokens-hour': '100000',
          'x-ratelimit-limit-tokens-day': '1000000',
        })
        expect(result.remaining_requests_minute).toBe(10)
        expect(result.remaining_requests_hour).toBe(100)
        expect(result.remaining_requests_day).toBe(1000)
        expect(result.remaining_tokens_minute).toBe(5000)
        expect(result.remaining_tokens_hour).toBe(50000)
        expect(result.remaining_tokens_day).toBe(500000)
        expect(result.limit_requests_minute).toBe(60)
        expect(result.limit_requests_hour).toBe(600)
        expect(result.limit_requests_day).toBe(6000)
        expect(result.limit_tokens_minute).toBe(10000)
        expect(result.limit_tokens_hour).toBe(100000)
        expect(result.limit_tokens_day).toBe(1000000)
        return
      }
      if (testName === 'test_partial_headers') {
        const result = extractCerebrasRateLimits({
          'x-ratelimit-remaining-requests-minute': '10',
          'x-ratelimit-remaining-tokens-day': '500000',
        })
        expect(result.remaining_requests_minute).toBe(10)
        expect(result.remaining_requests_hour).toBeNull()
        expect(result.remaining_tokens_day).toBe(500000)
        return
      }
      if (testName === 'test_invalid_values_ignored') {
        const result = extractCerebrasRateLimits({ 'x-ratelimit-remaining-requests-minute': 'not-a-number' })
        expect(result.remaining_requests_minute).toBeNull()
        return
      }

      const rateLimit = extractRateLimitInfo({
        'x-ratelimit-remaining-requests': '100',
        'x-ratelimit-remaining-requests-minute': '10',
        'x-ratelimit-remaining-requests-day': '1000',
      })
      expect(rateLimit.remaining_requests).toBe(100)
      const result = extractCerebrasRateLimits(rateLimit.raw_headers)
      expect(result.remaining_requests_minute).toBe(10)
      expect(result.remaining_requests_day).toBe(1000)
      return
    }

    if (group === 'TestAnthropicRateLimits') {
      const AnthropicRateLimits = requireClassExport('AnthropicRateLimits')
      if (testName === 'test_default_values') {
        const limits = new AnthropicRateLimits()
        expect(limits.requests_remaining).toBeNull()
        expect(limits.requests_limit).toBeNull()
        expect(limits.requests_reset).toBeNull()
        expect(limits.tokens_remaining).toBeNull()
        expect(limits.tokens_limit).toBeNull()
        expect(limits.tokens_reset).toBeNull()
        return
      }
      if (testName === 'test_all_fields') {
        const resetTime = new Date('2024-06-15T12:00:00Z')
        const limits = new AnthropicRateLimits({
          requests_remaining: 100,
          requests_limit: 1000,
          requests_reset: resetTime,
          tokens_remaining: 50000,
          tokens_limit: 100000,
          tokens_reset: resetTime,
          input_tokens_remaining: 25000,
          input_tokens_limit: 50000,
          output_tokens_remaining: 25000,
          output_tokens_limit: 50000,
        })
        expect(limits.requests_remaining).toBe(100)
        expect(limits.tokens_limit).toBe(100000)
        expect(limits.requests_reset).toEqual(resetTime)
        return
      }
      if (testName === 'test_is_limited_false') {
        expect(new AnthropicRateLimits({ requests_remaining: 100, tokens_remaining: 50000 }).is_limited()).toBe(false)
        return
      }
      if (testName === 'test_is_limited_true_requests') {
        expect(new AnthropicRateLimits({ requests_remaining: 0 }).is_limited()).toBe(true)
        return
      }
      if (testName === 'test_is_limited_true_tokens') {
        expect(new AnthropicRateLimits({ tokens_remaining: 0 }).is_limited()).toBe(true)
        return
      }
      if (testName === 'test_is_limited_true_input_tokens') {
        expect(new AnthropicRateLimits({ input_tokens_remaining: 0 }).is_limited()).toBe(true)
        return
      }
      if (testName === 'test_is_limited_true_output_tokens') {
        expect(new AnthropicRateLimits({ output_tokens_remaining: 0 }).is_limited()).toBe(true)
        return
      }
      if (testName === 'test_get_next_reset') {
        const early = new Date('2024-06-15T12:00:00Z')
        const late = new Date('2024-06-15T13:00:00Z')
        const limits = new AnthropicRateLimits({ requests_reset: late, tokens_reset: early })
        expect(limits.get_next_reset()).toEqual(early)
        return
      }

      expect(new AnthropicRateLimits().get_next_reset()).toBeNull()
      return
    }

    if (group === 'TestExtractAnthropicRateLimits') {
      const extractAnthropicRateLimits = requireFunctionExport('extract_anthropic_rate_limits')
      if (testName === 'test_empty_headers') {
        const result = extractAnthropicRateLimits({})
        expect(result.requests_remaining).toBeNull()
        return
      }
      if (testName === 'test_basic_headers') {
        const result = extractAnthropicRateLimits({
          'anthropic-ratelimit-requests-remaining': '100',
          'anthropic-ratelimit-requests-limit': '1000',
          'anthropic-ratelimit-tokens-remaining': '50000',
          'anthropic-ratelimit-tokens-limit': '100000',
        })
        expect(result.requests_remaining).toBe(100)
        expect(result.requests_limit).toBe(1000)
        expect(result.tokens_remaining).toBe(50000)
        expect(result.tokens_limit).toBe(100000)
        return
      }
      if (testName === 'test_reset_timestamps') {
        const result = extractAnthropicRateLimits({
          'anthropic-ratelimit-requests-remaining': '100',
          'anthropic-ratelimit-requests-reset': '2024-06-15T12:00:00Z',
        })
        expect(result.requests_remaining).toBe(100)
        expect(result.requests_reset).toBeDefined()
        return
      }
      if (testName === 'test_input_output_tokens') {
        const result = extractAnthropicRateLimits({
          'anthropic-ratelimit-input-tokens-remaining': '25000',
          'anthropic-ratelimit-input-tokens-limit': '50000',
          'anthropic-ratelimit-output-tokens-remaining': '25000',
          'anthropic-ratelimit-output-tokens-limit': '50000',
        })
        expect(result.input_tokens_remaining).toBe(25000)
        expect(result.input_tokens_limit).toBe(50000)
        expect(result.output_tokens_remaining).toBe(25000)
        expect(result.output_tokens_limit).toBe(50000)
        return
      }

      const result = extractAnthropicRateLimits({ 'anthropic-ratelimit-requests-remaining': 'not-a-number' })
      expect(result.requests_remaining).toBeNull()
      return
    }

    if (group === 'TestOpenAIRateLimits') {
      const OpenAIRateLimits = requireClassExport('OpenAIRateLimits')
      if (testName === 'test_default_values') {
        const limits = new OpenAIRateLimits()
        expect(limits.remaining_requests).toBeNull()
        expect(limits.remaining_tokens).toBeNull()
        expect(limits.limit_requests).toBeNull()
        expect(limits.limit_tokens).toBeNull()
        expect(limits.reset_requests).toBeNull()
        expect(limits.reset_tokens).toBeNull()
        expect(limits.reset_requests_seconds).toBeNull()
        expect(limits.reset_tokens_seconds).toBeNull()
        return
      }
      if (testName === 'test_all_fields') {
        const limits = new OpenAIRateLimits({
          remaining_requests: 100,
          remaining_tokens: 50000,
          limit_requests: 1000,
          limit_tokens: 100000,
          reset_requests: '6m30s',
          reset_requests_seconds: 390,
          reset_tokens: '1h',
          reset_tokens_seconds: 3600,
        })
        expect(limits.remaining_requests).toBe(100)
        expect(limits.reset_requests).toBe('6m30s')
        expect(limits.reset_requests_seconds).toBe(390)
        return
      }
      if (testName === 'test_is_limited_false') {
        expect(new OpenAIRateLimits({ remaining_requests: 100, remaining_tokens: 50000 }).is_limited()).toBe(false)
        return
      }
      if (testName === 'test_is_limited_true_requests') {
        expect(new OpenAIRateLimits({ remaining_requests: 0 }).is_limited()).toBe(true)
        return
      }
      if (testName === 'test_is_limited_true_tokens') {
        expect(new OpenAIRateLimits({ remaining_tokens: 0 }).is_limited()).toBe(true)
        return
      }
      if (testName === 'test_get_seconds_until_reset') {
        expect(new OpenAIRateLimits({ reset_requests_seconds: 390, reset_tokens_seconds: 3600 }).get_seconds_until_reset()).toBe(390)
        return
      }

      expect(new OpenAIRateLimits().get_seconds_until_reset()).toBeNull()
      return
    }

    if (group === 'TestExtractOpenAIRateLimits') {
      const extractOpenAIRateLimits = requireFunctionExport('extract_openai_rate_limits')
      if (testName === 'test_empty_headers') {
        const result = extractOpenAIRateLimits({})
        expect(result.remaining_requests).toBeNull()
        return
      }
      if (testName === 'test_basic_headers') {
        const result = extractOpenAIRateLimits({
          'x-ratelimit-remaining-requests': '100',
          'x-ratelimit-remaining-tokens': '50000',
          'x-ratelimit-limit-requests': '1000',
          'x-ratelimit-limit-tokens': '100000',
        })
        expect(result.remaining_requests).toBe(100)
        expect(result.remaining_tokens).toBe(50000)
        expect(result.limit_requests).toBe(1000)
        expect(result.limit_tokens).toBe(100000)
        return
      }
      if (testName === 'test_reset_duration_minutes_seconds') {
        const result = extractOpenAIRateLimits({ 'x-ratelimit-reset-requests': '6m30s' })
        expect(result.reset_requests).toBe('6m30s')
        expect(result.reset_requests_seconds).toBe(390)
        return
      }
      if (testName === 'test_reset_duration_hours') {
        const result = extractOpenAIRateLimits({ 'x-ratelimit-reset-tokens': '1h' })
        expect(result.reset_tokens).toBe('1h')
        expect(result.reset_tokens_seconds).toBe(3600)
        return
      }
      if (testName === 'test_reset_duration_complex') {
        const result = extractOpenAIRateLimits({ 'x-ratelimit-reset-requests': '1h30m45s' })
        expect(result.reset_requests_seconds).toBe(5445)
        return
      }
      if (testName === 'test_reset_duration_milliseconds') {
        const result = extractOpenAIRateLimits({ 'x-ratelimit-reset-requests': '500ms' })
        expect(result.reset_requests_seconds).toBe(1)
        return
      }
      if (testName === 'test_reset_duration_seconds_only') {
        const result = extractOpenAIRateLimits({ 'x-ratelimit-reset-requests': '45s' })
        expect(result.reset_requests_seconds).toBe(45)
        return
      }

      const result = extractOpenAIRateLimits({ 'x-ratelimit-remaining-requests': 'not-a-number' })
      expect(result.remaining_requests).toBeNull()
      return
    }

    if (testName === 'test_extract_from_ratelimitinfo_raw_headers') {
      const extractCerebrasRateLimits = requireFunctionExport('extract_cerebras_rate_limits')
      const rateLimit = extractRateLimitInfo({
        'x-ratelimit-remaining-requests': '100',
        'x-ratelimit-remaining-tokens': '50000',
        'x-ratelimit-remaining-requests-minute': '10',
        'x-ratelimit-remaining-tokens-day': '500000',
      })

      expect(rateLimit.remaining_requests).toBe(100)
      expect(rateLimit.remaining_tokens).toBe(50000)

      const cerebras = extractCerebrasRateLimits(rateLimit.raw_headers)
      expect(cerebras.remaining_requests_minute).toBe(10)
      expect(cerebras.remaining_tokens_day).toBe(500000)
      return
    }

    if (testName === 'test_all_extractors_handle_empty') {
      const extractCerebrasRateLimits = requireFunctionExport('extract_cerebras_rate_limits')
      const extractAnthropicRateLimits = requireFunctionExport('extract_anthropic_rate_limits')
      const extractOpenAIRateLimits = requireFunctionExport('extract_openai_rate_limits')

      expect(extractCerebrasRateLimits({}).is_limited()).toBe(false)
      expect(extractAnthropicRateLimits({}).is_limited()).toBe(false)
      expect(extractOpenAIRateLimits({}).is_limited()).toBe(false)
      return
    }

    const extractCerebrasRateLimits = requireFunctionExport('extract_cerebras_rate_limits')
    const extractOpenAIRateLimits = requireFunctionExport('extract_openai_rate_limits')
    const anthropicHeaders = {
      'anthropic-ratelimit-requests-remaining': '100',
    }
    expect(extractCerebrasRateLimits(anthropicHeaders).remaining_requests_minute).toBeNull()
    expect(extractOpenAIRateLimits(anthropicHeaders).remaining_requests).toBeNull()
  })
})

describe('integration metrics parity', () => {
  const INTEGRATION_METRIC_CASES = [
    'MetricsTestSuite.test_agent_monitor_basic',
    'MetricsTestSuite.test_agent_monitor_with_metrics',
    'MetricsTestSuite.test_track_operation',
    'MetricsTestSuite.test_track_operation_error',
  ] as const

  it.each(INTEGRATION_METRIC_CASES)('%s', async (caseName) => {
    if (caseName === 'MetricsTestSuite.test_agent_monitor_basic') {
      const monitor = new AgentMonitor('test-basic')
      monitor.start()
      vi.setSystemTime(new Date(METRIC_NOW.getTime() + 11))
      monitor.end()
      expect(monitor.agentId).toBe('test-basic')
      return
    }

    if (caseName === 'MetricsTestSuite.test_agent_monitor_with_metrics') {
      const monitor = new AgentMonitor('test-custom')
      monitor.start()
      monitor.metrics.tokens = 500
      monitor.metrics.cost = 0.01
      vi.setSystemTime(new Date(METRIC_NOW.getTime() + 11))
      monitor.end()

      expect(monitor.metrics.tokens).toBe(500)
      expect(monitor.metrics.cost).toBe(0.01)
      return
    }

    if (caseName === 'MetricsTestSuite.test_track_operation') {
      const result = await trackOperation('test-op', async () => {
        vi.setSystemTime(new Date(METRIC_NOW.getTime() + 20))
        return 'ok'
      })
      expect(result).toBe('ok')
      return
    }

    await expect(trackOperation('test-error-op', async () => {
      throw new Error('test error')
    })).rejects.toThrow('test error')
  })
})

import { describe, expect, it } from 'vitest'
import { mkdtempSync, rmSync } from 'node:fs'
import { join } from 'node:path'
import { tmpdir } from 'node:os'

import { FlatMachine } from '@memgrafter/flatmachines'
import { StructuredExtractor } from '@memgrafter/flatagents'
import { CheckpointManager, MemoryBackend } from '@memgrafter/flatmachines'
import {
  MemoryWorkBackend,
  SQLiteWorkBackend,
  createWorkBackend,
} from '@memgrafter/flatmachines'
import * as distributedModule from '@memgrafter/flatmachines'
import * as sdkIndex from '@memgrafter/flatmachines'
import { ClaudeCodeExecutor } from '@memgrafter/flatmachines'

const minimalMachineConfig = {
  spec: 'flatmachine' as const,
  spec_version: '0.1.0',
  data: {
    name: 'test',
    states: {
      start: { type: 'initial' as const, transitions: [{ to: 'end' }] },
      end: { type: 'final' as const, output: {} },
    },
  },
}

const renderViaMachine = (template: string, vars: Record<string, any>) => {
  const machine = new FlatMachine({ config: minimalMachineConfig }) as any
  return machine.render(template, vars)
}

const extractStructured = (content: any) => {
  const extractor = new StructuredExtractor()
  return extractor.extract(content)
}

const createThrottle = (config: Record<string, any> = {}, settings: Record<string, any> = {}) => {
  const executor = new ClaudeCodeExecutor(config, process.cwd(), settings) as any
  return executor.throttle as any
}

describe('type preservation parity', () => {
  it('TestPathReferences.test_path_reference_list', () => {
    const result = renderViaMachine('output.items', { output: { items: ['a', 'b', 'c'] } })
    expect(result).toEqual(['a', 'b', 'c'])
    expect(Array.isArray(result)).toBe(true)
  })

  it('TestPathReferences.test_path_reference_dict', () => {
    const result = renderViaMachine('output.data', { output: { data: { key: 'value', num: 42 } } })
    expect(result).toEqual({ key: 'value', num: 42 })
    expect(typeof result).toBe('object')
  })

  it('TestPathReferences.test_path_reference_nested', () => {
    const result = renderViaMachine('context.user.name', { context: { user: { name: 'Alice' } } })
    expect(result).toBe('Alice')
  })

  it('TestPathReferences.test_path_reference_boolean', () => {
    const result = renderViaMachine('output.flag', { output: { flag: true } })
    expect(result).toBe(true)
    expect(typeof result).toBe('boolean')
  })

  it('TestPathReferences.test_path_reference_none', () => {
    const result = renderViaMachine('output.value', { output: { value: null } })
    expect(result).toBeNull()
  })

  it('TestPathReferences.test_path_reference_with_whitespace', () => {
    const result = renderViaMachine('  output.items  ', { output: { items: [1, 2, 3] } })
    expect(result).toEqual([1, 2, 3])
  })

  it('TestPathReferences.test_context_path_reference', () => {
    const result = renderViaMachine('context.chapters', { context: { chapters: ['ch1', 'ch2'] } })
    expect(result).toEqual(['ch1', 'ch2'])
  })

  it('TestPathReferences.test_input_path_reference', () => {
    const result = renderViaMachine('input.query', { input: { query: 'test' } })
    expect(result).toBe('test')
  })

  it('TestPathReferences.test_missing_path_returns_none', () => {
    const result = renderViaMachine('output.nonexistent', { output: { other: 'value' } })
    expect(result).toBeNull()
  })

  it('TestJinja2StillWorks.test_jinja2_string_interpolation', () => {
    const result = renderViaMachine('Hello {{ context.name }}!', { context: { name: 'Alice' } })
    expect(result).toBe('Hello Alice!')
  })

  it('TestJinja2StillWorks.test_jinja2_with_tojson', () => {
    const result = renderViaMachine('{{ context.chapters | tojson }}', { context: { chapters: ['a', 'b'] } })
    expect(result).toBe('["a", "b"]')
    expect(typeof result).toBe('string')
    expect(JSON.parse(result)).toEqual(['a', 'b'])
  })

  it('TestJinja2StillWorks.test_jinja2_list_without_tojson', () => {
    const result = renderViaMachine('{{ context.my_list }}', { context: { my_list: ['a', 'b'] } })
    expect(typeof result).toBe('string')
    expect(JSON.parse(result)).toEqual(['a', 'b'])
  })

  it('TestJinja2StillWorks.test_jinja2_dict_without_tojson', () => {
    const result = renderViaMachine('{{ context.data }}', { context: { data: { key: 'value', num: 42 } } })
    expect(typeof result).toBe('string')
    expect(JSON.parse(result)).toEqual({ key: 'value', num: 42 })
  })

  it('TestJinja2StillWorks.test_jinja2_nested_list_without_tojson', () => {
    const result = renderViaMachine('{{ context.nested }}', { context: { nested: [['a', 'b'], ['c', 'd']] } })
    expect(typeof result).toBe('string')
    expect(JSON.parse(result)).toEqual([['a', 'b'], ['c', 'd']])
  })

  it('TestJinja2StillWorks.test_jinja2_filter_expression', () => {
    const result = renderViaMachine('{{ context.name | upper }}', { context: { name: 'alice' } })
    expect(result).toBe('ALICE')
  })

  it('TestJinja2StillWorks.test_jinja2_conditional', () => {
    const result = renderViaMachine('{% if context.active %}yes{% else %}no{% endif %}', {
      context: { active: true },
    })
    expect(result).toBe('yes')
  })

  it('TestJinja2StillWorks.test_plain_string_unchanged', () => {
    const result = renderViaMachine('hello world', {})
    expect(result).toBe('hello world')
  })

  it('TestJinja2StillWorks.test_non_path_string_unchanged', () => {
    const result = renderViaMachine('some.random.text', {})
    expect(result).toBe('some.random.text')
  })

  it('TestSerializationWarnings.test_safe_serialize_warns_with_field_name', () => {
    const manager = new CheckpointManager(new MemoryBackend()) as any
    const result = manager._safe_serialize({ good: 'value', timestamp: new Date() })
    const parsed = JSON.parse(result)
    expect(parsed.good).toBe('value')
    expect(parsed.timestamp).toBeDefined()
  })

  it('TestSerializationWarnings.test_safe_serialize_nested_non_serializable', () => {
    const manager = new CheckpointManager(new MemoryBackend()) as any
    const result = manager._safe_serialize({ wrapper: { nested_time: new Date() } })
    const parsed = JSON.parse(result)
    expect(parsed.wrapper).toBeDefined()
    expect(parsed.wrapper.nested_time).toBeDefined()
  })

  it('TestSerializationWarnings.test_safe_serialize_list_with_non_serializable', () => {
    const manager = new CheckpointManager(new MemoryBackend()) as any
    const result = manager._safe_serialize({ items: ['good', new Date(), 'also_good'] })
    const parsed = JSON.parse(result)
    expect(parsed.items).toHaveLength(3)
    expect(parsed.items[0]).toBe('good')
    expect(parsed.items[2]).toBe('also_good')
  })

  it('TestSerializationWarnings.test_safe_serialize_all_good_no_warning', () => {
    const manager = new CheckpointManager(new MemoryBackend()) as any
    const data = { string: 'value', number: 42, list: [1, 2, 3], nested: { a: 'b' } }
    const result = manager._safe_serialize(data)
    expect(JSON.parse(result)).toEqual(data)
  })

  it('TestSerializationWarnings.test_safe_serialize_multiple_bad_fields', () => {
    const manager = new CheckpointManager(new MemoryBackend()) as any
    class CustomObj {}
    const result = manager._safe_serialize({ time1: new Date(), good: 'value', custom: new CustomObj() })
    const parsed = JSON.parse(result)
    expect(parsed.good).toBe('value')
    expect(parsed.time1).toBeDefined()
    expect(parsed.custom).toBeDefined()
  })

  it('TestMarkdownStripping.test_strip_json_fence', () => {
    const result = extractStructured('```json\n{"key": "value"}\n```')
    expect(result).toEqual({ key: 'value' })
    expect(JSON.parse(JSON.stringify(result))).toEqual({ key: 'value' })
  })

  it('TestMarkdownStripping.test_strip_json_fence_uppercase', () => {
    const result = extractStructured('```JSON\n{"key": "value"}\n```')
    expect(result).toEqual({ key: 'value' })
  })

  it('TestMarkdownStripping.test_strip_plain_fence', () => {
    const result = extractStructured('```\n{"key": "value"}\n```')
    expect(result).toEqual({ key: 'value' })
  })

  it('TestMarkdownStripping.test_no_fence_unchanged', () => {
    const result = extractStructured('{"key": "value"}')
    expect(result).toEqual({ key: 'value' })
  })

  it('TestMarkdownStripping.test_whitespace_handling', () => {
    const result = extractStructured('  ```json\n{"key": "value"}\n```  ')
    expect(result).toEqual({ key: 'value' })
  })

  it('TestMarkdownStripping.test_empty_content', () => {
    expect(extractStructured('')).toBe('')
    expect(extractStructured(null)).toBeNull()
  })

  it('TestMarkdownStripping.test_complex_json', () => {
    const jsonContent = '{"items": ["a", "b"], "nested": {"x": 1}}'
    const content = `\`\`\`json\n${jsonContent}\n\`\`\``
    const result = extractStructured(content)
    expect(result).toEqual({ items: ['a', 'b'], nested: { x: 1 } })
  })

  it('TestMarkdownStripping.test_text_before_fence', () => {
    const content = 'I will search for other potential hook-related files...\n```json\n{"action": "rg", "pattern": "hook"}\n```'
    const result = extractStructured(content)
    expect(result).toEqual({ action: 'rg', pattern: 'hook' })
  })

  it('TestMarkdownStripping.test_text_after_fence', () => {
    const content = '```json\n{"key": "value"}\n```\nLet me know if you need anything else.'
    const result = extractStructured(content)
    expect(result).toEqual({ key: 'value' })
  })

  it('TestMarkdownStripping.test_raw_json_no_fence', () => {
    const content = 'Here is the result: {"status": "ok"}'
    const result = extractStructured(content)
    expect(result).toEqual({ status: 'ok' })
  })

  it('TestMarkdownStripping.test_raw_json_array', () => {
    const content = 'The items are: [1, 2, 3]'
    const result = extractStructured(content)
    expect(result).toEqual([1, 2, 3])
  })
})

describe('work pool parity', () => {
  const createSqlitePath = () => {
    const dir = mkdtempSync(join(tmpdir(), 'misc-runtime-work-'))
    return { dir, dbPath: join(dir, 'test_work.sqlite') }
  }

  const forEachPool = async (run: (pool: any) => Promise<void>) => {
    const memoryBackend = new MemoryWorkBackend()
    await run(memoryBackend.pool('test-pool'))

    const { dir, dbPath } = createSqlitePath()
    try {
      const sqliteBackend = new SQLiteWorkBackend(dbPath)
      try {
        await run(sqliteBackend.pool('test-pool'))
      } finally {
        sqliteBackend.close()
      }
    } finally {
      rmSync(dir, { recursive: true, force: true })
    }
  }

  it('TestPoolOperations.test_push_returns_id', async () => {
    await forEachPool(async (pool) => {
      const itemId = await pool.push({ task: 'hello' })
      expect(typeof itemId).toBe('string')
      expect(itemId.length).toBeGreaterThan(0)
    })
  })

  it('TestPoolOperations.test_push_and_claim', async () => {
    await forEachPool(async (pool) => {
      await pool.push({ task: 'hello' })
      const claimed = await pool.claim('worker-1')
      expect(claimed).not.toBeNull()
      expect(claimed.data).toEqual({ task: 'hello' })
    })
  })

  it('TestPoolOperations.test_claim_empty_returns_none', async () => {
    await forEachPool(async (pool) => {
      expect(await pool.claim('worker-1')).toBeNull()
    })
  })

  it('TestPoolOperations.test_complete_removes_item', async () => {
    await forEachPool(async (pool) => {
      await pool.push({ task: 'hello' })
      const claimed = await pool.claim('worker-1')
      await pool.complete(claimed.id)
      expect(await pool.size()).toBe(0)
    })
  })

  it('TestPoolOperations.test_fail_returns_to_pending', async () => {
    await forEachPool(async (pool) => {
      await pool.push({ task: 'hello' }, { max_retries: 3 })
      const claimed = await pool.claim('worker-1')
      await pool.fail(claimed.id, 'oops')
      expect(await pool.size()).toBe(1)
    })
  })

  it('TestPoolOperations.test_fail_poisons_after_max_retries', async () => {
    await forEachPool(async (pool) => {
      await pool.push({ task: 'hello' }, { max_retries: 1 })
      const claimed = await pool.claim('worker-1')
      await pool.fail(claimed.id, 'oops')
      const claimed2 = await pool.claim('worker-1')
      if (claimed2) {
        await pool.fail(claimed2.id, 'oops again')
      }
      expect(await pool.size()).toBe(0)
    })
  })

  it('TestPoolOperations.test_size_counts_pending_only', async () => {
    await forEachPool(async (pool) => {
      await pool.push({ a: 1 })
      await pool.push({ b: 2 })
      expect(await pool.size()).toBe(2)
      await pool.claim('worker-1')
      expect(await pool.size()).toBe(1)
    })
  })

  it('TestPoolOperations.test_release_by_worker', async () => {
    await forEachPool(async (pool) => {
      await pool.push({ a: 1 })
      await pool.push({ b: 2 })
      await pool.claim('worker-1')
      await pool.claim('worker-1')
      expect(await pool.size()).toBe(0)
      const released = await pool.releaseByWorker('worker-1')
      expect(released).toBe(2)
      expect(await pool.size()).toBe(2)
    })
  })

  it('TestNamedPools.test_separate_pools', async () => {
    const backend = new MemoryWorkBackend()
    const poolA = backend.pool('alpha')
    const poolB = backend.pool('beta')

    await poolA.push({ in: 'alpha' })
    expect(await poolA.size()).toBe(1)
    expect(await poolB.size()).toBe(0)
  })

  it('TestFactory.test_create_memory', () => {
    const backend = createWorkBackend('memory')
    expect(backend).toBeDefined()
  })

  it('TestFactory.test_create_sqlite', () => {
    const { dir, dbPath } = createSqlitePath()
    try {
      const backend = createWorkBackend('sqlite', { db_path: dbPath })
      expect(backend).toBeDefined()
      ;(backend as any).close?.()
    } finally {
      rmSync(dir, { recursive: true, force: true })
    }
  })

  it('TestBackwardCompat.test_distributed_reexports_work_pool', () => {
    expect((distributedModule as any).WorkPool).toBe(sdkIndex.WorkPool)
  })

  it('TestBackwardCompat.test_distributed_reexports_work_backend', () => {
    expect((distributedModule as any).WorkBackend).toBe(sdkIndex.WorkBackend)
  })

  it('TestBackwardCompat.test_distributed_reexports_work_item', () => {
    expect((distributedModule as any).WorkItem).toBe(sdkIndex.WorkItem)
  })

  it('TestBackwardCompat.test_distributed_reexports_memory_work_backend', () => {
    expect((distributedModule as any).MemoryWorkBackend).toBe(sdkIndex.MemoryWorkBackend)
  })

  it('TestBackwardCompat.test_distributed_reexports_sqlite_work_backend', () => {
    expect((distributedModule as any).SQLiteWorkBackend).toBe(sdkIndex.SQLiteWorkBackend)
  })

  it('TestBackwardCompat.test_init_reexports', () => {
    expect(sdkIndex.WorkPool).toBeDefined()
    expect(sdkIndex.WorkItem).toBeDefined()
    expect(sdkIndex.WorkBackend).toBeDefined()
  })
})

describe('call throttle parity', () => {
  it('TestCallThrottle.test_disabled_by_default', () => {
    const throttle = createThrottle({ rate_limit_delay: 0, rate_limit_jitter: 0 })
    expect(throttle.enabled).toBe(false)
  })

  it('TestCallThrottle.test_enabled_with_delay', () => {
    const throttle = createThrottle({ rate_limit_delay: 1.0, rate_limit_jitter: 0.0 })
    expect(throttle.enabled).toBe(true)
  })

  it('TestCallThrottle.test_enabled_with_jitter_only', () => {
    const throttle = createThrottle({ rate_limit_delay: 0.0, rate_limit_jitter: 1.0 })
    expect(throttle.enabled).toBe(true)
  })

  it('TestCallThrottle.test_first_call_no_wait', async () => {
    const throttle = createThrottle({ rate_limit_delay: 100.0, rate_limit_jitter: 0.0 })
    const waited = await throttle.wait()
    expect(waited).toBe(0.0)
  })

  it('TestCallThrottle.test_disabled_always_zero', async () => {
    const throttle = createThrottle({ rate_limit_delay: 0.0, rate_limit_jitter: 0.0 })
    const w1 = await throttle.wait()
    const w2 = await throttle.wait()
    const w3 = await throttle.wait()
    expect(w1).toBe(0.0)
    expect(w2).toBe(0.0)
    expect(w3).toBe(0.0)
  })

  it('TestCallThrottle.test_second_call_waits', async () => {
    const throttle = createThrottle({ rate_limit_delay: 50, rate_limit_jitter: 0.0 })
    await throttle.wait()
    const start = Date.now()
    const waited = await throttle.wait()
    const elapsed = Date.now() - start
    expect(waited).toBeGreaterThan(0.0)
    expect(elapsed).toBeGreaterThanOrEqual(40)
  })

  it('TestCallThrottle.test_jitter_adds_randomness', async () => {
    const throttle = createThrottle({ rate_limit_delay: 10, rate_limit_jitter: 10 })
    const waits: number[] = []

    await throttle.wait()
    for (let i = 0; i < 10; i += 1) {
      throttle._last_call = Date.now()
      waits.push(await throttle.wait())
    }

    const unique = new Set(waits.map((w) => Number(w.toFixed(4))))
    expect(unique.size).toBeGreaterThan(1)
  })

  it('TestCallThrottle.test_jitter_range', async () => {
    const jitter = 0.005
    const throttle = createThrottle({ rate_limit_delay: 0.0, rate_limit_jitter: jitter })
    await throttle.wait()

    const waits: number[] = []
    for (let i = 0; i < 50; i += 1) {
      throttle._last_call = Date.now()
      waits.push(await throttle.wait())
    }

    for (const wait of waits) {
      expect(wait).toBeLessThanOrEqual(0.015)
    }
  })

  it('TestCallThrottle.test_reset', async () => {
    const throttle = createThrottle({ rate_limit_delay: 100.0, rate_limit_jitter: 0.0 })
    await throttle.wait()
    throttle.reset()
    const start = Date.now()
    await throttle.wait()
    const elapsed = Date.now() - start
    expect(elapsed).toBeLessThan(50)
  })

  it('TestCallThrottle.test_negative_values_clamped', () => {
    const throttle = createThrottle({ rate_limit_delay: -5.0, rate_limit_jitter: -3.0 })
    expect(throttle.enabled).toBe(false)
  })

  it('TestSerialisedGate.test_concurrent_calls_stagger', async () => {
    const throttle = createThrottle({ rate_limit_delay: 50, rate_limit_jitter: 0.0 })
    const timestamps: Array<[number, number]> = []

    const call = async (idx: number) => {
      await throttle.wait()
      timestamps.push([idx, Date.now()])
    }

    await Promise.all([call(0), call(1), call(2)])

    timestamps.sort((a, b) => a[1] - b[1])
    expect(timestamps).toHaveLength(3)

    const gap01 = timestamps[1][1] - timestamps[0][1]
    const gap12 = timestamps[2][1] - timestamps[1][1]

    expect(gap01).toBeGreaterThanOrEqual(30)
    expect(gap12).toBeGreaterThanOrEqual(30)
  })

  it('TestThrottleFromConfig.test_empty_config', () => {
    const throttle = createThrottle({})
    expect(throttle.enabled).toBe(false)
  })

  it('TestThrottleFromConfig.test_delay_only', () => {
    const throttle = createThrottle({ rate_limit_delay: 3.0 })
    expect(throttle._delay).toBe(3.0)
    expect(throttle._jitter).toBe(0.0)
    expect(throttle.enabled).toBe(true)
  })

  it('TestThrottleFromConfig.test_both', () => {
    const throttle = createThrottle({ rate_limit_delay: 3.0, rate_limit_jitter: 4.0 })
    expect(throttle._delay).toBe(3.0)
    expect(throttle._jitter).toBe(4.0)
    expect(throttle.enabled).toBe(true)
  })

  it('TestThrottleFromConfig.test_string_values', () => {
    const throttle = createThrottle({ rate_limit_delay: '2.5', rate_limit_jitter: '1.5' })
    expect(throttle._delay).toBe(2.5)
    expect(throttle._jitter).toBe(1.5)
  })

  it('TestThrottleFromConfig.test_zero_disabled', () => {
    const throttle = createThrottle({ rate_limit_delay: 0, rate_limit_jitter: 0 })
    expect(throttle.enabled).toBe(false)
  })
})

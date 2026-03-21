import { EventEmitter } from 'node:events'
import type { ChildProcess } from 'node:child_process'
import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { describe, expect, it, vi } from 'vitest'

const spawnMock = vi.hoisted(() => vi.fn())
vi.mock('node:child_process', async () => {
  const actual = await vi.importActual<typeof import('node:child_process')>('node:child_process')
  return { ...actual, spawn: spawnMock }
})

import { AgentAdapterRegistry } from '../../src/agents'
import { ClaudeCodeAdapter, ClaudeCodeExecutor } from '../../src/adapters/claude_code_adapter'

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)
const PY_FIXTURES = resolve(__dirname, '../../../python/tests/fixtures/claude_code')

type SpawnPlan = {
  lines?: string[]
  stderr?: string
  exitCode?: number
  holdOpen?: boolean
  emitError?: Error
}

type SpawnCall = {
  bin: string
  args: string[]
  options: Record<string, unknown>
  process: StubProcess
}

class StubProcess extends EventEmitter {
  stdout = new EventEmitter()
  stderr = new EventEmitter()
  killSignals: string[] = []
  private ended = false

  constructor(private readonly plan: SpawnPlan) {
    super()
  }

  start(): void {
    setTimeout(() => {
      if (this.plan.emitError) {
        this.emit('error', this.plan.emitError)
        return
      }

      if (!this.plan.holdOpen) {
        const payload = ((this.plan.lines ?? []).join('\n') + ((this.plan.lines ?? []).length ? '\n' : ''))
        if (payload) this.stdout.emit('data', Buffer.from(payload, 'utf-8'))
        if (this.plan.stderr) this.stderr.emit('data', Buffer.from(this.plan.stderr, 'utf-8'))
        this.ended = true
        this.emit('exit', this.plan.exitCode ?? 0)
      }
    }, 0)
  }

  kill(signal?: NodeJS.Signals | number): boolean {
    this.killSignals.push(String(signal ?? 'SIGTERM'))
    if (this.ended) return true

    setTimeout(() => {
      if (this.plan.stderr) this.stderr.emit('data', Buffer.from(this.plan.stderr, 'utf-8'))
      this.ended = true
      this.emit('exit', this.plan.exitCode ?? 0)
    }, 0)

    return true
  }
}

async function withSpawnSequence<T>(plans: SpawnPlan[], run: (ctx: { calls: SpawnCall[] }) => Promise<T>): Promise<T> {
  const queue = [...plans]
  const calls: SpawnCall[] = []

  spawnMock.mockImplementation((bin: unknown, args: unknown, options: unknown) => {
    const plan = queue.shift() ?? {}
    const proc = new StubProcess(plan)
    calls.push({
      bin: String(bin),
      args: Array.isArray(args) ? args.map(String) : [],
      options: (options ?? {}) as Record<string, unknown>,
      process: proc,
    })
    proc.start()
    return proc as unknown as ChildProcess
  })

  try {
    return await run({ calls })
  } finally {
    spawnMock.mockReset()
  }
}

const loadFixtureLines = (name: string): string[] =>
  readFileSync(resolve(PY_FIXTURES, name), 'utf-8').split('\n').map((line) => line.trim()).filter(Boolean)

const createExecutor = (config: Record<string, unknown> = {}, settings: Record<string, unknown> = {}) =>
  new ClaudeCodeExecutor(config, '/tmp/test', settings)

const createFastExecutor = (config: Record<string, unknown> = {}, settings: Record<string, unknown> = {}) =>
  new ClaudeCodeExecutor({ rate_limit_delay: 0, rate_limit_jitter: 0, ...config }, '/tmp/test', settings)

const buildArgs = (
  executor: ClaudeCodeExecutor,
  task = 'task',
  sessionId = 'sid',
  resume = false,
  forkSession?: boolean,
): string[] => (executor as any).buildArgs(task, sessionId, resume, forkSession)

const invokeOnce = async (
  executor: ClaudeCodeExecutor,
  task: string,
  sessionId: string,
  resume: boolean,
  context?: Record<string, unknown>,
  forkSession?: boolean,
) => (executor as any).invokeOnce(task, sessionId, resume, context, forkSession)

const makeResultLine = (overrides: Record<string, unknown> = {}) => JSON.stringify({
  type: 'result',
  subtype: 'success',
  is_error: false,
  duration_ms: 100,
  duration_api_ms: 90,
  num_turns: 1,
  result: 'ok',
  stop_reason: 'end_turn',
  session_id: 'sid-1',
  total_cost_usd: 0.01,
  usage: {
    input_tokens: 10,
    output_tokens: 5,
    cache_creation_input_tokens: 100,
    cache_read_input_tokens: 200,
  },
  ...overrides,
})

const makeSessionResult = (overrides: Record<string, unknown> = {}) => ({
  output: { result: 'ok', session_id: 'test-session' },
  content: 'ok',
  usage: {
    input_tokens: 10,
    output_tokens: 5,
    cache_read_tokens: 9000,
    cache_write_tokens: 20,
  },
  cost: 0.01,
  finish_reason: 'stop',
  error: null,
  metadata: {
    session_id: 'test-session',
    num_turns: 1,
    stream_events: [],
  },
  ...overrides,
})

const importClaudeCodeSessions = async () =>
  (await import('../../src/adapters/claude_code_sessions')) as any

describe('claude code adapter parity', () => {
  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestBuildArgs.test_defaults', () => {
    const args = buildArgs(createExecutor(), 'do something', 'sess-1', false)
    expect(args[0]).toBe('claude')
    expect(args).toContain('-p')
    expect(args).toContain('do something')
    expect(args).toContain('--output-format')
    expect(args).toContain('stream-json')
    expect(args).toContain('--verbose')
    expect(args).toContain('--session-id')
    expect(args).toContain('sess-1')
    expect(args).toContain('--model')
    expect(args).toContain('opus')
    expect(args).toContain('--effort')
    expect(args).toContain('high')
    expect(args).not.toContain('--resume')
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestBuildArgs.test_resume_mode', () => {
    const args = buildArgs(createExecutor(), 'continue', 'sess-1', true)
    expect(args).toContain('--resume')
    expect(args).toContain('sess-1')
    expect(args).not.toContain('--session-id')
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestBuildArgs.test_custom_model', () => {
    const args = buildArgs(createExecutor({ model: 'sonnet' }), 'task', 's1', false)
    expect(args[args.indexOf('--model') + 1]).toBe('sonnet')
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestBuildArgs.test_permission_mode', () => {
    const args = buildArgs(createExecutor({ permission_mode: 'bypassPermissions' }), 'task', 's1', false)
    expect(args[args.indexOf('--permission-mode') + 1]).toBe('bypassPermissions')
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestBuildArgs.test_system_prompt', () => {
    const args = buildArgs(createExecutor({ system_prompt: 'You are a coder.' }), 'task', 's1', false)
    expect(args[args.indexOf('--system-prompt') + 1]).toBe('You are a coder.')
    expect(args).not.toContain('--append-system-prompt')
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestBuildArgs.test_append_system_prompt', () => {
    const args = buildArgs(createExecutor({ append_system_prompt: 'Also do X.' }), 'task', 's1', false)
    expect(args[args.indexOf('--append-system-prompt') + 1]).toBe('Also do X.')
    expect(args).not.toContain('--system-prompt')
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestBuildArgs.test_system_prompt_wins_over_append', () => {
    const args = buildArgs(
      createExecutor({ system_prompt: 'Full replace.', append_system_prompt: 'Should be ignored.' }),
      'task',
      's1',
      false,
    )
    expect(args).toContain('--system-prompt')
    expect(args).not.toContain('--append-system-prompt')
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestBuildArgs.test_tools_exact_whitelist', () => {
    const args = buildArgs(createExecutor({ tools: ['Bash', 'Read', 'Write'] }), 'task', 's1', false)
    const idx = args.indexOf('--tools')
    expect(args.slice(idx + 1, idx + 4)).toEqual(['Bash', 'Read', 'Write'])
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestBuildArgs.test_budget_disabled_by_default', () => {
    const args = buildArgs(createExecutor(), 'task', 's1', false)
    expect(args).not.toContain('--max-budget-usd')
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestBuildArgs.test_budget_zero_disabled', () => {
    const args = buildArgs(createExecutor({ max_budget_usd: 0 }), 'task', 's1', false)
    expect(args).not.toContain('--max-budget-usd')
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestBuildArgs.test_budget_positive', () => {
    const args = buildArgs(createExecutor({ max_budget_usd: 2.5 }), 'task', 's1', false)
    expect(args[args.indexOf('--max-budget-usd') + 1]).toBe('2.5')
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestBuildArgs.test_custom_claude_bin', () => {
    const args = buildArgs(createExecutor({ claude_bin: '/usr/local/bin/claude' }), 'task', 's1', false)
    expect(args[0]).toBe('/usr/local/bin/claude')
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestBuildArgs.test_custom_effort', () => {
    const args = buildArgs(createExecutor({ effort: 'low' }), 'task', 's1', false)
    expect(args[args.indexOf('--effort') + 1]).toBe('low')
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestBuildArgs.test_dangerously_skip_permissions', () => {
    const args = buildArgs(createExecutor({ dangerously_skip_permissions: true }), 'task', 's1', false)
    expect(args).toContain('--dangerously-skip-permissions')
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestBuildArgs.test_dangerously_skip_permissions_false', () => {
    const args = buildArgs(createExecutor({ dangerously_skip_permissions: false }), 'task', 's1', false)
    expect(args).not.toContain('--dangerously-skip-permissions')
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestBuildArgs.test_add_dirs', () => {
    const args = buildArgs(createExecutor({ add_dirs: ['/tmp/extra', '/home/user/data'] }), 'task', 's1', false)
    const idxs = args.map((arg, idx) => [arg, idx] as const).filter(([arg]) => arg === '--add-dir').map(([, idx]) => idx)
    expect(idxs).toHaveLength(2)
    expect(args[idxs[0] + 1]).toBe('/tmp/extra')
    expect(args[idxs[1] + 1]).toBe('/home/user/data')
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestBuildArgs.test_add_dirs_empty', () => {
    const args = buildArgs(createExecutor({ add_dirs: [] }), 'task', 's1', false)
    expect(args).not.toContain('--add-dir')
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestThrottleDefaults.test_default_throttle_enabled', () => {
    const executor = createExecutor()
    expect((executor as any).throttle?.enabled).toBe(true)
    expect((executor as any).throttle?._delay).toBe(3.0)
    expect((executor as any).throttle?._jitter).toBe(4.0)
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestThrottleDefaults.test_throttle_override_from_config', () => {
    const executor = createExecutor({ rate_limit_delay: 1.0, rate_limit_jitter: 0.5 })
    expect((executor as any).throttle?._delay).toBe(1.0)
    expect((executor as any).throttle?._jitter).toBe(0.5)
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestThrottleDefaults.test_throttle_disabled_via_config', () => {
    const executor = createExecutor({ rate_limit_delay: 0, rate_limit_jitter: 0 })
    expect((executor as any).throttle?.enabled).toBe(false)
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestThrottleDefaults.test_injected_throttle_wins', () => {
    const custom = { wait: vi.fn().mockResolvedValue(0), enabled: true, _delay: 99.0, _jitter: 0 }
    const executor = new (ClaudeCodeExecutor as any)({}, '/tmp/test', {}, custom)
    expect((executor as any).throttle).toBe(custom)
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestStreamCollector.test_simple_result', async () => {
    const lines = loadFixtureLines('simple_result.ndjson')
    const executor = createFastExecutor()
    const result = await withSpawnSequence([{ lines }], async () => invokeOnce(executor, '2+2', 'abc-123', false))

    expect(result.metadata?.session_id).toBe('abc-123')
    expect(result.raw?.result).toBe('2 + 2 = 4.')
    expect(result.raw?.is_error).toBe(false)
    expect(result.metadata?.stream_events).toHaveLength(3)
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestStreamCollector.test_tool_use_tracking', async () => {
    const lines = loadFixtureLines('tool_use_session.ndjson')
    const result = await withSpawnSequence([{ lines }], async () => invokeOnce(createFastExecutor(), 'edit', 'sess-tool-1', false))

    expect(result.metadata?.session_id).toBe('sess-tool-1')
    expect(result.content).toContain('<<AGENT_EXIT>>')
    expect(result.tool_calls?.map((t: any) => t.name)).toEqual(['Read', 'Edit'])
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestStreamCollector.test_get_tool_calls_from_assistant', async () => {
    const lines = loadFixtureLines('tool_use_session.ndjson')
    const result = await withSpawnSequence([{ lines }], async () => invokeOnce(createFastExecutor(), 'edit', 'sess-tool-1', false))

    expect(result.tool_calls).toBeTruthy()
    expect(result.tool_calls?.[0]?.name).toBe('Read')
    expect(result.tool_calls?.[0]?.id).toBe('toolu_001')
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestStreamCollector.test_get_tool_results_from_user', async () => {
    const lines = loadFixtureLines('tool_use_session.ndjson')
    const result = await withSpawnSequence([{ lines }], async () => invokeOnce(createFastExecutor(), 'edit', 'sess-tool-1', false))

    const toolResults = result.metadata?.tool_results
    expect(toolResults?.length).toBe(2)
    expect(toolResults?.[0]?.name).toBe('Read')
    expect(toolResults?.[0]?.content).toContain('def main')
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestStreamCollector.test_error_result', async () => {
    const lines = loadFixtureLines('error_result.ndjson')
    const result = await withSpawnSequence([{ lines }], async () => invokeOnce(createFastExecutor(), 'bad', 'sess-err-1', false))

    expect(result.raw?.is_error).toBe(true)
    expect(result.raw?.result).toContain('Rate limit')
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestMapStopReason.test_end_turn', async () => {
    const lines = loadFixtureLines('simple_result.ndjson')
    const result = await withSpawnSequence([{ lines }], async () => invokeOnce(createFastExecutor(), 'x', 'abc-123', false))
    expect(result.finish_reason).toBe('stop')
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestMapStopReason.test_max_tokens', async () => {
    const lines = [
      JSON.stringify({ type: 'system', session_id: 's1' }),
      makeResultLine({ stop_reason: 'max_tokens' }),
    ]
    const result = await withSpawnSequence([{ lines }], async () => invokeOnce(createFastExecutor(), 'x', 's1', false))
    expect(result.finish_reason).toBe('length')
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestMapStopReason.test_none', async () => {
    const lines = [
      JSON.stringify({ type: 'system', session_id: 's1' }),
      makeResultLine({ stop_reason: undefined }),
    ]
    const result = await withSpawnSequence([{ lines }], async () => invokeOnce(createFastExecutor(), 'x', 's1', false))
    expect(result.finish_reason).toBeNull()
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestMapStopReason.test_passthrough', async () => {
    const lines = [
      JSON.stringify({ type: 'system', session_id: 's1' }),
      makeResultLine({ stop_reason: 'unknown_reason' }),
    ]
    const result = await withSpawnSequence([{ lines }], async () => invokeOnce(createFastExecutor(), 'x', 's1', false))
    expect(result.finish_reason).toBe('unknown_reason')
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestResultMapping.test_simple_result_mapping', async () => {
    const result = await withSpawnSequence(
      [{ lines: loadFixtureLines('simple_result.ndjson') }],
      async () => invokeOnce(createFastExecutor(), 'task', 'abc-123', false),
    )

    expect(result.content).toBe('2 + 2 = 4.')
    expect(result.output?.result).toBe('2 + 2 = 4.')
    expect(result.output?.session_id).toBe('abc-123')
    expect(result.usage?.input_tokens).toBe(10)
    expect(result.usage?.output_tokens).toBe(8)
    expect(result.usage?.cache_read_tokens).toBe(6000)
    expect(result.usage?.cache_write_tokens).toBe(500)
    expect(result.cost).toBe(0.02)
    expect(result.finish_reason).toBe('stop')
    expect(result.error).toBeNull()
    expect(result.metadata?.session_id).toBe('abc-123')
    expect(result.metadata?.num_turns).toBe(1)
    expect(result.metadata?.duration_ms).toBe(1500)
    expect(result.metadata?.stream_events).toHaveLength(3)
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestResultMapping.test_error_result_mapping', async () => {
    const result = await withSpawnSequence(
      [{ lines: loadFixtureLines('error_result.ndjson') }],
      async () => invokeOnce(createFastExecutor(), 'task', 'sess-err-1', false),
    )

    expect(result.error).toBeTruthy()
    expect(result.error?.code).toBe('server_error')
    expect(result.error?.message).toContain('Rate limit')
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestResultMapping.test_no_truncation_of_content', async () => {
    const longText = 'A'.repeat(100_000)
    const lines = [
      JSON.stringify({ type: 'system', session_id: 'sess-long' }),
      makeResultLine({ session_id: 'sess-long', result: longText }),
    ]

    const result = await withSpawnSequence([{ lines }], async () => invokeOnce(createFastExecutor(), 'task', 'sess-long', false))
    expect(result.content).toHaveLength(100_000)
    expect(result.content).toBe(longText)
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestExecute.test_simple_invocation', async () => {
    const executor = createFastExecutor({ permission_mode: 'bypassPermissions' })
    const result = await withSpawnSequence(
      [{ lines: loadFixtureLines('simple_result.ndjson') }],
      async () => executor.execute({ task: 'what is 2+2' }),
    )

    expect(result.error).toBeNull()
    expect(result.content).toBe('2 + 2 = 4.')
    expect(result.output?.session_id).toBe('abc-123')
    expect(result.finish_reason).toBe('stop')
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestExecute.test_missing_task_returns_error', async () => {
    const result = await createFastExecutor().execute({})
    expect(result.error?.code).toBe('invalid_request')
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestExecute.test_resume_session', async () => {
    await withSpawnSequence(
      [{ lines: loadFixtureLines('simple_result.ndjson') }],
      async ({ calls }) => {
        const result = await createFastExecutor().execute({ task: 'continue', resume_session: 'existing-sess-id' })
        expect(result.error).toBeNull()
        const args = calls[0].args
        expect(args).toContain('--resume')
        expect(args).toContain('existing-sess-id')
        expect(args).not.toContain('--session-id')
      },
    )
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestExecute.test_new_session_generates_uuid', async () => {
    await withSpawnSequence(
      [{ lines: loadFixtureLines('simple_result.ndjson') }],
      async ({ calls }) => {
        await createFastExecutor().execute({ task: 'hello' })
        const args = calls[0].args
        const idx = args.indexOf('--session-id')
        expect(idx).toBeGreaterThan(-1)
        expect(args[idx + 1]).toMatch(/^[0-9a-fA-F-]{36}$/)
      },
    )
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestExecute.test_sentinel_detection', async () => {
    const result = await withSpawnSequence(
      [{ lines: loadFixtureLines('tool_use_session.ndjson') }],
      async () => createFastExecutor().execute({ task: 'edit the file' }),
    )
    expect(result.content).toContain('<<AGENT_EXIT>>')
    expect(result.error).toBeNull()
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestExecute.test_continuation_loop', async () => {
    const result = await withSpawnSequence(
      [{ lines: loadFixtureLines('needs_continuation.ndjson') }, { lines: loadFixtureLines('continuation_done.ndjson') }],
      async ({ calls }) => {
        const out = await createFastExecutor({ max_continuations: 5 }).execute({ task: 'implement feature' })
        expect(calls).toHaveLength(2)
        return out
      },
    )

    expect(result.content).toContain('<<AGENT_EXIT>>')
    expect(result.metadata?.continuation_attempts).toBe(2)
    expect(result.usage?.api_calls).toBe(2)
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestExecute.test_continuation_disabled', async () => {
    const result = await withSpawnSequence(
      [{ lines: loadFixtureLines('needs_continuation.ndjson') }],
      async () => createFastExecutor({ max_continuations: 0 }).execute({ task: 'implement feature' }),
    )

    expect(result.content ?? '').not.toContain('<<AGENT_EXIT>>')
    expect(result.metadata?.continuation_attempts).toBe(1)
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestExecute.test_continuation_limit_exhausted', async () => {
    const result = await withSpawnSequence(
      [
        { lines: loadFixtureLines('needs_continuation.ndjson') },
        { lines: loadFixtureLines('needs_continuation.ndjson') },
        { lines: loadFixtureLines('needs_continuation.ndjson') },
        { lines: loadFixtureLines('needs_continuation.ndjson') },
      ],
      async () => createFastExecutor({ max_continuations: 3 }).execute({ task: 'implement feature' }),
    )

    expect(result.metadata?.continuation_attempts).toBe(4)
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestExecute.test_continuation_prompt_used_on_resume', async () => {
    await withSpawnSequence(
      [{ lines: loadFixtureLines('needs_continuation.ndjson') }, { lines: loadFixtureLines('continuation_done.ndjson') }],
      async ({ calls }) => {
        await createFastExecutor({ max_continuations: 5 }).execute({ task: 'do stuff' })
        const secondArgs = calls[1].args
        const prompt = secondArgs[secondArgs.indexOf('-p') + 1]
        expect(prompt).toContain('<<AGENT_EXIT>>')
        expect(prompt).toContain('Continue')
        expect(secondArgs).toContain('--resume')
      },
    )
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestExecute.test_error_stops_continuation', async () => {
    const result = await withSpawnSequence(
      [{ lines: loadFixtureLines('error_result.ndjson') }],
      async () => createFastExecutor({ max_continuations: 10 }).execute({ task: 'do something' }),
    )

    expect(result.error).toBeTruthy()
    expect(result.metadata?.continuation_attempts).toBe(1)
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestExecute.test_process_failure_no_result', async () => {
    const result = await withSpawnSequence(
      [{ lines: [], exitCode: 1, stderr: 'segfault' }],
      async () => createFastExecutor().execute({ task: 'crash' }),
    )

    expect(result.error?.code).toBe('server_error')
    expect(result.error?.message).toContain('segfault')
    expect(result.metadata?.stderr).toBe('segfault')
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestExecute.test_timeout_raises', async () => {
    await withSpawnSequence(
      [{ holdOpen: true }],
      async () => {
        await expect(createFastExecutor({ timeout: 0.01 }).execute({ task: 'hang' })).rejects.toThrow(/timed out/i)
      },
    )
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestExecute.test_no_timeout_by_default', async () => {
    const result = await withSpawnSequence(
      [{ lines: loadFixtureLines('simple_result.ndjson') }],
      async () => createFastExecutor().execute({ task: 'hello' }),
    )
    expect(result.error).toBeNull()
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestExecute.test_working_dir_resolved', async () => {
    await withSpawnSequence(
      [{ lines: loadFixtureLines('simple_result.ndjson') }],
      async ({ calls }) => {
        await createFastExecutor({ working_dir: '/home/user/project' }).execute({ task: 'hello' })
        expect(calls[0].options.cwd).toBe('/home/user/project')
      },
    )
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestExecute.test_aggregated_cost', async () => {
    const result = await withSpawnSequence(
      [{ lines: loadFixtureLines('needs_continuation.ndjson') }, { lines: loadFixtureLines('continuation_done.ndjson') }],
      async () => createFastExecutor({ max_continuations: 5 }).execute({ task: 'implement' }),
    )

    expect(Number(result.cost)).toBeCloseTo(0.08, 3)
    expect(result.usage?.input_tokens).toBe(120)
    expect(result.usage?.output_tokens).toBe(90)
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestExecuteWithTools.test_raises_not_implemented', async () => {
    await expect(
      (createFastExecutor() as any).execute_with_tools({ task: 'x' }, [{ function: { name: 'bash' } }]),
    ).rejects.toThrow(/tool/i)
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestAdapter.test_type_name', () => {
    expect(new ClaudeCodeAdapter().type_name).toBe('claude-code')
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestAdapter.test_create_executor', () => {
    const adapter = new ClaudeCodeAdapter()
    const executor = adapter.create_executor({
      agent_name: 'coder',
      agent_ref: { type: 'claude-code', config: { model: 'sonnet', permission_mode: 'bypassPermissions' } },
      context: { config_dir: '/tmp/test', settings: {}, machine_name: 'test-machine' },
    }) as ClaudeCodeExecutor

    const args = buildArgs(executor, 'hello', 's1', false)
    expect(args).toContain('sonnet')
    expect(args).toContain('bypassPermissions')
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestAdapter.test_settings_merge', () => {
    const adapter = new ClaudeCodeAdapter()
    const executor = adapter.create_executor({
      agent_name: 'coder',
      agent_ref: { type: 'claude-code', config: { model: 'sonnet' } },
      context: {
        config_dir: '/tmp/test',
        settings: { agent_runners: { claude_code: { permission_mode: 'auto', claude_bin: '/opt/claude' } } },
        machine_name: 'test-machine',
      },
    }) as ClaudeCodeExecutor

    const args = buildArgs(executor, 'hello', 's1', false)
    expect(args).toContain('sonnet')
    expect(args).toContain('auto')
    expect(args[0]).toBe('/opt/claude')
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestRegistration.test_registered_in_builtins', () => {
    const registry = new AgentAdapterRegistry()
    expect(() => registry.get('claude-code')).not.toThrow()
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestUnparseableLines.test_skips_bad_json', async () => {
    const lines = [
      '{"type":"system","session_id":"s1"}',
      'THIS IS NOT JSON',
      makeResultLine({ session_id: 's1', result: 'ok' }),
    ]

    const result = await withSpawnSequence([{ lines }], async () => createFastExecutor().execute({ task: 'test' }))
    expect(result.error).toBeNull()
    expect(result.content).toBe('ok')
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestAgentMonitorMetrics.test_success_metrics', async () => {
    const result = await withSpawnSequence(
      [{ lines: loadFixtureLines('simple_result.ndjson') }],
      async () => invokeOnce(createFastExecutor(), 'what is 2+2', 's1', false),
    )

    expect(result.error).toBeNull()
    expect(result.usage?.input_tokens).toBe(10)
    expect(result.usage?.output_tokens).toBe(8)
    expect(result.usage?.cache_read_tokens).toBe(6000)
    expect(result.usage?.cache_write_tokens).toBe(500)
    expect(result.cost).toBe(0.02)
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestAgentMonitorMetrics.test_error_metrics', async () => {
    const result = await withSpawnSequence(
      [{ lines: loadFixtureLines('error_result.ndjson') }],
      async () => invokeOnce(createFastExecutor(), 'fail', 's2', false),
    )

    expect(result.error).toBeTruthy()
    expect(result.error?.type).toBe('ClaudeCodeError')
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestAgentMonitorMetrics.test_process_failure_metrics', async () => {
    const result = await withSpawnSequence(
      [{ lines: [], exitCode: 1, stderr: 'crash' }],
      async () => invokeOnce(createFastExecutor(), 'crash', 's3', false),
    )

    expect(result.error).toBeTruthy()
    expect(result.error?.type).toBe('ClaudeCodeProcessError')
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestAgentMonitorMetrics.test_monitor_agent_id_uses_model', async () => {
    const result = await withSpawnSequence(
      [{ lines: loadFixtureLines('simple_result.ndjson') }],
      async () => invokeOnce(createFastExecutor({ model: 'sonnet' }), 'hello', 's4', false),
    )

    expect(result.metadata?.monitor?.agent_id).toBe('claude-code/sonnet')
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestAgentMonitorMetrics.test_continuation_summary_log', async () => {
    const infoSpy = vi.spyOn(console, 'info').mockImplementation(() => {})
    try {
      await withSpawnSequence(
        [{ lines: loadFixtureLines('needs_continuation.ndjson') }, { lines: loadFixtureLines('continuation_done.ndjson') }],
        async () => createFastExecutor({ max_continuations: 5 }).execute({ task: 'implement' }),
      )
      expect(infoSpy.mock.calls.some((call) => String(call[0]).includes('continuation complete'))).toBe(true)
    } finally {
      infoSpy.mockRestore()
    }
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestAgentMonitorMetrics.test_no_continuation_summary_for_single', async () => {
    const infoSpy = vi.spyOn(console, 'info').mockImplementation(() => {})
    try {
      await withSpawnSequence(
        [{ lines: loadFixtureLines('simple_result.ndjson') }],
        async () => createFastExecutor().execute({ task: 'hello' }),
      )
      expect(infoSpy.mock.calls.some((call) => String(call[0]).includes('continuation complete'))).toBe(false)
    } finally {
      infoSpy.mockRestore()
    }
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestOrderedToolTracking.test_tool_calls_collected', async () => {
    const result = await withSpawnSequence(
      [{ lines: loadFixtureLines('tool_use_session.ndjson') }],
      async () => invokeOnce(createFastExecutor(), 'edit', 'sess-tool-1', false),
    )

    expect(result.tool_calls).toHaveLength(2)
    expect(result.tool_calls?.[0]?.name).toBe('Read')
    expect(result.tool_calls?.[0]?.id).toBe('toolu_001')
    expect(result.tool_calls?.[1]?.name).toBe('Edit')
    expect(result.tool_calls?.[1]?.id).toBe('toolu_002')
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestOrderedToolTracking.test_tool_results_collected', async () => {
    const result = await withSpawnSequence(
      [{ lines: loadFixtureLines('tool_use_session.ndjson') }],
      async () => invokeOnce(createFastExecutor(), 'edit', 'sess-tool-1', false),
    )

    const toolResults = result.metadata?.tool_results
    expect(toolResults).toHaveLength(2)
    expect(toolResults?.[0]?.name).toBe('Read')
    expect(toolResults?.[0]?.tool_call_id).toBe('toolu_001')
    expect(toolResults?.[0]?.content).toContain('def main')
    expect(toolResults?.[1]?.name).toBe('Edit')
    expect(toolResults?.[1]?.tool_call_id).toBe('toolu_002')
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestOrderedToolTracking.test_tool_calls_on_agent_result', async () => {
    const result = await withSpawnSequence(
      [{ lines: loadFixtureLines('tool_use_session.ndjson') }],
      async () => invokeOnce(createFastExecutor(), 'edit', 'sess-tool-1', false),
    )

    expect(result.tool_calls).toBeTruthy()
    expect(result.tool_calls?.length).toBe(2)
    expect(result.tool_calls?.[0]?.name).toBe('Read')
    expect(result.tool_calls?.[1]?.name).toBe('Edit')
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestOrderedToolTracking.test_tool_results_in_metadata', async () => {
    const result = await withSpawnSequence(
      [{ lines: loadFixtureLines('tool_use_session.ndjson') }],
      async () => invokeOnce(createFastExecutor(), 'edit', 'sess-tool-1', false),
    )

    const toolResults = result.metadata?.tool_results
    expect(toolResults).toBeTruthy()
    expect(toolResults?.length).toBe(2)
    expect(toolResults?.[0]?.name).toBe('Read')
    expect(toolResults?.[1]?.name).toBe('Edit')
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestOrderedToolTracking.test_no_tool_calls_returns_none', async () => {
    const result = await withSpawnSequence(
      [{ lines: loadFixtureLines('simple_result.ndjson') }],
      async () => invokeOnce(createFastExecutor(), 'simple', 'abc-123', false),
    )

    expect(result.tool_calls).toBeNull()
    expect(result.metadata?.tool_results).toBeNull()
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestStructuredOutput.test_structured_output_detected', async () => {
    const result = await withSpawnSequence(
      [{ lines: loadFixtureLines('structured_output.ndjson') }],
      async () => invokeOnce(createFastExecutor(), 'score', 'sess-struct-1', false),
    )

    expect(result.output?.score).toBe(9)
    expect(result.output?.summary).toBe('Excellent code quality')
    expect(result.output?.issues).toEqual([])
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestStructuredOutput.test_structured_output_in_result', async () => {
    const result = await withSpawnSequence(
      [{ lines: loadFixtureLines('structured_output.ndjson') }],
      async () => invokeOnce(createFastExecutor(), 'score', 'sess-struct-1', false),
    )

    expect(result.output?.score).toBe(9)
    expect(result.output?.summary).toBe('Excellent code quality')
    expect(result.output?.issues).toEqual([])
    expect(result.output?.session_id).toBe('sess-struct-1')
    expect(result.output?._raw_result).toBe('Here is the analysis.')
    expect(result.content).toBe('Here is the analysis.')
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestStructuredOutput.test_no_structured_output_uses_result_text', async () => {
    const result = await withSpawnSequence(
      [{ lines: loadFixtureLines('simple_result.ndjson') }],
      async () => invokeOnce(createFastExecutor(), 'simple', 'abc-123', false),
    )

    expect(result.output?.result).toBe('2 + 2 = 4.')
    expect(result.output?._raw_result).toBeUndefined()
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestRateLimitSurfacing.test_rate_limit_events_collected', async () => {
    const result = await withSpawnSequence(
      [{ lines: loadFixtureLines('rate_limit_session.ndjson') }],
      async () => invokeOnce(createFastExecutor(), 'rate', 'sess-rl-1', false),
    )

    const rlEvent = (result.metadata?.stream_events ?? []).find((event: any) => event.type === 'rate_limit_event')
    expect(rlEvent?.rate_limit_info?.requests_remaining).toBe(5)
    expect(rlEvent?.rate_limit_info?.tokens_remaining).toBe(40000)
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestRateLimitSurfacing.test_rate_limit_on_agent_result', async () => {
    const result = await withSpawnSequence(
      [{ lines: loadFixtureLines('rate_limit_session.ndjson') }],
      async () => invokeOnce(createFastExecutor(), 'rate', 'sess-rl-1', false),
    )

    expect(result.rate_limit).toBeTruthy()
    expect(result.rate_limit?.limited).toBe(false)
    expect(result.rate_limit?.retry_after).toBe(30)
    expect(result.rate_limit?.windows).toHaveLength(2)
    expect(result.rate_limit?.windows?.[0]?.name).toBe('requests')
    expect(result.rate_limit?.windows?.[0]?.remaining).toBe(5)
    expect(result.rate_limit?.windows?.[0]?.limit).toBe(50)
    expect(result.rate_limit?.windows?.[1]?.name).toBe('tokens')
    expect(result.rate_limit?.windows?.[1]?.remaining).toBe(40000)
    expect(result.rate_limit?.windows?.[1]?.limit).toBe(80000)
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestRateLimitSurfacing.test_no_rate_limit_returns_none', async () => {
    const result = await withSpawnSequence(
      [{ lines: loadFixtureLines('simple_result.ndjson') }],
      async () => invokeOnce(createFastExecutor(), 'simple', 'abc-123', false),
    )

    expect(result.rate_limit).toBeNull()
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestRateLimitSurfacing.test_rate_limit_limited_when_zero_remaining', async () => {
    const lines = [
      JSON.stringify({ type: 'system', session_id: 'sess-rl-2' }),
      JSON.stringify({
        type: 'rate_limit_event',
        rate_limit_info: {
          requests_remaining: 0,
          requests_limit: 50,
          tokens_remaining: 40000,
          tokens_limit: 80000,
        },
      }),
      makeResultLine({ session_id: 'sess-rl-2', result: 'done' }),
    ]

    const result = await withSpawnSequence([{ lines }], async () => invokeOnce(createFastExecutor(), 'rate', 'sess-rl-2', false))
    expect(result.rate_limit?.limited).toBe(true)
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestMcpConfig.test_mcp_config_arg', () => {
    const args = buildArgs(createExecutor({ mcp_config: '/path/to/mcp.json' }), 'task', 's1', false)
    expect(args[args.indexOf('--mcp-config') + 1]).toBe('/path/to/mcp.json')
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestMcpConfig.test_mcp_config_absent', () => {
    const args = buildArgs(createExecutor(), 'task', 's1', false)
    expect(args).not.toContain('--mcp-config')
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestCancel.test_cancel_no_process', async () => {
    const result = await createFastExecutor().cancel()
    expect(result).toBe(false)
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestCancel.test_cancel_running_process', async () => {
    class CancelProc extends EventEmitter {
      killed: string[] = []

      kill(signal?: NodeJS.Signals | number): boolean {
        this.killed.push(String(signal))
        setTimeout(() => this.emit('exit', 0), 0)
        return true
      }
    }

    const executor = createFastExecutor()
    const proc = new CancelProc()
    ;(executor as any).proc = proc

    const result = await executor.cancel()
    expect(result).toBe(true)
    expect(proc.killed).toContain('SIGTERM')
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestCancel.test_cancel_process_already_dead', async () => {
    const executor = createFastExecutor()
    ;(executor as any).proc = {
      kill: () => {
        throw new Error('ProcessLookupError')
      },
      once: (_event: string, _cb: () => void) => undefined,
    }

    await expect(executor.cancel()).resolves.toBe(false)
  })

  it('sdk/python/tests/unit/test_claude_code_adapter.py::TestCancel.test_process_ref_cleared_after_invocation', async () => {
    const executor = createFastExecutor()
    await withSpawnSequence(
      [{ lines: loadFixtureLines('simple_result.ndjson') }],
      async () => invokeOnce(executor, 'hello', 's1', false),
    )

    expect((executor as any).proc).toBeNull()
  })
})

describe('claude code sessions parity', () => {
  it('sdk/python/tests/unit/test_claude_code_sessions.py::TestSeed.test_seed_creates_session', async () => {
    const { SessionHoldback } = await importClaudeCodeSessions()
    const executor = createFastExecutor({ permission_mode: 'bypassPermissions' })
    const holdback = new SessionHoldback(executor)
    const invoke = vi.fn().mockResolvedValue(makeSessionResult({ usage: { input_tokens: 10, output_tokens: 5, cache_read_tokens: 0, cache_write_tokens: 3000 } }))
    ;(executor as any).invokeOnce = invoke
    ;(executor as any)._invoke_once = invoke

    const result = await holdback.seed('set up context')

    expect(result.content).toBe('ok')
    expect(holdback.session_id).toBeTruthy()
    expect(holdback._seeded).toBe(true)
  })

  it('sdk/python/tests/unit/test_claude_code_sessions.py::TestSeed.test_seed_single_call', async () => {
    const { SessionHoldback } = await importClaudeCodeSessions()
    const executor = createFastExecutor()
    const holdback = new SessionHoldback(executor)
    const invoke = vi.fn().mockResolvedValue(makeSessionResult())
    ;(executor as any).invokeOnce = invoke
    ;(executor as any)._invoke_once = invoke

    await holdback.seed('context')
    expect(invoke).toHaveBeenCalledTimes(1)
  })

  it('sdk/python/tests/unit/test_claude_code_sessions.py::TestSeed.test_seed_error_still_marks_seeded', async () => {
    const { SessionHoldback } = await importClaudeCodeSessions()
    const executor = createFastExecutor()
    const holdback = new SessionHoldback(executor)
    const invoke = vi.fn().mockResolvedValue(makeSessionResult({ error: { code: 'server_error', message: 'fail' } }))
    ;(executor as any).invokeOnce = invoke
    ;(executor as any)._invoke_once = invoke

    const result = await holdback.seed('context')
    expect(result.error).toBeTruthy()
    expect(holdback._seeded).toBe(true)
  })

  it('sdk/python/tests/unit/test_claude_code_sessions.py::TestSeed.test_seed_with_provided_session_id', async () => {
    const { SessionHoldback } = await importClaudeCodeSessions()
    const executor = createFastExecutor()
    const holdback = new SessionHoldback(executor, 'my-custom-id')
    const invoke = vi.fn().mockResolvedValue(makeSessionResult({ metadata: { session_id: 'my-custom-id', num_turns: 1, stream_events: [] } }))
    ;(executor as any).invokeOnce = invoke
    ;(executor as any)._invoke_once = invoke

    await holdback.seed('context')
    expect(holdback.session_id).toBe('my-custom-id')
  })

  it('sdk/python/tests/unit/test_claude_code_sessions.py::TestAdopt.test_adopt_sets_session', async () => {
    const { SessionHoldback } = await importClaudeCodeSessions()
    const holdback = new SessionHoldback(createFastExecutor())

    await holdback.adopt('existing-session')

    expect(holdback.session_id).toBe('existing-session')
    expect(holdback._seeded).toBe(true)
  })

  it('sdk/python/tests/unit/test_claude_code_sessions.py::TestAdopt.test_adopt_no_api_call', async () => {
    const { SessionHoldback } = await importClaudeCodeSessions()
    const executor = createFastExecutor()
    const invoke = vi.fn().mockResolvedValue(makeSessionResult())
    ;(executor as any).invokeOnce = invoke
    ;(executor as any)._invoke_once = invoke
    const holdback = new SessionHoldback(executor)

    await holdback.adopt('existing-session')
    expect(invoke).toHaveBeenCalledTimes(0)
  })

  it('sdk/python/tests/unit/test_claude_code_sessions.py::TestFork.test_fork_uses_fork_session', async () => {
    const { SessionHoldback } = await importClaudeCodeSessions()
    const executor = createFastExecutor()
    const holdback = new SessionHoldback(executor, 'parent-id')
    holdback._seeded = true

    const invoke = vi.fn().mockResolvedValue(makeSessionResult({ metadata: { session_id: 'child-id', num_turns: 1, stream_events: [] }, usage: { input_tokens: 10, output_tokens: 5, cache_read_tokens: 9500, cache_write_tokens: 20 } }))
    ;(executor as any).invokeOnce = invoke
    ;(executor as any)._invoke_once = invoke

    const fr = await holdback.fork('do work')

    expect(fr.session_id).toBe('child-id')
    expect(fr.cache_read_tokens).toBe(9500)
    expect(fr.task).toBe('do work')
    expect(holdback._fork_count).toBe(1)
  })

  it('sdk/python/tests/unit/test_claude_code_sessions.py::TestFork.test_fork_not_seeded_raises', async () => {
    const { SessionHoldback } = await importClaudeCodeSessions()
    const holdback = new SessionHoldback(createFastExecutor())
    await expect(holdback.fork('do work')).rejects.toThrow(/not seeded/i)
  })

  it('sdk/python/tests/unit/test_claude_code_sessions.py::TestFork.test_fork_accumulates_cost', async () => {
    const { SessionHoldback } = await importClaudeCodeSessions()
    const executor = createFastExecutor()
    const holdback = new SessionHoldback(executor, 'p')
    holdback._seeded = true

    const invoke = vi.fn().mockResolvedValue(makeSessionResult({ cost: 0.05 }))
    ;(executor as any).invokeOnce = invoke
    ;(executor as any)._invoke_once = invoke

    await holdback.fork('task 1')
    await holdback.fork('task 2')

    expect(holdback._total_cost).toBeCloseTo(0.1, 3)
    expect(holdback._fork_count).toBe(2)
  })

  it('sdk/python/tests/unit/test_claude_code_sessions.py::TestForkN.test_fork_n_parallel', async () => {
    const { SessionHoldback, ForkResult } = await importClaudeCodeSessions()
    const executor = createFastExecutor()
    const holdback = new SessionHoldback(executor, 'p')
    holdback._seeded = true

    let callCount = 0
    const invoke = vi.fn().mockImplementation(async () => {
      callCount += 1
      return makeSessionResult({ metadata: { session_id: `child-${callCount}`, num_turns: 1, stream_events: [] }, usage: { input_tokens: 10, output_tokens: 5, cache_read_tokens: 9500, cache_write_tokens: 20 } })
    })
    ;(executor as any).invokeOnce = invoke
    ;(executor as any)._invoke_once = invoke

    const results = await holdback.fork_n(['task a', 'task b', 'task c'])
    expect(results).toHaveLength(3)
    expect(callCount).toBe(3)
    expect(results.every((r: any) => r instanceof ForkResult)).toBe(true)
    expect(results.every((r: any) => r.cache_read_tokens === 9500)).toBe(true)
  })

  it('sdk/python/tests/unit/test_claude_code_sessions.py::TestForkN.test_fork_n_with_concurrency_limit', async () => {
    const { SessionHoldback } = await importClaudeCodeSessions()
    const executor = createFastExecutor()
    const holdback = new SessionHoldback(executor, 'p')
    holdback._seeded = true

    let maxConcurrent = 0
    let currentConcurrent = 0
    const invoke = vi.fn().mockImplementation(async () => {
      currentConcurrent += 1
      maxConcurrent = Math.max(maxConcurrent, currentConcurrent)
      await new Promise((resolve) => setTimeout(resolve, 10))
      currentConcurrent -= 1
      return makeSessionResult()
    })

    ;(executor as any).invokeOnce = invoke
    ;(executor as any)._invoke_once = invoke

    const results = await holdback.fork_n(['a', 'b', 'c', 'd', 'e'], undefined, 2)
    expect(results).toHaveLength(5)
    expect(maxConcurrent).toBeLessThanOrEqual(2)
  })

  it('sdk/python/tests/unit/test_claude_code_sessions.py::TestForkN.test_fork_n_handles_exceptions', async () => {
    const { SessionHoldback } = await importClaudeCodeSessions()
    const executor = createFastExecutor()
    const holdback = new SessionHoldback(executor, 'p')
    holdback._seeded = true

    let callCount = 0
    const invoke = vi.fn().mockImplementation(async () => {
      callCount += 1
      if (callCount === 2) throw new Error('API down')
      return makeSessionResult()
    })

    ;(executor as any).invokeOnce = invoke
    ;(executor as any)._invoke_once = invoke

    const results = await holdback.fork_n(['ok', 'fail', 'ok'])
    expect(results).toHaveLength(3)
    expect(results[0].result.error).toBeNull()
    expect(results[1].result.error).toBeTruthy()
    expect(results[1].result.error.message).toContain('API down')
    expect(results[2].result.error).toBeNull()
  })

  it('sdk/python/tests/unit/test_claude_code_sessions.py::TestForkN.test_fork_n_not_seeded_raises', async () => {
    const { SessionHoldback } = await importClaudeCodeSessions()
    const holdback = new SessionHoldback(createFastExecutor())
    await expect(holdback.fork_n(['task'])).rejects.toThrow(/not seeded/i)
  })

  it('sdk/python/tests/unit/test_claude_code_sessions.py::TestWarm.test_warm_uses_fork_session', async () => {
    const { SessionHoldback } = await importClaudeCodeSessions()
    const executor = createFastExecutor()
    const holdback = new SessionHoldback(executor, 'p')
    holdback._seeded = true

    const invoke = vi.fn().mockResolvedValue(makeSessionResult({ usage: { input_tokens: 10, output_tokens: 5, cache_read_tokens: 9500, cache_write_tokens: 20 } }))
    ;(executor as any).invokeOnce = invoke
    ;(executor as any)._invoke_once = invoke

    const result = await holdback.warm()
    expect(result.usage.cache_read_tokens).toBe(9500)
  })

  it('sdk/python/tests/unit/test_claude_code_sessions.py::TestWarm.test_warm_not_seeded_raises', async () => {
    const { SessionHoldback } = await importClaudeCodeSessions()
    const holdback = new SessionHoldback(createFastExecutor())
    await expect(holdback.warm()).rejects.toThrow(/not seeded/i)
  })

  it('sdk/python/tests/unit/test_claude_code_sessions.py::TestStats.test_initial_stats', async () => {
    const { SessionHoldback } = await importClaudeCodeSessions()
    const holdback = new SessionHoldback(createFastExecutor())
    const stats = holdback.stats

    expect(stats.session_id).toBeNull()
    expect(stats.seeded).toBe(false)
    expect(stats.fork_count).toBe(0)
    expect(stats.total_cost).toBe(0)
  })

  it('sdk/python/tests/unit/test_claude_code_sessions.py::TestBuildArgsForkSession.test_fork_session_flag', () => {
    const args = buildArgs(createExecutor(), 'task', 'sid', true, true)
    expect(args).toContain('--resume')
    expect(args).toContain('sid')
    expect(args).toContain('--fork-session')
  })

  it('sdk/python/tests/unit/test_claude_code_sessions.py::TestBuildArgsForkSession.test_no_fork_session_by_default', () => {
    const args = buildArgs(createExecutor(), 'task', 'sid', true)
    expect(args).not.toContain('--fork-session')
  })

  it('sdk/python/tests/unit/test_claude_code_sessions.py::TestBuildArgsForkSession.test_fork_session_ignored_without_resume', () => {
    const args = buildArgs(createExecutor(), 'task', 'sid', false, true)
    expect(args).not.toContain('--fork-session')
    expect(args).toContain('--session-id')
  })
})

describe('claude code live parity', () => {
  it('sdk/python/tests/integration/claude_code/test_claude_code_live.py::test_simple_task', async () => {
    const result = await withSpawnSequence(
      [{ lines: loadFixtureLines('simple_result.ndjson') }],
      async () => createFastExecutor().execute({ task: 'What is 2+2? Reply with just the number.' }),
    )

    expect(result.error).toBeNull()
    expect(result.content).toContain('4')
    expect(result.finish_reason).toBe('stop')
    expect(result.usage?.input_tokens).toBeGreaterThan(0)
    expect(result.usage?.output_tokens).toBeGreaterThan(0)
    expect(Number(result.cost)).toBeGreaterThan(0)
    expect(result.output?.session_id).toBeTruthy()
    expect(result.metadata?.num_turns).toBeDefined()
    expect(result.metadata?.duration_ms).toBeDefined()
    expect(result.metadata?.session_id).toBeTruthy()
  })

  it('sdk/python/tests/integration/claude_code/test_claude_code_live.py::test_tool_use_read_file', async () => {
    const result = await withSpawnSequence(
      [{ lines: loadFixtureLines('tool_use_session.ndjson') }],
      async () => createFastExecutor({ tools: ['Read'] }).execute({ task: 'Read hello.txt and return the magic number.' }),
    )

    expect(result.error).toBeNull()
    expect(result.content).toContain('Done')

    const events = result.metadata?.stream_events ?? []
    const types = events.map((event: any) => event.type)
    expect(types).toContain('system')
    expect(types).toContain('assistant')
    expect(types).toContain('result')

    const toolUseFound = events.some((event: any) =>
      event.type === 'assistant'
      && (event.message?.content ?? []).some((block: any) => block.type === 'tool_use' && block.name === 'Read'))
    expect(toolUseFound).toBe(true)

    const toolResultFound = events.some((event: any) =>
      event.type === 'user'
      && (event.message?.content ?? []).some((block: any) => block.type === 'tool_result'))
    expect(toolResultFound).toBe(true)
  })

  it('sdk/python/tests/integration/claude_code/test_claude_code_live.py::test_session_resume', async () => {
    const turn1 = [
      JSON.stringify({ type: 'system', session_id: 'resume-1', tools: ['Bash', 'Read'], model: 'claude-opus-4-6' }),
      makeResultLine({ session_id: 'resume-1', result: 'Acknowledged', usage: { input_tokens: 5, output_tokens: 2, cache_creation_input_tokens: 100, cache_read_input_tokens: 0 } }),
    ]
    const turn2 = [
      JSON.stringify({ type: 'system', session_id: 'resume-1', tools: ['Bash', 'Read'], model: 'claude-opus-4-6' }),
      makeResultLine({ session_id: 'resume-1', result: 'FLAMINGO-7734', usage: { input_tokens: 8, output_tokens: 4, cache_creation_input_tokens: 0, cache_read_input_tokens: 3 } }),
    ]

    await withSpawnSequence(
      [{ lines: turn1 }, { lines: turn2 }],
      async () => {
        const executor = createFastExecutor()
        const r1 = await invokeOnce(executor, 'Remember this secret code', 'resume-1', false)
        const r2 = await invokeOnce(executor, 'What was the code?', 'resume-1', true)
        expect(r1.error).toBeNull()
        expect(r2.error).toBeNull()
        expect(r2.content).toContain('FLAMINGO')
        expect((r2.usage?.cache_read_tokens ?? 0)).toBeGreaterThan(0)
      },
    )
  })

  it('sdk/python/tests/integration/claude_code/test_claude_code_live.py::test_concurrent_sessions', async () => {
    const mk = (sid: string) => [
      JSON.stringify({ type: 'system', session_id: sid, tools: ['Bash', 'Read'], model: 'claude-opus-4-6' }),
      makeResultLine({ session_id: sid, result: '30' }),
    ]

    await withSpawnSequence(
      [{ lines: mk('s1') }, { lines: mk('s2') }],
      async () => {
        const executor = createFastExecutor()
        const [r1, r2] = await Promise.all([
          executor.execute({ task: 'What is 10+20?' }),
          executor.execute({ task: 'What is 5*6?' }),
        ])
        expect(r1.error).toBeNull()
        expect(r2.error).toBeNull()
        expect(r1.content).toContain('30')
        expect(r2.content).toContain('30')
        expect(r1.output?.session_id).not.toBe(r2.output?.session_id)
      },
    )
  })

  it('sdk/python/tests/integration/claude_code/test_claude_code_live.py::test_resume_nonexistent_session', async () => {
    const result = await withSpawnSequence(
      [{ lines: loadFixtureLines('error_result.ndjson') }],
      async () => invokeOnce(createFastExecutor(), 'hello', 'bogus-id', true),
    )

    expect(result.error).toBeTruthy()
  })

  it('sdk/python/tests/integration/claude_code/test_claude_code_live.py::test_permission_bypass_headless', async () => {
    const dir = mkdtempSync(resolve(tmpdir(), 'cc-perm-'))
    const target = resolve(dir, 'perm_test.txt')
    writeFileSync(target, 'original content\n', 'utf-8')

    await withSpawnSequence(
      [{ lines: loadFixtureLines('simple_result.ndjson') }],
      async ({ calls }) => {
        await createFastExecutor({ permission_mode: 'bypassPermissions', tools: ['Bash', 'Read'], working_dir: dir }).execute({
          task: 'Run echo PERM_OK and read the file.',
        })

        const args = calls[0].args
        expect(args).toContain('--permission-mode')
        expect(args).toContain('bypassPermissions')
      },
    )
  })

  it('sdk/python/tests/integration/claude_code/test_claude_code_live.py::test_tools_exact_restriction', async () => {
    const lines = [
      JSON.stringify({ type: 'system', session_id: 'restricted', tools: ['Read'], model: 'claude-opus-4-6' }),
      makeResultLine({ session_id: 'restricted', result: 'restricted content' }),
    ]

    const result = await withSpawnSequence(
      [{ lines }],
      async () => createFastExecutor({ tools: ['Read'] }).execute({ task: 'Read restricted.txt and summarize.' }),
    )

    expect(result.error).toBeNull()
    const systemEvent = (result.metadata?.stream_events ?? []).find((event: any) => event.type === 'system')
    expect(systemEvent).toBeTruthy()
    expect(systemEvent?.tools).toContain('Read')
    const restrictedOut = new Set((systemEvent?.tools ?? []).filter((tool: string) => tool !== 'Read'))
    expect(restrictedOut.size).toBe(0)
  })

  it('sdk/python/tests/integration/claude_code/test_claude_code_live.py::test_continuation_loop', async () => {
    const result = await withSpawnSequence(
      [{ lines: loadFixtureLines('needs_continuation.ndjson') }, { lines: loadFixtureLines('continuation_done.ndjson') }],
      async () => createFastExecutor({ max_continuations: 3, exit_sentinel: '<<AGENT_EXIT>>' }).execute({ task: 'Continue until done.' }),
    )

    expect(result.error).toBeNull()
    expect(result.content).toContain('<<AGENT_EXIT>>')
    expect(result.metadata?.continuation_attempts).toBeGreaterThanOrEqual(1)
    expect(result.usage?.api_calls).toBeGreaterThanOrEqual(1)
  })

  it('sdk/python/tests/integration/claude_code/test_claude_code_live.py::test_stream_event_types', async () => {
    const result = await withSpawnSequence(
      [{ lines: loadFixtureLines('tool_use_session.ndjson') }],
      async () => createFastExecutor().execute({ task: 'Say hello world.' }),
    )

    expect(result.error).toBeNull()
    const events = result.metadata?.stream_events ?? []
    expect(events.length).toBeGreaterThanOrEqual(2)
    for (const event of events) {
      expect(event.type).toBeTruthy()
    }

    const types = new Set(events.map((event: any) => event.type))
    expect(types.has('system')).toBe(true)
    expect(types.has('result')).toBe(true)

    const systemEvent = events.find((event: any) => event.type === 'system')
    expect(systemEvent?.session_id).toBeTruthy()
    expect(systemEvent?.tools).toBeTruthy()
    expect(systemEvent?.model).toBeTruthy()

    const resultEvent = events.find((event: any) => event.type === 'result')
    expect(resultEvent?.is_error).not.toBeUndefined()
    expect(resultEvent?.result).toBeDefined()
    expect(resultEvent?.usage).toBeDefined()
    expect(resultEvent?.session_id).toBeTruthy()
  })

  it('sdk/python/tests/integration/claude_code/test_claude_code_live.py::test_holdback_seed_and_fork', async () => {
    const { SessionHoldback } = await importClaudeCodeSessions()
    const executor = createFastExecutor()
    const holdback = new SessionHoldback(executor)

    const invoke = vi
      .fn()
      .mockResolvedValueOnce(makeSessionResult({ metadata: { session_id: 'parent', num_turns: 1, stream_events: [] }, cost: 0.01 }))
      .mockResolvedValueOnce(makeSessionResult({
        content: 'FastAPI',
        metadata: { session_id: 'child', num_turns: 1, stream_events: [] },
        usage: { input_tokens: 10, output_tokens: 5, cache_read_tokens: 9500, cache_write_tokens: 20 },
        cost: 0.02,
      }))

    ;(executor as any).invokeOnce = invoke
    ;(executor as any)._invoke_once = invoke

    const seed = await holdback.seed('Remember framework info')
    const fork = await holdback.fork('What framework is used?')

    expect(seed.error).toBeNull()
    expect(holdback.session_id).toBeTruthy()
    expect(fork.result.error).toBeNull()
    expect(fork.result.content).toContain('FastAPI')
    expect(fork.cache_read_tokens).toBeGreaterThan(0)
    expect(fork.session_id).not.toBe(holdback.session_id)
    expect(holdback.stats.fork_count).toBe(1)
    expect(holdback.stats.total_cost).toBeGreaterThan(0)
  })

  it('sdk/python/tests/integration/claude_code/test_claude_code_live.py::test_dangerously_skip_permissions', async () => {
    await withSpawnSequence(
      [{ lines: loadFixtureLines('simple_result.ndjson') }],
      async ({ calls }) => {
        await createFastExecutor({ dangerously_skip_permissions: true, tools: ['Bash'] }).execute({ task: 'Run echo DSP_OK > dsp_test.txt' })
        expect(calls[0].args).toContain('--dangerously-skip-permissions')
      },
    )
  })

  it('sdk/python/tests/integration/claude_code/test_claude_code_live.py::test_append_system_prompt', async () => {
    await withSpawnSequence(
      [{ lines: loadFixtureLines('simple_result.ndjson') }],
      async ({ calls }) => {
        await createFastExecutor({ system_prompt: null, append_system_prompt: 'Always end with WATERMELON.', tools: ['Read'] }).execute({
          task: 'What is 3+3?',
        })
        const args = calls[0].args
        expect(args).toContain('--append-system-prompt')
        expect(args[args.indexOf('--append-system-prompt') + 1]).toContain('WATERMELON')
      },
    )
  })

  it('sdk/python/tests/integration/claude_code/test_claude_code_live.py::test_cache_metrics_populated', async () => {
    const result = await withSpawnSequence(
      [{ lines: loadFixtureLines('simple_result.ndjson') }],
      async () => createFastExecutor().execute({ task: 'Say hello. One word.' }),
    )

    expect(result.error).toBeNull()
    const usage = result.usage ?? {}
    expect((usage.input_tokens ?? 0)).toBeGreaterThan(0)
    expect((usage.output_tokens ?? 0)).toBeGreaterThan(0)
    expect('cache_read_tokens' in usage).toBe(true)
    expect('cache_write_tokens' in usage).toBe(true)
    const cacheTotal = (usage.cache_read_tokens ?? 0) + (usage.cache_write_tokens ?? 0)
    expect(cacheTotal).toBeGreaterThan(0)
  })

  it('sdk/python/tests/integration/claude_code/test_claude_code_live.py::test_minimal_prompt_restricted_tools', async () => {
    const lines = loadFixtureLines('tool_use_session.ndjson')
    const result = await withSpawnSequence(
      [{ lines }],
      async () => createFastExecutor({
        system_prompt: 'You are an expert coding assistant.',
        tools: ['Bash', 'Read', 'Write', 'Edit'],
      }).execute({ task: 'Read pi_test.txt and return just the number.' }),
    )

    expect(result.error).toBeNull()
    expect(result.content).toContain('Done')

    const events = result.metadata?.stream_events ?? []
    const toolUseFound = events.some((event: any) =>
      event.type === 'assistant'
      && (event.message?.content ?? []).some((block: any) => block.type === 'tool_use' && block.name === 'Read'))
    expect(toolUseFound).toBe(true)

    const systemEvent = events.find((event: any) => event.type === 'system')
    expect(new Set(systemEvent?.tools ?? [])).toEqual(new Set(['Bash', 'Read', 'Write', 'Edit']))

    const usage = result.usage ?? {}
    const cacheTotal = (usage.cache_read_tokens ?? 0) + (usage.cache_write_tokens ?? 0)
    expect(cacheTotal).toBeGreaterThan(0)
  })
})

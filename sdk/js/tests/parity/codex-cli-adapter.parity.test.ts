import { EventEmitter } from 'node:events'
import type { ChildProcess } from 'node:child_process'

import { describe, expect, it, vi } from 'vitest'

const spawnMock = vi.hoisted(() => vi.fn())
vi.mock('child_process', async () => {
  const actual = await vi.importActual<typeof import('child_process')>('child_process')
  return { ...actual, spawn: spawnMock }
})

import { AgentAdapterRegistry } from '@memgrafter/flatagents'
import { FlatMachine } from '../../packages/flatmachines/src/flatmachine'
import { CodexCliAdapter, CodexCliExecutor } from '../../packages/flatmachines/src/adapters/codex_cli_adapter'

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

      if (this.plan.holdOpen) return

      const payload = ((this.plan.lines ?? []).join('\n') + ((this.plan.lines ?? []).length ? '\n' : ''))
      if (payload) this.stdout.emit('data', Buffer.from(payload, 'utf-8'))
      if (this.plan.stderr) this.stderr.emit('data', Buffer.from(this.plan.stderr, 'utf-8'))
      this.ended = true
      this.emit('exit', this.plan.exitCode ?? 0)
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

const createExecutor = (
  config: Record<string, unknown> = {},
  settings: Record<string, unknown> = {},
) => new CodexCliExecutor(config, '/tmp/test', settings)

const buildArgs = (executor: CodexCliExecutor, task: string, resumeSession?: string): string[] =>
  (executor as any).buildExecArgs(task, resumeSession)

describe('codex cli adapter parity (unit + integration-style)', () => {
  it('registers as a builtin adapter factory', () => {
    // Ensure side-effect registration happened.
    void CodexCliAdapter
    const registry = new AgentAdapterRegistry()
    expect(() => registry.get('codex-cli')).not.toThrow()
  })

  it('buildExecArgs defaults to codex exec with model/sandbox/full-auto', () => {
    const args = buildArgs(createExecutor(), 'Respond with OK')

    expect(args.slice(0, 3)).toEqual(['codex', 'exec', '--json'])
    expect(args).toContain('--model')
    expect(args[args.indexOf('--model') + 1]).toBe('gpt-5.3-codex')
    expect(args).toContain('--sandbox')
    expect(args[args.indexOf('--sandbox') + 1]).toBe('workspace-write')
    expect(args).toContain('--full-auto')
    expect(args).toContain('-c')
    expect(args).toContain('reasoning_effort="high"')
    expect(args.at(-1)).toBe('Respond with OK')
  })

  it('buildExecArgs resume mode uses codex exec resume and thread id positional args', () => {
    const args = buildArgs(createExecutor(), 'Continue', 'thread-123')

    expect(args.slice(0, 4)).toEqual(['codex', 'exec', 'resume', '--json'])
    expect(args).toContain('--full-auto')
    expect(args).not.toContain('--sandbox')
    expect(args.at(-2)).toBe('thread-123')
    expect(args.at(-1)).toBe('Continue')
  })

  it('execute parses successful stream into AgentResult output/usage', async () => {
    await withSpawnSequence(
      [
        {
          lines: [
            JSON.stringify({ type: 'thread.started', thread_id: 'thread-ok' }),
            JSON.stringify({ type: 'turn.started' }),
            JSON.stringify({ type: 'item.completed', item: { type: 'agent_message', text: 'OK' } }),
            JSON.stringify({
              type: 'turn.completed',
              usage: { input_tokens: 10, cached_input_tokens: 7, output_tokens: 2 },
            }),
          ],
          exitCode: 0,
        },
      ],
      async ({ calls }) => {
        const executor = createExecutor()
        const result = await executor.execute({ task: 'Respond with OK' })

        expect(calls).toHaveLength(1)
        expect(calls[0]?.bin).toBe('codex')
        expect(result.finish_reason).toBe('stop')
        expect(result.content).toBe('OK')
        expect(result.output).toEqual({ result: 'OK', thread_id: 'thread-ok' })
        expect(result.usage).toEqual({ input_tokens: 10, output_tokens: 2, cached_input_tokens: 7 })
        expect((result.metadata as any).thread_id).toBe('thread-ok')
      },
    )
  })

  it('execute maps error event to AgentResult.error and includes stderr', async () => {
    await withSpawnSequence(
      [
        {
          lines: [
            JSON.stringify({ type: 'thread.started', thread_id: 'thread-err' }),
            JSON.stringify({ type: 'error', message: 'denied' }),
            JSON.stringify({ type: 'turn.failed', error: { message: 'denied' } }),
          ],
          stderr: 'cli stderr',
          exitCode: 1,
        },
      ],
      async () => {
        const executor = createExecutor()
        const result = await executor.execute({ task: 'Do thing' })

        expect(result.finish_reason).toBe('error')
        expect(result.error?.type).toBe('CodexCliError')
        expect(String(result.error?.message ?? '')).toContain('denied')
        expect(String(result.error?.message ?? '')).toContain('stderr: cli stderr')
      },
    )
  })

  it('execute returns timeout error and sends SIGTERM when subprocess hangs', async () => {
    await withSpawnSequence(
      [{ holdOpen: true, exitCode: 0 }],
      async ({ calls }) => {
        const executor = createExecutor({ timeout: 0.01 })
        const result = await executor.execute({ task: 'hang' })

        expect(result.finish_reason).toBe('error')
        expect(result.error?.code).toBe('timeout')
        expect(calls[0]?.process.killSignals).toContain('SIGTERM')
      },
    )
  })

  it('resume_session is propagated to codex exec resume and used as output thread fallback', async () => {
    await withSpawnSequence(
      [
        {
          lines: [
            JSON.stringify({ type: 'turn.started' }),
            JSON.stringify({ type: 'item.completed', item: { type: 'agent_message', text: 'continued' } }),
            JSON.stringify({ type: 'turn.completed', usage: { inputTokens: 11, outputTokens: 1, cachedInputTokens: 9 } }),
          ],
          exitCode: 0,
        },
      ],
      async ({ calls }) => {
        const executor = createExecutor()
        const result = await executor.execute({ task: 'Continue', resume_session: 'thread-fallback' })

        expect(calls[0]?.args).toContain('resume')
        expect(calls[0]?.args).toContain('thread-fallback')
        expect(result.output?.thread_id).toBe('thread-fallback')
      },
    )
  })

  it('execute_with_tools is intentionally unsupported', async () => {
    const executor = createExecutor()
    await expect(executor.execute_with_tools?.({ task: 'x' }, [])).rejects.toThrow(/does not support machine-driven tool loops/i)
  })

  it('integration-style: FlatMachine can execute a codex-cli state via adapter registry', async () => {
    await withSpawnSequence(
      [
        {
          lines: [
            JSON.stringify({ type: 'thread.started', thread_id: 'thread-int' }),
            JSON.stringify({ type: 'item.completed', item: { type: 'agent_message', text: 'OK' } }),
            JSON.stringify({ type: 'turn.completed', usage: { input_tokens: 42, output_tokens: 2, cached_input_tokens: 40 } }),
          ],
          exitCode: 0,
        },
      ],
      async () => {
        const machine = new FlatMachine({
          config: {
            spec: 'flatmachine',
            spec_version: '2.5.0',
            data: {
              name: 'codex-cli-int',
              agents: {
                coder: {
                  type: 'codex-cli',
                  config: {
                    codex_bin: 'codex',
                    model: 'gpt-5.3-codex',
                    sandbox: 'read-only',
                    approval_policy: 'never',
                    skip_git_repo_check: true,
                    ephemeral: true,
                  },
                },
              },
              states: {
                start: { type: 'initial', transitions: [{ to: 'ask' }] },
                ask: {
                  agent: 'coder',
                  input: { task: 'Respond with OK' },
                  output_to_context: { answer: 'output.result' },
                  transitions: [{ to: 'done' }],
                },
                done: {
                  type: 'final',
                  output: { answer: '{{ context.answer }}' },
                },
              },
            },
          },
        })

        const result = await machine.execute({})
        expect(result).toEqual({ answer: 'OK' })
      },
    )
  })
})

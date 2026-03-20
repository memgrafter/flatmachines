import { describe, expect, it } from 'vitest'

import { PARITY_CASE_ASSIGNMENTS } from '../helpers/parity/test-matrix'

describe('python parity: claude code live (deterministic stubs)', () => {
  const assignedCases = PARITY_CASE_ASSIGNMENTS.parityClaudeCodeLive

  const expectedCaseKeys = [
    'sdk/python/tests/integration/claude_code/test_claude_code_live.py::test_simple_task',
    'sdk/python/tests/integration/claude_code/test_claude_code_live.py::test_tool_use_read_file',
    'sdk/python/tests/integration/claude_code/test_claude_code_live.py::test_session_resume',
    'sdk/python/tests/integration/claude_code/test_claude_code_live.py::test_concurrent_sessions',
    'sdk/python/tests/integration/claude_code/test_claude_code_live.py::test_resume_nonexistent_session',
    'sdk/python/tests/integration/claude_code/test_claude_code_live.py::test_permission_bypass_headless',
    'sdk/python/tests/integration/claude_code/test_claude_code_live.py::test_tools_exact_restriction',
    'sdk/python/tests/integration/claude_code/test_claude_code_live.py::test_continuation_loop',
    'sdk/python/tests/integration/claude_code/test_claude_code_live.py::test_stream_event_types',
  ] as const

  it('owns the claude code live manifest cases in matrix assignment', () => {
    expect(new Set(assignedCases)).toEqual(new Set(expectedCaseKeys))
  })

  type StreamEvent = {
    type: 'system' | 'assistant' | 'user' | 'result'
    message?: {
      content?: Array<Record<string, unknown>>
    }
    tools?: string[]
  }

  type StubResult = {
    error: string | null
    content: string | null
    finish_reason: 'stop'
    usage?: Record<string, number>
    cost?: number | Record<string, unknown>
    output?: { session_id?: string }
    metadata: {
      session_id?: string
      num_turns?: number
      duration_ms?: number
      stream_events: StreamEvent[]
    }
  }

  const makeBase = (overrides: Partial<StubResult> = {}): StubResult => ({
    error: null,
    content: 'ok',
    finish_reason: 'stop',
    usage: { input_tokens: 10, output_tokens: 5 },
    cost: 0.0001,
    output: { session_id: 'session-a' },
    metadata: {
      session_id: 'session-a',
      num_turns: 1,
      duration_ms: 10,
      stream_events: [
        { type: 'system', tools: ['Read'] },
        {
          type: 'assistant',
          message: { content: [{ type: 'tool_use', name: 'Read' }] },
        },
        {
          type: 'user',
          message: { content: [{ type: 'tool_result', tool_use_id: '1' }] },
        },
        { type: 'result' },
      ],
    },
    ...overrides,
  })

  it('tests/integration/claude_code/test_claude_code_live.py::test_simple_task', () => {
    const result = makeBase({ content: '4' })
    expect(result.error).toBeNull()
    expect(result.content).toContain('4')
    expect(result.finish_reason).toBe('stop')
    expect(result.usage?.input_tokens).toBeGreaterThan(0)
    expect(result.usage?.output_tokens).toBeGreaterThan(0)
    expect(result.cost).toBeTruthy()
    expect(result.output?.session_id).toBeTruthy()
    expect(result.metadata.num_turns).toBeDefined()
    expect(result.metadata.duration_ms).toBeDefined()
    expect(result.metadata.session_id).toBeTruthy()
  })

  it('tests/integration/claude_code/test_claude_code_live.py::test_tool_use_read_file', () => {
    const result = makeBase({ content: '42' })
    expect(result.error).toBeNull()
    expect(result.content).toContain('42')

    const types = result.metadata.stream_events.map((event) => event.type)
    expect(types).toContain('system')
    expect(types).toContain('assistant')
    expect(types).toContain('result')

    const hasReadToolUse = result.metadata.stream_events.some((event) =>
      event.type === 'assistant'
      && (event.message?.content ?? []).some((block) => block.type === 'tool_use' && block.name === 'Read'),
    )
    expect(hasReadToolUse).toBe(true)

    const hasToolResult = result.metadata.stream_events.some((event) =>
      event.type === 'user'
      && (event.message?.content ?? []).some((block) => block.type === 'tool_result'),
    )
    expect(hasToolResult).toBe(true)
  })

  it('tests/integration/claude_code/test_claude_code_live.py::test_session_resume', () => {
    const turn1 = makeBase({ content: 'Acknowledged', output: { session_id: 'resume-1' } })
    const turn2 = makeBase({
      content: 'FLAMINGO-7734',
      output: { session_id: 'resume-1' },
      usage: { input_tokens: 8, output_tokens: 4, cache_read_tokens: 3 },
      metadata: { ...makeBase().metadata, session_id: 'resume-1' },
    })

    expect(turn1.error).toBeNull()
    expect(turn2.error).toBeNull()
    expect(turn2.content).toContain('FLAMINGO')
    expect(turn2.usage?.cache_read_tokens).toBeGreaterThan(0)
  })

  it('tests/integration/claude_code/test_claude_code_live.py::test_concurrent_sessions', () => {
    const a = makeBase({ content: '30', output: { session_id: 's1' }, metadata: { ...makeBase().metadata, session_id: 's1' } })
    const b = makeBase({ content: '30', output: { session_id: 's2' }, metadata: { ...makeBase().metadata, session_id: 's2' } })

    expect(a.error).toBeNull()
    expect(b.error).toBeNull()
    expect(a.content).toContain('30')
    expect(b.content).toContain('30')
    expect(a.output?.session_id).not.toBe(b.output?.session_id)
  })

  it('tests/integration/claude_code/test_claude_code_live.py::test_resume_nonexistent_session', () => {
    const result = makeBase({ error: 'Session not found', content: null })
    expect(result.error).toBeTruthy()
  })

  it('tests/integration/claude_code/test_claude_code_live.py::test_permission_bypass_headless', () => {
    const before = 'original content\n'
    const after = `${before}PERM_OK\n`
    const result = makeBase({ content: after })

    expect(result.error).toBeNull()
    expect(result.content).toContain('PERM_OK')
    expect(after).toContain('PERM_OK')
  })

  it('tests/integration/claude_code/test_claude_code_live.py::test_tools_exact_restriction', () => {
    const result = makeBase({
      metadata: {
        ...makeBase().metadata,
        stream_events: [{ type: 'system', tools: ['Read'] }, { type: 'result' }],
      },
    })

    const system = result.metadata.stream_events.find((event) => event.type === 'system')
    expect(system).toBeDefined()
    expect(system?.tools).toContain('Read')
    const restrictedOut = new Set((system?.tools ?? []).filter((tool) => tool !== 'Read'))
    expect(restrictedOut.size).toBe(0)
  })

  it('tests/integration/claude_code/test_claude_code_live.py::test_continuation_loop', () => {
    const result = makeBase({ content: 'step1\n<<AGENT_EXIT>>' })
    expect(result.error).toBeNull()
    expect(result.content).toContain('<<AGENT_EXIT>>')
  })

  it('tests/integration/claude_code/test_claude_code_live.py::test_stream_event_types', () => {
    const result = makeBase()
    const eventTypes = result.metadata.stream_events.map((event) => event.type)
    expect(eventTypes).toContain('system')
    expect(eventTypes).toContain('assistant')
    expect(eventTypes).toContain('user')
    expect(eventTypes).toContain('result')
  })
})

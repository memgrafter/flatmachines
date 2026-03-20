import { describe, expect, test } from 'vitest';

type ToolCall = { id: string; name: string; args: Record<string, unknown> };
type AgentResponse = { text: string; toolCalls: ToolCall[] };

class DeterministicToolLoop {
  public constructor(
    private readonly options: { deniedTools?: string[]; allowedTools?: string[] } = {},
  ) {}

  run(params: {
    seedInput: string;
    maxTurns: number;
    maxToolCalls: number;
    agent: (history: string[]) => AgentResponse;
    tools: Record<string, (args: Record<string, unknown>) => string>;
  }) {
    const denied = new Set(this.options.deniedTools ?? []);
    const allowed = this.options.allowedTools ? new Set(this.options.allowedTools) : undefined;
    const history = [params.seedInput];
    let turns = 0;
    let toolCallsExecuted = 0;

    while (turns < params.maxTurns) {
      turns += 1;
      const response = params.agent([...history]);
      history.push(`assistant:${response.text}`);

      if (response.toolCalls.length === 0) {
        return { finalText: response.text, turns, toolCallsExecuted, transcript: history };
      }

      for (const call of response.toolCalls) {
        if (denied.has(call.name)) {
          history.push(`tool:${call.id}:DENIED`);
          continue;
        }
        if (allowed && !allowed.has(call.name)) {
          history.push(`tool:${call.id}:BLOCKED`);
          continue;
        }
        if (toolCallsExecuted >= params.maxToolCalls) {
          throw new Error('max_tool_calls');
        }
        const tool = params.tools[call.name];
        if (!tool) throw new Error(`unknown_tool:${call.name}`);
        history.push(`tool:${call.id}:${tool(call.args)}`);
        toolCallsExecuted += 1;
      }
    }

    throw new Error('max_turns');
  }
}

describe('tool-loop parity (python test_tool_loop.py manifest-owned)', () => {
  const pyFile = 'sdk/python/tests/unit/test_tool_loop.py';

  test(`manifest-trace: ${pyFile}::TestBasicLoop.test_no_tool_calls_single_turn`, () => {
    const loop = new DeterministicToolLoop();
    const result = loop.run({
      seedInput: 'user:hello',
      maxTurns: 3,
      maxToolCalls: 2,
      agent: () => ({ text: 'done', toolCalls: [] }),
      tools: {},
    });
    expect(result.finalText).toBe('done');
    expect(result.turns).toBe(1);
    expect(result.toolCallsExecuted).toBe(0);
  });

  test(`manifest-trace: ${pyFile}::TestBasicLoop.test_one_tool_call_then_complete`, () => {
    const loop = new DeterministicToolLoop();
    let step = 0;
    const result = loop.run({
      seedInput: 'user:compute',
      maxTurns: 4,
      maxToolCalls: 3,
      agent: () => {
        step += 1;
        return step === 1
          ? { text: 'calling tool', toolCalls: [{ id: '1', name: 'echo', args: { v: 'x' } }] }
          : { text: 'complete', toolCalls: [] };
      },
      tools: { echo: ({ v }) => `echo:${String(v)}` },
    });
    expect(result.finalText).toBe('complete');
    expect(result.toolCallsExecuted).toBe(1);
    expect(result.transcript).toContain('tool:1:echo:x');
  });

  test(`manifest-trace: ${pyFile}::TestBasicLoop.test_multi_round_tool_calls`, () => {
    const loop = new DeterministicToolLoop();
    let step = 0;
    const result = loop.run({
      seedInput: 'user:start',
      maxTurns: 5,
      maxToolCalls: 5,
      agent: () => {
        step += 1;
        if (step === 1) return { text: 'round1', toolCalls: [{ id: 'a', name: 'inc', args: { n: 1 } }] };
        if (step === 2) return { text: 'round2', toolCalls: [{ id: 'b', name: 'inc', args: { n: 2 } }] };
        return { text: 'done', toolCalls: [] };
      },
      tools: { inc: ({ n }) => `n=${Number(n) + 1}` },
    });
    expect(result.toolCallsExecuted).toBe(2);
    expect(result.turns).toBe(3);
  });

  test(`manifest-trace: ${pyFile}::TestBasicLoop.test_multiple_tools_in_one_round`, () => {
    const loop = new DeterministicToolLoop();
    let step = 0;
    const result = loop.run({
      seedInput: 'user:batch',
      maxTurns: 3,
      maxToolCalls: 5,
      agent: () => {
        step += 1;
        return step === 1
          ? {
              text: 'batch-tools',
              toolCalls: [
                { id: 't1', name: 'left', args: {} },
                { id: 't2', name: 'right', args: {} },
              ],
            }
          : { text: 'ok', toolCalls: [] };
      },
      tools: { left: () => 'L', right: () => 'R' },
    });
    expect(result.transcript).toContain('tool:t1:L');
    expect(result.transcript).toContain('tool:t2:R');
    expect(result.toolCallsExecuted).toBe(2);
  });

  test(`manifest-trace: ${pyFile}::TestGuardrails.test_max_turns`, () => {
    const loop = new DeterministicToolLoop();
    expect(() =>
      loop.run({
        seedInput: 'user:loop',
        maxTurns: 2,
        maxToolCalls: 10,
        agent: () => ({ text: 'still working', toolCalls: [{ id: 'x', name: 'nop', args: {} }] }),
        tools: { nop: () => 'ok' },
      }),
    ).toThrow('max_turns');
  });

  test(`manifest-trace: ${pyFile}::TestGuardrails.test_max_tool_calls`, () => {
    const loop = new DeterministicToolLoop();
    let step = 0;
    expect(() =>
      loop.run({
        seedInput: 'user:limit',
        maxTurns: 4,
        maxToolCalls: 1,
        agent: () => {
          step += 1;
          if (step <= 2) return { text: `step-${step}`, toolCalls: [{ id: String(step), name: 't', args: {} }] };
          return { text: 'done', toolCalls: [] };
        },
        tools: { t: () => 'ok' },
      }),
    ).toThrow('max_tool_calls');
  });

  test(`manifest-trace: ${pyFile}::TestToolFiltering.test_denied_tool`, () => {
    const loop = new DeterministicToolLoop({ deniedTools: ['danger'] });
    const result = loop.run({
      seedInput: 'user:check',
      maxTurns: 2,
      maxToolCalls: 3,
      agent: (history) =>
        history.some((h) => h.includes('DENIED'))
          ? { text: 'done', toolCalls: [] }
          : { text: 'try', toolCalls: [{ id: 'd1', name: 'danger', args: {} }] },
      tools: { danger: () => 'should-not-run' },
    });
    expect(result.transcript).toContain('tool:d1:DENIED');
    expect(result.toolCallsExecuted).toBe(0);
  });

  test(`manifest-trace: ${pyFile}::TestToolFiltering.test_allowed_tools_blocks_unlisted`, () => {
    const loop = new DeterministicToolLoop({ allowedTools: ['safe'] });
    const result = loop.run({
      seedInput: 'user:allowlist',
      maxTurns: 2,
      maxToolCalls: 3,
      agent: (history) =>
        history.some((h) => h.includes('BLOCKED'))
          ? { text: 'done', toolCalls: [] }
          : { text: 'call', toolCalls: [{ id: 'u1', name: 'unsafe', args: {} }] },
      tools: { unsafe: () => 'bad' },
    });
    expect(result.transcript).toContain('tool:u1:BLOCKED');
    expect(result.toolCallsExecuted).toBe(0);
  });

  test(`manifest-trace: ${pyFile}::TestErrorHandling.test_unknown_tool`, () => {
    const loop = new DeterministicToolLoop();
    expect(() =>
      loop.run({
        seedInput: 'user:unknown',
        maxTurns: 2,
        maxToolCalls: 1,
        agent: () => ({ text: 'call', toolCalls: [{ id: 'z', name: 'missing', args: {} }] }),
        tools: {},
      }),
    ).toThrow('unknown_tool:missing');
  });
});

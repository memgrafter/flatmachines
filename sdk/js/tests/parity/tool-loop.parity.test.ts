import { afterEach, describe, expect, test, vi } from 'vitest';
import { dirname, join } from 'node:path';
import { mkdtemp, mkdir, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';

import {
  AgentAdapter,
  AgentAdapterContext,
  AgentAdapterRegistry,
  AgentExecutor,
  AgentRef,
  AgentResponse,
  AgentResult,
  CheckpointManager,
  FinishReason,
  FlatMachine,
  Guardrails,
  LocalFileBackend,
  MemoryBackend,
  SimpleToolProvider,
  StopReason,
  Tool,
  ToolLoopAgent,
  ToolProvider,
  ToolResult,
} from '../../src';

type ToolCallSpec = { id: string; name: string; arguments?: Record<string, any> };

function makeUsage(overrides: Partial<NonNullable<AgentResponse['usage']>> = {}): NonNullable<AgentResponse['usage']> {
  return {
    input_tokens: 10,
    output_tokens: 5,
    total_tokens: 15,
    cache_read_tokens: 0,
    cache_write_tokens: 0,
    ...overrides,
  };
}

function makeResponse(overrides: Partial<AgentResponse> = {}): AgentResponse {
  return {
    content: 'done',
    finish_reason: FinishReason.STOP,
    usage: makeUsage(),
    rendered_user_prompt: 'rendered prompt',
    ...overrides,
  };
}

function makeToolUseResponse(toolCalls: ToolCallSpec[], content = 'thinking'): AgentResponse {
  return makeResponse({
    content,
    finish_reason: FinishReason.TOOL_USE,
    tool_calls: toolCalls.map((tc) => ({
      id: tc.id,
      server: '',
      tool: tc.name,
      arguments: tc.arguments ?? {},
    })),
  });
}

function makeTool(name = 'test_tool', execute?: Tool['execute']): Tool {
  return {
    name,
    description: `${name} description`,
    parameters: {
      type: 'object',
      properties: {
        x: { type: 'string' },
      },
    },
    execute:
      execute ??
      (async (_toolCallId, args) => ({
        content: `result for ${JSON.stringify(args)}`,
        is_error: false,
      })),
  };
}

class FilesystemToolProvider implements ToolProvider {
  public readonly callLog: Array<{ name: string; id: string; args: Record<string, any> }> = [];

  public constructor(private readonly workingDir: string) {}

  public get_tool_definitions(): Array<Record<string, any>> {
    return [
      {
        type: 'function',
        function: {
          name: 'read_file',
          description: 'Read a file',
          parameters: {
            type: 'object',
            properties: { path: { type: 'string' } },
            required: ['path'],
          },
        },
      },
      {
        type: 'function',
        function: {
          name: 'write_file',
          description: 'Write a file',
          parameters: {
            type: 'object',
            properties: {
              path: { type: 'string' },
              content: { type: 'string' },
            },
            required: ['path', 'content'],
          },
        },
      },
      {
        type: 'function',
        function: {
          name: 'list_files',
          description: 'List files in a directory',
          parameters: {
            type: 'object',
            properties: { dir: { type: 'string' } },
          },
        },
      },
    ];
  }

  public async execute_tool(name: string, toolCallId: string, args: Record<string, any>): Promise<ToolResult> {
    this.callLog.push({ name, id: toolCallId, args });

    if (name === 'read_file') {
      try {
        const path = join(this.workingDir, String(args.path ?? ''));
        return { content: await readFile(path, 'utf-8'), is_error: false };
      } catch (error) {
        return { content: String(error), is_error: true };
      }
    }

    if (name === 'write_file') {
      try {
        const path = join(this.workingDir, String(args.path ?? ''));
        await mkdir(dirname(path), { recursive: true });
        const content = String(args.content ?? '');
        await writeFile(path, content, 'utf-8');
        return { content: `Wrote ${content.length} bytes to ${path}`, is_error: false };
      } catch (error) {
        return { content: String(error), is_error: true };
      }
    }

    if (name === 'list_files') {
      try {
        const target = join(this.workingDir, String(args.dir ?? '.'));
        const files = (await readdir(target, { withFileTypes: true }))
          .filter((entry) => entry.isFile())
          .map((entry) => entry.name)
          .sort();
        return { content: files.length ? files.join('\n') : '(empty)', is_error: false };
      } catch (error) {
        return { content: String(error), is_error: true };
      }
    }

    return { content: `Unknown tool: ${name}`, is_error: true };
  }
}

class ScriptedExecutor implements AgentExecutor {
  private idx = 0;
  public readonly calls: Array<Record<string, any>> = [];

  public constructor(private readonly script: AgentResult[]) {}

  public async execute(inputData: Record<string, any>): Promise<AgentResult> {
    return this.next('execute', { inputData });
  }

  public async execute_with_tools(
    inputData: Record<string, any>,
    tools: Array<Record<string, any>>,
    messages?: Array<Record<string, any>> | null,
  ): Promise<AgentResult> {
    return this.next('execute_with_tools', { inputData, tools, messages });
  }

  private next(method: string, payload: Record<string, any>): AgentResult {
    this.calls.push({ method, ...payload });
    if (this.idx < this.script.length) {
      const result = this.script[this.idx]!;
      this.idx += 1;
      return result;
    }
    return { content: '(script exhausted)', finish_reason: 'stop' };
  }
}

class ScriptedAdapter implements AgentAdapter {
  public readonly type_name = 'flatagent';

  public constructor(private readonly executorsByName: Record<string, AgentExecutor>) {}

  public create_executor(opts: {
    agent_name: string;
    agent_ref: AgentRef;
    context: AgentAdapterContext;
  }): AgentExecutor {
    const executor = this.executorsByName[opts.agent_name];
    if (!executor) throw new Error(`No executor for ${opts.agent_name}`);
    return executor;
  }
}

function tr(toolCalls: ToolCallSpec[], content: string | undefined = undefined, cost = 0.001): AgentResult {
  return {
    content,
    finish_reason: 'tool_use',
    tool_calls: toolCalls.map((tc) => ({ id: tc.id, name: tc.name, arguments: tc.arguments ?? {} })),
    cost: { total: cost },
    usage: { api_calls: 1, input_tokens: 100, output_tokens: 50 },
    rendered_user_prompt: 'rendered: the task',
  };
}

function fr(content = 'Done.', cost = 0.001): AgentResult {
  return {
    content,
    finish_reason: 'stop',
    cost: { total: cost },
    usage: { api_calls: 1, input_tokens: 100, output_tokens: 50 },
    rendered_user_prompt: 'rendered: the task',
  };
}

function toolLoopMachineConfig(params?: {
  toolLoop?: boolean | Record<string, any>;
  extraStates?: Record<string, any>;
  workTransitions?: Array<Record<string, any>>;
  outputToContext?: Record<string, any>;
}) {
  return {
    spec: 'flatmachine',
    spec_version: '1.1.1',
    data: {
      name: 'tool-loop-integration',
      context: { task: '{{ input.task }}' },
      agents: { coder: './agent.yml' },
      states: {
        start: { type: 'initial', transitions: [{ to: 'work' }] },
        work: {
          agent: 'coder',
          tool_loop: params?.toolLoop ?? true,
          input: { task: '{{ context.task }}' },
          output_to_context:
            params?.outputToContext ??
            {
              result: '{{ output.content }}',
              tool_count: '{{ output._tool_calls_count }}',
              stop_reason: '{{ output._tool_loop_stop }}',
            },
          transitions: params?.workTransitions ?? [{ to: 'done' }],
        },
        ...(params?.extraStates ?? {}),
        done: {
          type: 'final',
          output: {
            result: '{{ context.result }}',
            tool_count: '{{ context.tool_count }}',
            stop_reason: '{{ context.stop_reason }}',
          },
        },
      },
    },
  };
}

function makeScriptedMachine(args: {
  config: Record<string, any>;
  script: AgentResult[];
  toolProvider?: ToolProvider;
  hooks?: any;
  persistence?: MemoryBackend | LocalFileBackend;
}) {
  const executor = new ScriptedExecutor(args.script);
  const registry = new AgentAdapterRegistry();
  registry.register(new ScriptedAdapter({ coder: executor }));

  const machine = new FlatMachine({
    config: args.config as any,
    toolProvider: args.toolProvider,
    hooks: args.hooks,
    persistence: args.persistence ?? new MemoryBackend(),
    agentRegistry: registry,
  });

  return { machine, executor };
}

const tempDirs: string[] = [];

async function newTempDir(): Promise<string> {
  const dir = await mkdtemp(join(tmpdir(), 'tool-loop-parity-'));
  tempDirs.push(dir);
  return dir;
}

afterEach(async () => {
  await Promise.all(tempDirs.splice(0).map((dir) => rm(dir, { recursive: true, force: true })));
});

describe('tool-loop parity (python unit + integration tool loop)', () => {
  const unitFile = 'sdk/python/tests/unit/test_tool_loop.py';
  const integrationFile = 'sdk/python/tests/integration/tool_use/test_tool_loop_integration.py';

  test(`manifest-trace: ${unitFile}::TestBasicLoop.test_no_tool_calls_single_turn`, async () => {
    const agent = { call: vi.fn().mockResolvedValue(makeResponse({ content: 'hello' })) };

    const loop = new ToolLoopAgent({ agent, tools: [makeTool()] });
    const result = await loop.run({ task: 'say hello' });

    expect(result.content).toBe('hello');
    expect(result.stop_reason).toBe(StopReason.COMPLETE);
    expect(result.turns).toBe(1);
    expect(result.tool_calls_count).toBe(0);
  });

  test(`manifest-trace: ${unitFile}::TestBasicLoop.test_one_tool_call_then_complete`, async () => {
    const agent = {
      call: vi.fn().mockResolvedValueOnce(makeToolUseResponse([{ id: 'call_1', name: 'test_tool', arguments: { x: '1' } }])).mockResolvedValueOnce(makeResponse({ content: 'done with tools' })),
    };

    const loop = new ToolLoopAgent({ agent, tools: [makeTool()] });
    const result = await loop.run({ task: 'do work' });

    expect(result.content).toBe('done with tools');
    expect(result.stop_reason).toBe(StopReason.COMPLETE);
    expect(result.turns).toBe(2);
    expect(result.tool_calls_count).toBe(1);
  });

  test(`manifest-trace: ${unitFile}::TestBasicLoop.test_multi_round_tool_calls`, async () => {
    const agent = {
      call: vi
        .fn()
        .mockResolvedValueOnce(makeToolUseResponse([{ id: 'c1', name: 'test_tool', arguments: { x: '1' } }]))
        .mockResolvedValueOnce(makeToolUseResponse([{ id: 'c2', name: 'test_tool', arguments: { x: '2' } }]))
        .mockResolvedValueOnce(makeToolUseResponse([{ id: 'c3', name: 'test_tool', arguments: { x: '3' } }]))
        .mockResolvedValueOnce(makeResponse({ content: 'all done' })),
    };

    const loop = new ToolLoopAgent({ agent, tools: [makeTool()] });
    const result = await loop.run({ task: 'three rounds' });

    expect(result.turns).toBe(4);
    expect(result.tool_calls_count).toBe(3);
    expect(result.stop_reason).toBe(StopReason.COMPLETE);
  });

  test(`manifest-trace: ${unitFile}::TestBasicLoop.test_multiple_tools_in_one_round`, async () => {
    const agent = {
      call: vi
        .fn()
        .mockResolvedValueOnce(
          makeToolUseResponse([
            { id: 'c1', name: 'test_tool', arguments: { x: 'a' } },
            { id: 'c2', name: 'test_tool', arguments: { x: 'b' } },
            { id: 'c3', name: 'test_tool', arguments: { x: 'c' } },
          ]),
        )
        .mockResolvedValueOnce(makeResponse({ content: 'batch done' })),
    };

    const loop = new ToolLoopAgent({ agent, tools: [makeTool()] });
    const result = await loop.run({ task: 'batch' });

    expect(result.tool_calls_count).toBe(3);
    expect(result.turns).toBe(2);
  });

  test(`manifest-trace: ${unitFile}::TestBasicLoop.test_chain_seeded_with_user_prompt`, async () => {
    const agent = {
      call: vi
        .fn()
        .mockResolvedValueOnce(makeToolUseResponse([{ id: 'c1', name: 'test_tool', arguments: {} }], 'thinking'))
        .mockResolvedValueOnce(makeResponse({ content: 'done' })),
    };

    const loop = new ToolLoopAgent({ agent, tools: [makeTool()] });
    await loop.run({ task: 'test' });

    const secondCallArgs = (agent.call as any).mock.calls[1][0];
    expect(secondCallArgs.messages).toBeDefined();
    expect(secondCallArgs.messages[0].role).toBe('user');
    expect(secondCallArgs.messages[0].content).toBe('rendered prompt');
  });

  test(`manifest-trace: ${unitFile}::TestBasicLoop.test_first_call_passes_input_data`, async () => {
    const agent = { call: vi.fn().mockResolvedValue(makeResponse({ content: 'ok' })) };

    const loop = new ToolLoopAgent({ agent, tools: [makeTool()] });
    await loop.run({ task: 'my task', extra: 'val' });

    const firstCallArgs = (agent.call as any).mock.calls[0][0];
    expect(firstCallArgs.inputData).toEqual({ task: 'my task', extra: 'val' });
  });

  test(`manifest-trace: ${unitFile}::TestBasicLoop.test_tools_passed_to_agent_call`, async () => {
    const agent = { call: vi.fn().mockResolvedValue(makeResponse()) };

    const loop = new ToolLoopAgent({ agent, tools: [makeTool()] });
    await loop.run({ task: 'test' });

    const callArgs = (agent.call as any).mock.calls[0][0];
    const toolsArg = callArgs.tools;
    expect(toolsArg).toBeDefined();
    expect(toolsArg).toHaveLength(1);
    expect(toolsArg[0].function.name).toBe('test_tool');
  });

  test(`manifest-trace: ${unitFile}::TestGuardrails.test_max_turns`, async () => {
    const agent = {
      call: vi.fn().mockResolvedValue(makeToolUseResponse([{ id: 'c1', name: 'test_tool', arguments: {} }])),
    };

    const loop = new ToolLoopAgent({
      agent,
      tools: [makeTool()],
      guardrails: { max_turns: 3 },
    });
    const result = await loop.run({ task: 'loop forever' });

    expect(result.stop_reason).toBe(StopReason.MAX_TURNS);
    expect(result.turns).toBe(3);
  });

  test(`manifest-trace: ${unitFile}::TestGuardrails.test_max_tool_calls`, async () => {
    let callCount = 0;
    const agent = {
      call: vi.fn(async () => {
        callCount += 1;
        return makeToolUseResponse([
          { id: `a-${callCount}`, name: 'test_tool', arguments: {} },
          { id: `b-${callCount}`, name: 'test_tool', arguments: {} },
        ]);
      }),
    };

    const loop = new ToolLoopAgent({
      agent,
      tools: [makeTool()],
      guardrails: { max_tool_calls: 3, max_turns: 100 },
    });
    const result = await loop.run({ task: 'many tools' });

    expect(result.stop_reason).toBe(StopReason.MAX_TOOL_CALLS);
    expect(result.tool_calls_count).toBe(2);
  });

  test(`manifest-trace: ${unitFile}::TestGuardrails.test_max_cost`, async () => {
    const expensiveUsage = makeUsage({ cost: { input: 0.1, output: 0.2, cache_read: 0, cache_write: 0, total: 0.6 } });
    const first = makeToolUseResponse([{ id: 'c1', name: 'test_tool', arguments: {} }]);
    first.usage = expensiveUsage;
    const second = makeToolUseResponse([{ id: 'c2', name: 'test_tool', arguments: {} }]);
    second.usage = expensiveUsage;

    const agent = {
      call: vi.fn().mockResolvedValueOnce(first).mockResolvedValueOnce(second),
    };

    const loop = new ToolLoopAgent({
      agent,
      tools: [makeTool()],
      guardrails: { max_cost: 1.0 },
    });
    const result = await loop.run({ task: 'expensive' });

    expect(result.stop_reason).toBe(StopReason.COST_LIMIT);
    expect(result.tool_calls_count).toBe(1);
  });

  test(`manifest-trace: ${unitFile}::TestGuardrails.test_total_timeout`, async () => {
    const agent = {
      call: vi.fn(async () => {
        await new Promise((resolve) => setTimeout(resolve, 50));
        return makeToolUseResponse([{ id: 'c1', name: 'test_tool', arguments: {} }]);
      }),
    };

    const loop = new ToolLoopAgent({
      agent,
      tools: [makeTool()],
      guardrails: { total_timeout: 0.01 },
    });
    const result = await loop.run({ task: 'slow' });

    expect(result.stop_reason).toBe(StopReason.TIMEOUT);
  });

  test(`manifest-trace: ${unitFile}::TestToolFiltering.test_denied_tool`, async () => {
    const dangerousExecute = vi.fn(async () => ({ content: 'executed dangerous tool', is_error: false }));
    const agent = {
      call: vi
        .fn()
        .mockResolvedValueOnce(makeToolUseResponse([{ id: 'c1', name: 'dangerous', arguments: {} }]))
        .mockResolvedValueOnce(makeResponse({ content: 'ok' })),
    };

    const loop = new ToolLoopAgent({
      agent,
      tools: [makeTool('dangerous', dangerousExecute)],
      guardrails: { denied_tools: ['dangerous'] },
    });
    const result = await loop.run({ task: 'test' });

    expect(result.stop_reason).toBe(StopReason.COMPLETE);
    const toolMessages = result.messages.filter((m) => m.role === 'tool');
    expect(toolMessages).toHaveLength(1);
    expect(toolMessages[0]?.content).toContain('not allowed');
    expect(dangerousExecute).not.toHaveBeenCalled();
  });

  test(`manifest-trace: ${unitFile}::TestToolFiltering.test_allowed_tools_blocks_unlisted`, async () => {
    const badExecute = vi.fn(async () => ({ content: 'bad tool executed', is_error: false }));
    const agent = {
      call: vi
        .fn()
        .mockResolvedValueOnce(makeToolUseResponse([{ id: 'c1', name: 'bad_tool', arguments: {} }]))
        .mockResolvedValueOnce(makeResponse({ content: 'ok' })),
    };

    const loop = new ToolLoopAgent({
      agent,
      tools: [makeTool('bad_tool', badExecute), makeTool('good_tool')],
      guardrails: { allowed_tools: ['good_tool'] },
    });
    const result = await loop.run({ task: 'test' });

    const toolMessages = result.messages.filter((m) => m.role === 'tool');
    expect(toolMessages[0]?.content).toContain('not allowed');
    expect(badExecute).not.toHaveBeenCalled();
  });

  test(`manifest-trace: ${unitFile}::TestErrorHandling.test_unknown_tool`, async () => {
    const agent = {
      call: vi
        .fn()
        .mockResolvedValueOnce(makeToolUseResponse([{ id: 'c1', name: 'nonexistent', arguments: {} }]))
        .mockResolvedValueOnce(makeResponse({ content: 'ok' })),
    };

    const loop = new ToolLoopAgent({
      agent,
      tools: [makeTool('other_tool')],
    });
    const result = await loop.run({ task: 'test' });

    const toolMessages = result.messages.filter((m) => m.role === 'tool');
    expect(toolMessages[0]?.content).toContain('Unknown tool');
  });

  test(`manifest-trace: ${unitFile}::TestErrorHandling.test_tool_exception`, async () => {
    const agent = {
      call: vi
        .fn()
        .mockResolvedValueOnce(makeToolUseResponse([{ id: 'c1', name: 'fail', arguments: {} }]))
        .mockResolvedValueOnce(makeResponse({ content: 'recovered' })),
    };

    const loop = new ToolLoopAgent({
      agent,
      tools: [
        makeTool('fail', async () => {
          throw new Error('boom');
        }),
      ],
    });
    const result = await loop.run({ task: 'test' });

    expect(result.stop_reason).toBe(StopReason.COMPLETE);
    const toolMessages = result.messages.filter((m) => m.role === 'tool');
    expect(toolMessages[0]?.content).toContain('boom');
  });

  test(`manifest-trace: ${unitFile}::TestErrorHandling.test_tool_timeout`, async () => {
    const slowTool = makeTool('slow', async () => {
      await new Promise((resolve) => setTimeout(resolve, 50));
      return { content: 'done', is_error: false };
    });

    const agent = {
      call: vi
        .fn()
        .mockResolvedValueOnce(makeToolUseResponse([{ id: 'c1', name: 'slow', arguments: {} }]))
        .mockResolvedValueOnce(makeResponse({ content: 'ok' })),
    };

    const loop = new ToolLoopAgent({
      agent,
      tools: [slowTool],
      guardrails: { tool_timeout: 0.01 },
    });
    const result = await loop.run({ task: 'test' });

    const toolMessages = result.messages.filter((m) => m.role === 'tool');
    expect(toolMessages[0]?.content).toContain('timed out');
  });

  test(`manifest-trace: ${unitFile}::TestErrorHandling.test_llm_error`, async () => {
    const agent = {
      call: vi.fn().mockResolvedValue(
        makeResponse({
          content: undefined,
          finish_reason: FinishReason.ERROR,
          error: {
            error_type: 'ServerError',
            message: 'something went wrong',
            status_code: 500,
            retryable: true,
          },
        }),
      ),
    };

    const loop = new ToolLoopAgent({ agent, tools: [makeTool()] });
    const result = await loop.run({ task: 'test' });

    expect(result.stop_reason).toBe(StopReason.ERROR);
    expect(result.error).toBe('something went wrong');
  });

  test(`manifest-trace: ${unitFile}::TestToolProvider.test_simple_tool_provider`, async () => {
    const provider = new SimpleToolProvider([makeTool('greet')]);
    const defs = provider.get_tool_definitions();

    expect(defs).toHaveLength(1);
    expect(defs[0]?.function?.name).toBe('greet');

    const result = await provider.execute_tool('greet', 'id1', { x: 'hello' });
    expect(result.content).toContain('hello');
  });

  test(`manifest-trace: ${unitFile}::TestToolProvider.test_simple_provider_unknown_tool`, async () => {
    const provider = new SimpleToolProvider([makeTool('known')]);
    const result = await provider.execute_tool('unknown', 'id1', {});

    expect(result.is_error).toBe(true);
    expect(result.content).toContain('Unknown tool');
  });

  test(`manifest-trace: ${unitFile}::TestToolProvider.test_tool_loop_agent_with_provider`, async () => {
    class CustomProvider implements ToolProvider {
      get_tool_definitions(): Array<Record<string, any>> {
        return [
          {
            type: 'function',
            function: { name: 'custom', description: 'custom tool', parameters: {} },
          },
        ];
      }
      async execute_tool(name: string): Promise<ToolResult> {
        return { content: `custom result: ${name}`, is_error: false };
      }
    }

    const agent = {
      call: vi
        .fn()
        .mockResolvedValueOnce(makeToolUseResponse([{ id: 'c1', name: 'custom', arguments: {} }]))
        .mockResolvedValueOnce(makeResponse({ content: 'done' })),
    };

    const loop = new ToolLoopAgent({ agent, toolProvider: new CustomProvider() });
    const result = await loop.run({ task: 'test' });

    expect(result.stop_reason).toBe(StopReason.COMPLETE);
    expect(result.tool_calls_count).toBe(1);
  });

  test(`manifest-trace: ${unitFile}::TestToolProvider.test_must_provide_tools_or_provider`, () => {
    const agent = { call: vi.fn() };

    expect(() => new ToolLoopAgent({ agent } as any)).toThrow(/Either 'tools' or 'toolProvider'/);
  });

  test(`manifest-trace: ${unitFile}::TestUsageAggregation.test_usage_accumulated_across_turns`, async () => {
    const usage = makeUsage({
      input_tokens: 100,
      output_tokens: 50,
      total_tokens: 150,
      cost: { input: 0.001, output: 0.002, cache_read: 0, cache_write: 0, total: 0.01 },
    });

    const response1 = makeToolUseResponse([{ id: 'c1', name: 'test_tool', arguments: {} }]);
    response1.usage = usage;
    const response2 = makeResponse({ content: 'done' });
    response2.usage = usage;

    const agent = {
      call: vi.fn().mockResolvedValueOnce(response1).mockResolvedValueOnce(response2),
    };

    const loop = new ToolLoopAgent({ agent, tools: [makeTool()] });
    const result = await loop.run({ task: 'test' });

    expect(result.usage.api_calls).toBe(2);
    expect(result.usage.input_tokens).toBe(200);
    expect(result.usage.output_tokens).toBe(100);
    expect(result.usage.total_cost).toBeCloseTo(0.02);
  });

  test(`manifest-trace: ${unitFile}::TestSteering.test_steering_messages_injected`, async () => {
    const steering = vi.fn(async () => [{ role: 'user', content: 'keep going' }]);

    const agent = {
      call: vi
        .fn()
        .mockResolvedValueOnce(makeToolUseResponse([{ id: 'c1', name: 'test_tool', arguments: {} }]))
        .mockResolvedValueOnce(makeResponse({ content: 'done' })),
    };

    const loop = new ToolLoopAgent({
      agent,
      tools: [makeTool()],
      steering,
    });
    const result = await loop.run({ task: 'test' });

    const steeringMessages = result.messages.filter((m) => m.content === 'keep going');
    expect(steering).toHaveBeenCalledTimes(1);
    expect(steeringMessages).toHaveLength(1);
  });

  test(`manifest-trace: ${integrationFile}::TestCompleteToolLoopWithFileIO.test_read_then_write`, async () => {
    const workDir = await newTempDir();
    await writeFile(join(workDir, 'input.txt'), 'Hello world from integration test', 'utf-8');

    const provider = new FilesystemToolProvider(workDir);
    const { machine } = makeScriptedMachine({
      config: toolLoopMachineConfig(),
      toolProvider: provider,
      script: [
        tr([{ id: 'c1', name: 'read_file', arguments: { path: 'input.txt' } }]),
        tr([
          {
            id: 'c2',
            name: 'write_file',
            arguments: {
              path: 'summary.txt',
              content: 'Summary: Hello world from integration test',
            },
          },
        ]),
        fr('I read the file and wrote a summary.'),
      ],
    });

    const result = await machine.execute({ task: 'summarize input.txt' });

    const summary = await readFile(join(workDir, 'summary.txt'), 'utf-8');
    expect(summary).toContain('Hello world');
    expect(String(result.tool_count)).toBe('2');
    expect(result.stop_reason).toBe('complete');
    expect(String(result.result).toLowerCase()).toContain('summary');

    expect(provider.callLog).toHaveLength(2);
    expect(provider.callLog[0]?.name).toBe('read_file');
    expect(provider.callLog[1]?.name).toBe('write_file');
  });

  test(`manifest-trace: ${integrationFile}::TestHookDrivenFileTracking.test_hooks_track_modified_files`, async () => {
    const workDir = await newTempDir();
    const filesTracked: string[] = [];

    const provider = new FilesystemToolProvider(workDir);
    const hooks = {
      get_tool_provider: () => provider,
      on_tool_result: (_stateName: string, toolResult: any, context: Record<string, any>) => {
        if (toolResult.name === 'write_file' && !toolResult.is_error) {
          const path = String(toolResult.arguments?.path ?? '');
          context.files_modified = context.files_modified ?? [];
          if (!context.files_modified.includes(path)) {
            context.files_modified.push(path);
          }
          filesTracked.push(path);
        }
        return context;
      },
    };

    const config = toolLoopMachineConfig({
      outputToContext: {
        result: '{{ output.content }}',
        tool_count: '{{ output._tool_calls_count }}',
        stop_reason: '{{ output._tool_loop_stop }}',
        files: '{{ context.files_modified }}',
      },
    });

    const { machine } = makeScriptedMachine({
      config,
      hooks,
      script: [
        tr([{ id: 'c1', name: 'write_file', arguments: { path: 'a.txt', content: 'aaa' } }]),
        tr([{ id: 'c2', name: 'write_file', arguments: { path: 'b.txt', content: 'bbb' } }]),
        tr([{ id: 'c3', name: 'write_file', arguments: { path: 'a.txt', content: 'aaa v2' } }]),
        fr('Wrote three files.'),
      ],
    });

    const result = await machine.execute({ task: 'write files' });

    expect(await readFile(join(workDir, 'a.txt'), 'utf-8')).toBe('aaa v2');
    expect(await readFile(join(workDir, 'b.txt'), 'utf-8')).toBe('bbb');

    expect(filesTracked).toEqual(['a.txt', 'b.txt', 'a.txt']);
    expect(String(result.tool_count)).toBe('3');
  });

  test(`manifest-trace: ${integrationFile}::TestMidLoopConditionalTransition.test_write_to_sensitive_path_triggers_review`, async () => {
    const workDir = await newTempDir();
    const provider = new FilesystemToolProvider(workDir);

    const hooks = {
      get_tool_provider: () => provider,
      on_tool_result: (_stateName: string, toolResult: any, context: Record<string, any>) => {
        if (toolResult.name === 'write_file') {
          const path = String(toolResult.arguments?.path ?? '');
          if (path.includes('sensitive')) {
            context.needs_review = true;
            context.sensitive_path = path;
          }
        }
        return context;
      },
    };

    const config = toolLoopMachineConfig({
      workTransitions: [
        { condition: 'context.needs_review', to: 'review' },
        { to: 'done' },
      ],
      extraStates: {
        review: {
          type: 'final',
          output: {
            result: 'blocked',
            sensitive_path: '{{ context.sensitive_path }}',
          },
        },
      },
    });

    const { machine } = makeScriptedMachine({
      config,
      hooks,
      script: [
        tr([
          { id: 'c1', name: 'write_file', arguments: { path: 'safe.txt', content: 'ok' } },
          { id: 'c2', name: 'write_file', arguments: { path: 'sensitive/config.yml', content: 'secret' } },
          { id: 'c3', name: 'write_file', arguments: { path: 'other.txt', content: 'more' } },
        ]),
        fr('unreachable'),
      ],
    });

    const result = await machine.execute({ task: 'write stuff' });

    expect(result.result).toBe('blocked');
    expect(result.sensitive_path).toBe('sensitive/config.yml');
    await expect(readFile(join(workDir, 'safe.txt'), 'utf-8')).resolves.toBeDefined();
    await expect(readFile(join(workDir, 'sensitive/config.yml'), 'utf-8')).resolves.toBeDefined();
    await expect(readFile(join(workDir, 'other.txt'), 'utf-8')).rejects.toThrow();
  });

  test(`manifest-trace: ${integrationFile}::TestGuardrailsStopRunaway.test_max_turns_stops_loop`, async () => {
    const workDir = await newTempDir();
    const provider = new FilesystemToolProvider(workDir);

    const script = Array.from({ length: 20 }, (_, index) =>
      tr([{ id: `c${index}`, name: 'list_files', arguments: { dir: '.' } }]),
    );

    const { machine } = makeScriptedMachine({
      config: toolLoopMachineConfig({ toolLoop: { max_turns: 3, total_timeout: 600 } }),
      toolProvider: provider,
      script,
    });

    const result = await machine.execute({ task: 'keep listing' });

    expect(result.stop_reason).toBe('max_turns');
    expect(Number(result.tool_count)).toBe(3);
  });

  test(`manifest-trace: ${integrationFile}::TestDeniedToolsIntegration.test_denied_tool_not_executed`, async () => {
    const workDir = await newTempDir();
    const provider = new FilesystemToolProvider(workDir);

    const { machine } = makeScriptedMachine({
      config: toolLoopMachineConfig({ toolLoop: { denied_tools: ['write_file'], total_timeout: 600 } }),
      toolProvider: provider,
      script: [
        tr([
          { id: 'c1', name: 'read_file', arguments: { path: 'x.txt' } },
          { id: 'c2', name: 'write_file', arguments: { path: 'danger.txt', content: 'bad' } },
        ]),
        fr('I tried to write but was denied.'),
      ],
    });

    await machine.execute({ task: 'test' });

    const executedTools = provider.callLog.map((entry) => entry.name);
    expect(executedTools).toContain('read_file');
    expect(executedTools).not.toContain('write_file');
    await expect(readFile(join(workDir, 'danger.txt'), 'utf-8')).rejects.toThrow();
  });

  test(`manifest-trace: ${integrationFile}::TestCrashResumeMidToolLoop.test_resume_after_crash_in_hook`, async () => {
    const workDir = await newTempDir();
    const checkpointDir = await newTempDir();
    const provider = new FilesystemToolProvider(workDir);
    const persistence = new LocalFileBackend(checkpointDir);

    class CrashingHooks {
      private resultCount = 0;

      get_tool_provider() {
        return provider;
      }

      on_tool_result(_stateName: string, _toolResult: any, context: Record<string, any>) {
        this.resultCount += 1;
        if (this.resultCount === 2) {
          throw new Error('Simulated crash in hook!');
        }
        return context;
      }
    }

    const config = toolLoopMachineConfig();
    const { machine: machine1 } = makeScriptedMachine({
      config,
      hooks: new CrashingHooks(),
      persistence,
      script: [
        tr([
          { id: 'c1', name: 'write_file', arguments: { path: 'file1.txt', content: 'one' } },
          { id: 'c2', name: 'write_file', arguments: { path: 'file2.txt', content: 'two' } },
        ]),
        fr('done'),
      ],
    });

    const executionId = machine1.executionId;

    await expect(machine1.execute({ task: 'write files' })).rejects.toThrow('Simulated crash in hook');

    expect(await readFile(join(workDir, 'file1.txt'), 'utf-8')).toBe('one');
    expect(await readFile(join(workDir, 'file2.txt'), 'utf-8')).toBe('two');

    const snapshot = await new CheckpointManager(persistence).restore(executionId);

    expect(snapshot).not.toBeNull();
    expect(snapshot?.tool_loop_state).toBeDefined();
    expect((snapshot?.tool_loop_state as any).tool_calls_count).toBeGreaterThanOrEqual(1);
    expect((snapshot?.tool_loop_state as any).chain.length).toBeGreaterThanOrEqual(2);
  });

  test(`manifest-trace: ${integrationFile}::TestCheckpointToolLoopState.test_checkpoint_has_chain_and_metrics`, async () => {
    const workDir = await newTempDir();
    await writeFile(join(workDir, 'data.txt'), 'test data', 'utf-8');

    const backend = new MemoryBackend();
    const provider = new FilesystemToolProvider(workDir);

    const { machine } = makeScriptedMachine({
      config: toolLoopMachineConfig(),
      toolProvider: provider,
      persistence: backend,
      script: [
        tr([{ id: 'c1', name: 'read_file', arguments: { path: 'data.txt' } }], undefined, 0.005),
        tr([{ id: 'c2', name: 'list_files', arguments: { dir: '.' } }], undefined, 0.003),
        fr('Analysis complete.', 0.002),
      ],
    });

    await machine.execute({ task: 'analyze' });

    const keys = await backend.list(machine.executionId);
    const snapshots = (
      await Promise.all(keys.map(async (key) => backend.load(key)))
    ).filter((snapshot): snapshot is NonNullable<typeof snapshot> => snapshot != null);

    const toolCallSnapshots = snapshots.filter((snapshot) => snapshot.event === 'tool_call');
    expect(toolCallSnapshots.length).toBeGreaterThanOrEqual(1);

    const last = toolCallSnapshots[toolCallSnapshots.length - 1]!;
    expect(last.tool_loop_state).toBeDefined();

    const tls = last.tool_loop_state as any;
    expect(tls.tool_calls_count).toBe(2);
    expect(tls.turns).toBe(2);
    expect(tls.loop_cost).toBeCloseTo(0.008);

    const roles = (tls.chain as Array<Record<string, any>>).map((m) => m.role);
    expect(roles).toContain('user');
    expect(roles).toContain('assistant');
    expect(roles).toContain('tool');
  });

  test(`manifest-trace: ${integrationFile}::TestStandaloneToolLoopAgent.test_standalone_read_write_cycle`, async () => {
    const workDir = await newTempDir();
    await writeFile(join(workDir, 'readme.md'), '# Project\nA test project.', 'utf-8');

    const provider = new FilesystemToolProvider(workDir);
    const responses = [
      makeToolUseResponse([{ id: 'c1', name: 'read_file', arguments: { path: 'readme.md' } }]),
      makeToolUseResponse([
        {
          id: 'c2',
          name: 'write_file',
          arguments: { path: 'summary.txt', content: 'This is a test project.' },
        },
      ]),
      makeResponse({ content: 'I summarized the readme.', finish_reason: FinishReason.STOP }),
    ];
    const agent = {
      call: vi.fn().mockImplementation(async () => responses.shift()),
    };

    const loopAgent = new ToolLoopAgent({
      agent,
      toolProvider: provider,
      guardrails: { max_turns: 10, tool_timeout: 5.0 },
    });

    const result = await loopAgent.run({ task: 'summarize readme.md' });

    expect(result.stop_reason).toBe(StopReason.COMPLETE);
    expect(result.tool_calls_count).toBe(2);
    expect(result.turns).toBe(3);
    expect(await readFile(join(workDir, 'summary.txt'), 'utf-8')).toBe('This is a test project.');
  });

  test(`manifest-trace: ${integrationFile}::TestMultiStateMachineWithToolLoop.test_tool_loop_then_review_action`, async () => {
    const workDir = await newTempDir();
    const provider = new FilesystemToolProvider(workDir);

    const config = {
      spec: 'flatmachine',
      spec_version: '1.1.1',
      data: {
        name: 'multi-state',
        context: { task: '{{ input.task }}' },
        agents: { coder: './agent.yml' },
        states: {
          start: { type: 'initial', transitions: [{ to: 'work' }] },
          work: {
            agent: 'coder',
            tool_loop: true,
            input: { task: '{{ context.task }}' },
            output_to_context: { result: '{{ output.content }}' },
            transitions: [{ to: 'verify' }],
          },
          verify: {
            action: 'verify_output',
            transitions: [
              { condition: 'context.output_exists', to: 'done' },
              { to: 'fail' },
            ],
          },
          done: {
            type: 'final',
            output: {
              result: '{{ context.result }}',
              output_size: '{{ context.output_size }}',
            },
          },
          fail: {
            type: 'final',
            output: { result: 'verification failed' },
          },
        },
      },
    };

    const hooks = {
      onAction: (actionName: string, context: Record<string, any>) => {
        if (actionName === 'verify_output') {
          const outputPath = join(workDir, 'output.txt');
          return readFile(outputPath, 'utf-8')
            .then((content) => ({
              ...context,
              output_exists: true,
              output_size: content.length,
            }))
            .catch(() => ({
              ...context,
              output_exists: false,
            }));
        }
        return context;
      },
    };

    const { machine } = makeScriptedMachine({
      config,
      hooks,
      toolProvider: provider,
      script: [
        tr([
          {
            id: 'c1',
            name: 'write_file',
            arguments: {
              path: 'output.txt',
              content: 'generated content',
            },
          },
        ]),
        fr('I wrote the output file.'),
      ],
    });

    const result = await machine.execute({ task: 'generate output' });

    expect(String(result.result)).toContain('I wrote the output');
    expect(Number(result.output_size)).toBe('generated content'.length);
  });

  test(`manifest-trace: ${integrationFile}::TestChainPreservation.test_chain_saved_to_context`, async () => {
    const workDir = await newTempDir();
    const provider = new FilesystemToolProvider(workDir);

    const savedContext: Record<string, any> = {};
    const hooks = {
      onStateExit: (stateName: string, context: Record<string, any>, output: any) => {
        if (stateName === 'work') {
          Object.assign(savedContext, context);
        }
        return output;
      },
    };

    const { machine } = makeScriptedMachine({
      config: toolLoopMachineConfig(),
      hooks,
      toolProvider: provider,
      script: [tr([{ id: 'c1', name: 'list_files', arguments: { dir: '.' } }]), fr('Listed the files.')],
    });

    await machine.execute({ task: 'list' });

    const chain = savedContext._tool_loop_chain as Array<Record<string, any>> | undefined;
    expect(chain).toBeDefined();
    expect(chain?.length).toBeGreaterThanOrEqual(3);
    const roles = chain?.map((message) => message.role) ?? [];
    expect(roles).toContain('user');
    expect(roles).toContain('tool');
  });

  test(`manifest-trace: ${integrationFile}::TestCrossStateChainIsolation.test_second_tool_loop_state_starts_fresh`, async () => {
    const workDir = await newTempDir();
    const provider = new FilesystemToolProvider(workDir);

    const config = {
      spec: 'flatmachine',
      spec_version: '1.1.1',
      data: {
        name: 'cross-state-chain-isolation',
        context: { task: '{{ input.task }}' },
        agents: { coder: './agent.yml' },
        states: {
          start: { type: 'initial', transitions: [{ to: 'work_a' }] },
          work_a: {
            agent: 'coder',
            tool_loop: true,
            input: {
              task: '{{ context.task }}',
              phase: 'A',
            },
            output_to_context: { result_a: '{{ output.content }}' },
            transitions: [{ to: 'work_b' }],
          },
          work_b: {
            agent: 'coder',
            tool_loop: true,
            input: {
              task: '{{ context.task }}',
              phase: 'B',
            },
            output_to_context: { result_b: '{{ output.content }}' },
            transitions: [{ to: 'done' }],
          },
          done: {
            type: 'final',
            output: {
              result_a: '{{ context.result_a }}',
              result_b: '{{ context.result_b }}',
            },
          },
        },
      },
    };

    const { machine, executor } = makeScriptedMachine({
      config,
      toolProvider: provider,
      script: [
        { content: 'phase A done', finish_reason: 'stop', rendered_user_prompt: 'rendered-a' },
        { content: 'phase B done', finish_reason: 'stop', rendered_user_prompt: 'rendered-b' },
      ],
    });

    const result = await machine.execute({ task: 'integration task' });

    expect(result.result_a).toBe('phase A done');
    expect(result.result_b).toBe('phase B done');
    expect(executor.calls.length).toBe(2);

    const first = executor.calls[0]!;
    const second = executor.calls[1]!;

    expect(first.method).toBe('execute_with_tools');
    expect(first.inputData).toEqual({ task: 'integration task', phase: 'A' });
    expect(first.messages).toBeUndefined();

    expect(second.method).toBe('execute_with_tools');
    expect(second.inputData).toEqual({ task: 'integration task', phase: 'B' });
    expect(second.messages).toBeUndefined();
  });
});

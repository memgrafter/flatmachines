import { describe, expect, test, vi } from 'vitest';
import {
  FlatMachine,
  MemoryBackend,
  CompositeHooks,
  coerceAgentResult,
  type AgentExecutor,
  type AgentResult,
  type MachineConfig,
  type ToolProvider,
  type ToolResult,
} from '../../src';
import { FlatAgentExecutor } from '../../src/adapters/flatagent_adapter';
import * as SDK from '../../src';

type ToolCall = {
  id: string;
  name?: string;
  tool?: string;
  arguments: Record<string, any>;
};

function makeAgentResult(options: {
  content?: string;
  finish_reason?: string;
  tool_calls?: ToolCall[];
  error?: Record<string, any> | null;
  cost?: Record<string, number> | number | null;
  usage?: Record<string, any> | null;
  rendered_user_prompt?: string | null;
} = {}): AgentResult {
  return {
    content: options.content ?? 'done',
    finish_reason: options.finish_reason ?? 'stop',
    tool_calls: options.tool_calls ?? null,
    error: options.error ?? null,
    cost: options.cost ?? { total: 0.001 },
    usage: options.usage ?? { api_calls: 1, input_tokens: 10, output_tokens: 5 },
    rendered_user_prompt: options.rendered_user_prompt ?? 'rendered prompt',
  };
}

function makeToolResult(toolCalls: ToolCall[], options: { content?: string; cost?: Record<string, number> | number } = {}): AgentResult {
  return makeAgentResult({
    content: options.content,
    finish_reason: 'tool_use',
    tool_calls: toolCalls,
    cost: options.cost,
  });
}

class MockToolProvider implements ToolProvider {
  calls: Array<{ name: string; tool_call_id: string; arguments: Record<string, any> }> = [];

  constructor(
    private readonly results: Record<string, ToolResult> = {},
    private readonly definitions: Array<Record<string, any>> = [],
  ) {}

  get_tool_definitions(): Array<Record<string, any>> {
    return this.definitions;
  }

  async execute_tool(name: string, tool_call_id: string, args: Record<string, any>): Promise<ToolResult> {
    this.calls.push({ name, tool_call_id, arguments: args });
    return this.results[name] ?? { content: `executed ${name}(${JSON.stringify(args)})`, is_error: false };
  }
}

class MockExecutor implements AgentExecutor {
  calls: Array<Record<string, any>> = [];
  private idx = 0;

  constructor(private readonly responses: AgentResult[]) {}

  get metadata(): Record<string, any> {
    return {};
  }

  async execute(inputData: Record<string, any>, context?: Record<string, any>): Promise<AgentResult> {
    return this.next('execute', { inputData, context });
  }

  async execute_with_tools(
    inputData: Record<string, any>,
    tools: Array<Record<string, any>>,
    messages?: Array<Record<string, any>> | null,
    context?: Record<string, any>,
  ): Promise<AgentResult> {
    return this.next('execute_with_tools', { inputData, tools, messages, context });
  }

  private next(method: string, payload: Record<string, any>): AgentResult {
    this.calls.push({ method, ...payload });
    if (this.idx >= this.responses.length) return makeAgentResult({ content: 'fallback', finish_reason: 'stop' });
    const value = this.responses[this.idx]!;
    this.idx += 1;
    return value;
  }
}

class NoToolsExecutor implements AgentExecutor {
  get metadata(): Record<string, any> {
    return {};
  }

  async execute(): Promise<AgentResult> {
    return makeAgentResult({ content: 'done without tools', finish_reason: 'stop' });
  }
}

function makeMachineConfig(options: {
  tool_loop?: boolean | Record<string, any>;
  transitions?: Array<{ condition?: string; to: string }>;
  output_to_context?: Record<string, any>;
  agent_inline?: Record<string, any>;
} = {}): MachineConfig {
  const stateDef: Record<string, any> = {
    agent: 'coder',
    tool_loop: options.tool_loop ?? true,
    input: { task: '{{ context.task }}' },
    transitions: options.transitions ?? [{ to: 'done' }],
  };

  if (options.output_to_context) stateDef.output_to_context = options.output_to_context;

  return {
    spec: 'flatmachine',
    spec_version: '1.1.1',
    data: {
      name: 'test-tool-loop-machine',
      context: { task: '{{ input.task }}' },
      agents: options.agent_inline ? ({ coder: options.agent_inline } as any) : { coder: './agent.yml' },
      states: {
        start: { type: 'initial', transitions: [{ to: 'work' }] },
        work: stateDef,
        done: {
          type: 'final',
          output: {
            result: '{{ context.result }}',
            stop: '{{ context.stop }}',
            loop_cost: '{{ context.loop_cost }}',
            calls: '{{ context.calls }}',
          },
        },
      },
    },
  };
}

function buildMachine(options: {
  responses: AgentResult[];
  toolProvider?: ToolProvider;
  hooks?: Record<string, any>;
  config?: MachineConfig;
  persistence?: MemoryBackend;
}) {
  const machine = new FlatMachine({
    config: options.config ?? makeMachineConfig(),
    toolProvider: options.toolProvider,
    hooks: options.hooks as any,
    persistence: options.persistence,
  } as any);
  const executor = new MockExecutor(options.responses);
  (machine as any).executors.set('coder', executor);
  return { machine, executor };
}

function loadSnapshots(backend: MemoryBackend, executionId: string): any[] {
  const store = (backend as any).store as Map<string, any>;
  return [...store.entries()]
    .filter(([key]) => key.startsWith(`${executionId}/`))
    .map(([, snapshot]) => snapshot);
}

describe('tool-loop-machine parity (python test_tool_loop_machine.py manifest-owned)', () => {
  const pyFile = 'sdk/python/tests/unit/test_tool_loop_machine.py';

  describe('TestBasicMachineToolLoop', () => {
    test(`manifest-trace: ${pyFile}::TestBasicMachineToolLoop.test_single_tool_call_then_complete`, async () => {
      const provider = new MockToolProvider();
      const { machine, executor } = buildMachine({
        responses: [
          makeToolResult([{ id: 'c1', name: 'read_file', tool: 'read_file', arguments: { path: 'x' } }]),
          makeAgentResult({ content: 'file analyzed' }),
        ],
        toolProvider: provider,
      });

      await machine.execute({ task: 'read a file' });

      expect(provider.calls[0]?.name).toBe('read_file');
      expect(executor.calls[0]?.method).toBe('execute_with_tools');
      expect(executor.calls[1]?.method).toBe('execute_with_tools');
    });

    test(`manifest-trace: ${pyFile}::TestBasicMachineToolLoop.test_multi_round_tool_calls`, async () => {
      const provider = new MockToolProvider();
      const { machine, executor } = buildMachine({
        responses: [
          makeToolResult([{ id: 'c1', name: 'read_file', tool: 'read_file', arguments: {} }]),
          makeToolResult([{ id: 'c2', name: 'write_file', tool: 'write_file', arguments: {} }]),
          makeToolResult([{ id: 'c3', name: 'bash', tool: 'bash', arguments: {} }]),
          makeAgentResult({ content: 'all done' }),
        ],
        toolProvider: provider,
      });

      await machine.execute({ task: 'complex work' });

      expect(provider.calls).toHaveLength(3);
      expect(executor.calls).toHaveLength(4);
    });

    test(`manifest-trace: ${pyFile}::TestBasicMachineToolLoop.test_multiple_tools_in_single_response`, async () => {
      const provider = new MockToolProvider();
      const { machine } = buildMachine({
        responses: [
          makeToolResult([
            { id: 'c1', name: 'read_file', tool: 'read_file', arguments: { path: 'a' } },
            { id: 'c2', name: 'read_file', tool: 'read_file', arguments: { path: 'b' } },
            { id: 'c3', name: 'read_file', tool: 'read_file', arguments: { path: 'c' } },
          ]),
          makeAgentResult({ content: 'read all three' }),
        ],
        toolProvider: provider,
      });

      await machine.execute({ task: 'read three files' });

      expect(provider.calls).toHaveLength(3);
    });

    test(`manifest-trace: ${pyFile}::TestBasicMachineToolLoop.test_output_to_context_mapping`, async () => {
      const provider = new MockToolProvider();
      const cfg = makeMachineConfig({
        output_to_context: {
          result: '{{ output.content }}',
          calls: '{{ output._tool_calls_count }}',
        },
      });
      const { machine } = buildMachine({
        responses: [
          makeToolResult([{ id: 'c1', name: 'test', tool: 'test', arguments: {} }]),
          makeAgentResult({ content: 'final answer' }),
        ],
        config: cfg,
        toolProvider: provider,
      });

      const result = await machine.execute({ task: 'work' });

      expect(result.result).toBe('final answer');
      expect(result.calls).toBe(1);
    });

    test(`manifest-trace: ${pyFile}::TestBasicMachineToolLoop.test_no_tool_calls_completes_immediately`, async () => {
      const provider = new MockToolProvider();
      const { machine, executor } = buildMachine({
        responses: [makeAgentResult({ content: 'immediate answer', finish_reason: 'stop' })],
        toolProvider: provider,
      });

      await machine.execute({ task: 'simple question' });

      expect(provider.calls).toHaveLength(0);
      expect(executor.calls).toHaveLength(1);
    });
  });

  describe('TestToolLoopChainScoping', () => {
    test(`manifest-trace: ${pyFile}::TestToolLoopChainScoping.test_cross_state_tool_loop_chain_isolation`, async () => {
      const cfg: MachineConfig = {
        spec: 'flatmachine',
        spec_version: '1.1.1',
        data: {
          name: 'chain-scope',
          context: {},
          agents: { coder: './agent.yml' },
          states: {
            start: { type: 'initial', transitions: [{ to: 'work_a' }] },
            work_a: {
              agent: 'coder',
              tool_loop: true,
              input: { task: 'state-a' },
              transitions: [{ to: 'work_b' }],
            },
            work_b: {
              agent: 'coder',
              tool_loop: true,
              input: { task: 'state-b' },
              transitions: [{ to: 'done' }],
            },
            done: { type: 'final', output: { ok: true } },
          },
        },
      };

      const { machine, executor } = buildMachine({
        config: cfg,
        responses: [
          makeAgentResult({ content: 'a', rendered_user_prompt: 'prompt-a' }),
          makeAgentResult({ content: 'b', rendered_user_prompt: 'prompt-b' }),
        ],
        toolProvider: new MockToolProvider(),
      });

      await machine.execute({});

      expect(executor.calls).toHaveLength(2);
      expect(executor.calls[0]?.inputData).toEqual({ task: 'state-a' });
      expect(executor.calls[0]?.messages).toBeUndefined();
      expect(executor.calls[1]?.inputData).toEqual({ task: 'state-b' });
      expect(executor.calls[1]?.messages).toBeUndefined();
    });

    test(`manifest-trace: ${pyFile}::TestToolLoopChainScoping.test_same_state_continuation_reuses_chain`, async () => {
      const { machine, executor } = buildMachine({
        responses: [makeAgentResult({ content: 'continued' })],
        toolProvider: new MockToolProvider(),
      });

      (machine as any).context = {
        task: 'resume',
        _tool_loop_chain: [
          { role: 'user', content: 'prior prompt' },
          { role: 'assistant', content: 'prior answer' },
        ],
        _tool_loop_chain_state: 'work',
        _tool_loop_chain_agent: 'coder',
      };
      (machine as any).input = {};

      const [updatedContext] = await (machine as any).executeToolLoop('work', (machine as any).config.data.states.work);

      expect(executor.calls[0]?.inputData).toEqual({});
      expect(executor.calls[0]?.messages?.[0]?.content).toBe('prior prompt');
      expect(updatedContext._tool_loop_chain_state).toBe('work');
      expect(updatedContext._tool_loop_chain_agent).toBe('coder');
    });

    test(`manifest-trace: ${pyFile}::TestToolLoopChainScoping.test_continuation_does_not_append_synthetic_user_prompt`, async () => {
      const { machine } = buildMachine({
        responses: [makeAgentResult({ content: 'continued answer', rendered_user_prompt: 'SHOULD_NOT_APPEND' })],
        toolProvider: new MockToolProvider(),
      });

      (machine as any).context = {
        task: 'resume',
        _tool_loop_chain: [
          { role: 'user', content: 'prior prompt' },
          { role: 'assistant', content: 'prior answer' },
        ],
        _tool_loop_chain_state: 'work',
        _tool_loop_chain_agent: 'coder',
      };
      (machine as any).input = {};

      const [updatedContext] = await (machine as any).executeToolLoop('work', (machine as any).config.data.states.work);

      const finalChain = updatedContext._tool_loop_chain as Array<Record<string, any>>;
      expect(finalChain).toHaveLength(3);
      expect(finalChain.some((m) => m.role === 'user' && m.content === 'SHOULD_NOT_APPEND')).toBe(false);
    });
  });

  describe('TestMachineGuardrails', () => {
    test(`manifest-trace: ${pyFile}::TestMachineGuardrails.test_max_turns`, async () => {
      const provider = new MockToolProvider();
      const cfg = makeMachineConfig({
        tool_loop: { max_turns: 2, total_timeout: 600 },
        output_to_context: { stop: '{{ output._tool_loop_stop }}' },
      });
      const responses = Array.from({ length: 10 }).map((_, i) =>
        makeToolResult([{ id: `c${i + 1}`, name: 'test', tool: 'test', arguments: {} }]),
      );
      const { machine } = buildMachine({ responses, toolProvider: provider, config: cfg });

      const result = await machine.execute({ task: 'loop' });

      expect(result.stop).toBe('max_turns');
    });

    test(`manifest-trace: ${pyFile}::TestMachineGuardrails.test_max_tool_calls`, async () => {
      const provider = new MockToolProvider();
      const cfg = makeMachineConfig({
        tool_loop: { max_tool_calls: 2, max_turns: 100, total_timeout: 600 },
        output_to_context: { stop: '{{ output._tool_loop_stop }}' },
      });
      const { machine } = buildMachine({
        responses: [
          makeToolResult([
            { id: 'c1', name: 'test', tool: 'test', arguments: {} },
            { id: 'c2', name: 'test', tool: 'test', arguments: {} },
            { id: 'c3', name: 'test', tool: 'test', arguments: {} },
          ]),
        ],
        toolProvider: provider,
        config: cfg,
      });

      const result = await machine.execute({ task: 'test' });

      expect(provider.calls).toHaveLength(0);
      expect(result.stop).toBe('max_tool_calls');
    });

    test(`manifest-trace: ${pyFile}::TestMachineGuardrails.test_max_cost_guardrail`, async () => {
      const provider = new MockToolProvider();
      const cfg = makeMachineConfig({
        tool_loop: { max_cost: 0.005, max_turns: 100, total_timeout: 600 },
        output_to_context: { stop: '{{ output._tool_loop_stop }}' },
      });
      const { machine } = buildMachine({
        responses: [
          makeToolResult([{ id: 'c1', name: 'test', tool: 'test', arguments: {} }], { cost: { total: 0.003 } }),
          makeToolResult([{ id: 'c2', name: 'test', tool: 'test', arguments: {} }], { cost: { total: 0.003 } }),
        ],
        toolProvider: provider,
        config: cfg,
      });

      const result = await machine.execute({ task: 'expensive' });

      expect(provider.calls.length).toBeGreaterThanOrEqual(1);
      expect(result.stop).toBe('cost_limit');
    });

    test(`manifest-trace: ${pyFile}::TestMachineGuardrails.test_jinja2_guardrail_rendering`, async () => {
      const provider = new MockToolProvider();
      const cfg = makeMachineConfig({
        tool_loop: { max_turns: '{{ context.max_iters | int }}', total_timeout: 600 },
        output_to_context: { stop: '{{ output._tool_loop_stop }}' },
      });
      (cfg.data.context as Record<string, any>).max_iters = 2;
      const responses = Array.from({ length: 10 }).map((_, i) =>
        makeToolResult([{ id: `c${i + 1}`, name: 'test', tool: 'test', arguments: {} }]),
      );
      const { machine } = buildMachine({ responses, toolProvider: provider, config: cfg });

      const result = await machine.execute({ task: 'test' });

      expect(result.stop).toBe('max_turns');
      expect(provider.calls).toHaveLength(2);
    });

    test(`manifest-trace: ${pyFile}::TestMachineGuardrails.test_denied_tools`, async () => {
      const provider = new MockToolProvider();
      const cfg = makeMachineConfig({ tool_loop: { denied_tools: ['write_file'], total_timeout: 600 } });
      const { machine, executor } = buildMachine({
        responses: [
          makeToolResult([{ id: 'c1', name: 'write_file', tool: 'write_file', arguments: {} }]),
          makeAgentResult({ content: 'ok' }),
        ],
        toolProvider: provider,
        config: cfg,
      });

      await machine.execute({ task: 'try to write' });

      expect(provider.calls).toHaveLength(0);
      const secondMessages = executor.calls[1]?.messages as Array<Record<string, any>>;
      expect(secondMessages.some((m) => m.role === 'tool' && String(m.content).includes('not allowed'))).toBe(true);
    });

    test(`manifest-trace: ${pyFile}::TestMachineGuardrails.test_allowed_tools`, async () => {
      const provider = new MockToolProvider();
      const cfg = makeMachineConfig({ tool_loop: { allowed_tools: ['read_file'], total_timeout: 600 } });
      const { machine } = buildMachine({
        responses: [
          makeToolResult([
            { id: 'c1', name: 'read_file', tool: 'read_file', arguments: {} },
            { id: 'c2', name: 'write_file', tool: 'write_file', arguments: {} },
          ]),
          makeAgentResult({ content: 'ok' }),
        ],
        toolProvider: provider,
        config: cfg,
      });

      await machine.execute({ task: 'mixed tools' });

      expect(provider.calls).toHaveLength(1);
      expect(provider.calls[0]?.name).toBe('read_file');
    });
  });

  describe('TestToolLoopHooks', () => {
    test(`manifest-trace: ${pyFile}::TestToolLoopHooks.test_on_tool_calls_fires_once_per_response`, async () => {
      const hookCalls: Array<[string, number]> = [];
      const hooks = {
        on_tool_calls: (_state: string, toolCalls: any[], context: Record<string, any>) => {
          hookCalls.push(['on_tool_calls', toolCalls.length]);
          return context;
        },
      };

      const { machine } = buildMachine({
        responses: [
          makeToolResult([
            { id: 'c1', name: 'a', tool: 'a', arguments: {} },
            { id: 'c2', name: 'b', tool: 'b', arguments: {} },
          ]),
          makeAgentResult({ content: 'done' }),
        ],
        toolProvider: new MockToolProvider(),
        hooks,
      });

      await machine.execute({ task: 'test' });

      expect(hookCalls).toHaveLength(1);
      expect(hookCalls[0]).toEqual(['on_tool_calls', 2]);
    });

    test(`manifest-trace: ${pyFile}::TestToolLoopHooks.test_on_tool_result_fires_per_tool`, async () => {
      const resultHooks: string[] = [];
      const hooks = {
        on_tool_result: (_state: string, toolResult: Record<string, any>, context: Record<string, any>) => {
          resultHooks.push(String(toolResult.name));
          return context;
        },
      };

      const { machine } = buildMachine({
        responses: [
          makeToolResult([
            { id: 'c1', name: 'read_file', tool: 'read_file', arguments: {} },
            { id: 'c2', name: 'write_file', tool: 'write_file', arguments: {} },
            { id: 'c3', name: 'bash', tool: 'bash', arguments: {} },
          ]),
          makeAgentResult({ content: 'done' }),
        ],
        toolProvider: new MockToolProvider(),
        hooks,
      });

      await machine.execute({ task: 'test' });

      expect(resultHooks).toEqual(['read_file', 'write_file', 'bash']);
    });

    test(`manifest-trace: ${pyFile}::TestToolLoopHooks.test_abort_tool_loop_from_on_tool_calls`, async () => {
      const hooks = {
        on_tool_calls: (_state: string, _toolCalls: any[], context: Record<string, any>) => {
          context._abort_tool_loop = true;
          return context;
        },
      };

      const provider = new MockToolProvider();
      const { machine } = buildMachine({
        responses: [
          makeToolResult([{ id: 'c1', name: 'test', tool: 'test', arguments: {} }]),
          makeAgentResult({ content: 'unreachable' }),
        ],
        toolProvider: provider,
        hooks,
      });

      await machine.execute({ task: 'test' });

      expect(provider.calls).toHaveLength(0);
    });

    test(`manifest-trace: ${pyFile}::TestToolLoopHooks.test_abort_tool_loop_from_on_tool_result`, async () => {
      const hooks = {
        on_tool_result: (_state: string, _toolResult: Record<string, any>, context: Record<string, any>) => {
          context._abort_tool_loop = true;
          return context;
        },
      };

      const provider = new MockToolProvider();
      const { machine } = buildMachine({
        responses: [
          makeToolResult([
            { id: 'c1', name: 'a', tool: 'a', arguments: {} },
            { id: 'c2', name: 'b', tool: 'b', arguments: {} },
          ]),
          makeAgentResult({ content: 'done' }),
        ],
        toolProvider: provider,
        hooks,
      });

      await machine.execute({ task: 'test' });

      expect(provider.calls).toHaveLength(1);
      expect(provider.calls[0]?.name).toBe('a');
    });

    test(`manifest-trace: ${pyFile}::TestToolLoopHooks.test_skip_tools_by_id`, async () => {
      const hooks = {
        on_tool_calls: (_state: string, _toolCalls: any[], context: Record<string, any>) => {
          context._skip_tools = ['c2'];
          return context;
        },
      };

      const provider = new MockToolProvider();
      const { machine } = buildMachine({
        responses: [
          makeToolResult([
            { id: 'c1', name: 'a', tool: 'a', arguments: {} },
            { id: 'c2', name: 'b', tool: 'b', arguments: {} },
            { id: 'c3', name: 'c', tool: 'c', arguments: {} },
          ]),
          makeAgentResult({ content: 'done' }),
        ],
        toolProvider: provider,
        hooks,
      });

      await machine.execute({ task: 'test' });

      expect(provider.calls.map((c) => c.name)).toEqual(['a', 'c']);
    });

    test(`manifest-trace: ${pyFile}::TestToolLoopHooks.test_skip_tools_by_name`, async () => {
      const hooks = {
        on_tool_calls: (_state: string, _toolCalls: any[], context: Record<string, any>) => {
          context._skip_tools = ['b'];
          return context;
        },
      };

      const provider = new MockToolProvider();
      const { machine } = buildMachine({
        responses: [
          makeToolResult([
            { id: 'c1', name: 'a', tool: 'a', arguments: {} },
            { id: 'c2', name: 'b', tool: 'b', arguments: {} },
          ]),
          makeAgentResult({ content: 'done' }),
        ],
        toolProvider: provider,
        hooks,
      });

      await machine.execute({ task: 'test' });

      expect(provider.calls.map((c) => c.name)).toEqual(['a']);
    });

    test(`manifest-trace: ${pyFile}::TestToolLoopHooks.test_steering_messages_injection`, async () => {
      const hooks = {
        on_tool_result: (_state: string, _toolResult: Record<string, any>, context: Record<string, any>) => {
          context._steering_messages = [{ role: 'user', content: 'keep focused' }];
          return context;
        },
      };

      const { machine, executor } = buildMachine({
        responses: [
          makeToolResult([{ id: 'c1', name: 'test', tool: 'test', arguments: {} }]),
          makeAgentResult({ content: 'done' }),
        ],
        toolProvider: new MockToolProvider(),
        hooks,
      });

      await machine.execute({ task: 'test' });

      const messages = executor.calls[1]?.messages as Array<Record<string, any>>;
      expect(messages.some((m) => m.content === 'keep focused')).toBe(true);
    });

    test(`manifest-trace: ${pyFile}::TestToolLoopHooks.test_get_tool_provider_from_hooks`, async () => {
      const hookProvider = new MockToolProvider({ test: { content: 'from hooks', is_error: false } });
      const constructorProvider = new MockToolProvider({ test: { content: 'from constructor', is_error: false } });
      const hooks = {
        get_tool_provider: (_state: string) => hookProvider,
      };

      const { machine } = buildMachine({
        responses: [
          makeToolResult([{ id: 'c1', name: 'test', tool: 'test', arguments: {} }]),
          makeAgentResult({ content: 'done' }),
        ],
        toolProvider: constructorProvider,
        hooks,
      });

      await machine.execute({ task: 'test' });

      expect(hookProvider.calls).toHaveLength(1);
      expect(constructorProvider.calls).toHaveLength(0);
    });
  });

  describe('TestMidLoopTransitions', () => {
    test(`manifest-trace: ${pyFile}::TestMidLoopTransitions.test_conditional_transition_mid_batch`, async () => {
      const cfg = makeMachineConfig({
        transitions: [
          { condition: 'context.needs_review', to: 'done' },
          { to: 'done' },
        ],
      });
      const hooks = {
        on_tool_result: (_state: string, toolResult: Record<string, any>, context: Record<string, any>) => {
          if (toolResult.name === 'write_file') context.needs_review = true;
          return context;
        },
      };

      const provider = new MockToolProvider();
      const { machine } = buildMachine({
        responses: [
          makeToolResult([
            { id: 'c1', name: 'read_file', tool: 'read_file', arguments: {} },
            { id: 'c2', name: 'write_file', tool: 'write_file', arguments: {} },
            { id: 'c3', name: 'bash', tool: 'bash', arguments: {} },
          ]),
          makeAgentResult({ content: 'unreachable' }),
        ],
        toolProvider: provider,
        hooks,
        config: cfg,
      });

      await machine.execute({ task: 'test' });

      const executed = provider.calls.map((c) => c.name);
      expect(executed).toContain('read_file');
      expect(executed).toContain('write_file');
      expect(executed).not.toContain('bash');
    });

    test(`manifest-trace: ${pyFile}::TestMidLoopTransitions.test_unconditional_transition_does_not_fire_mid_loop`, async () => {
      const cfg = makeMachineConfig({ transitions: [{ to: 'done' }] });
      const provider = new MockToolProvider();
      const { machine } = buildMachine({
        responses: [
          makeToolResult([{ id: 'c1', name: 'test', tool: 'test', arguments: {} }]),
          makeToolResult([{ id: 'c2', name: 'test', tool: 'test', arguments: {} }]),
          makeAgentResult({ content: 'all done' }),
        ],
        toolProvider: provider,
        config: cfg,
      });

      await machine.execute({ task: 'test' });

      expect(provider.calls).toHaveLength(2);
    });
  });

  describe('TestToolLoopCheckpoints', () => {
    test(`manifest-trace: ${pyFile}::TestToolLoopCheckpoints.test_checkpoint_saved_per_tool_call`, async () => {
      const backend = new MemoryBackend();
      const provider = new MockToolProvider();
      const { machine } = buildMachine({
        responses: [
          makeToolResult([
            { id: 'c1', name: 'a', tool: 'a', arguments: {} },
            { id: 'c2', name: 'b', tool: 'b', arguments: {} },
          ]),
          makeAgentResult({ content: 'done' }),
        ],
        toolProvider: provider,
        persistence: backend,
      });

      await machine.execute({ task: 'test' });

      const allSnapshots = loadSnapshots(backend, machine.executionId);
      const toolCheckpoints = allSnapshots.filter((s) => s.event === 'tool_call');
      expect(toolCheckpoints).toHaveLength(1);
      const chain = toolCheckpoints[0].tool_loop_state.chain as Array<Record<string, any>>;
      const toolMsgs = chain.filter((m) => m.role === 'tool');
      expect(toolMsgs).toHaveLength(2);
    });

    test(`manifest-trace: ${pyFile}::TestToolLoopCheckpoints.test_checkpoint_contains_tool_loop_state`, async () => {
      const backend = new MemoryBackend();
      const provider = new MockToolProvider();
      const { machine } = buildMachine({
        responses: [
          makeToolResult([{ id: 'c1', name: 'test', tool: 'test', arguments: {} }]),
          makeAgentResult({ content: 'done' }),
        ],
        toolProvider: provider,
        persistence: backend,
      });

      await machine.execute({ task: 'test' });

      const allSnapshots = loadSnapshots(backend, machine.executionId);
      const toolCheckpoints = allSnapshots.filter((s) => s.event === 'tool_call');
      expect(toolCheckpoints).toHaveLength(1);

      const tls = toolCheckpoints[0].tool_loop_state;
      expect(tls).toBeDefined();
      expect(tls.chain).toBeDefined();
      expect(tls.turns).toBe(1);
      expect(tls.tool_calls_count).toBe(1);
      expect(tls.loop_cost).toBeDefined();
    });
  });

  describe('TestToolLoopErrors', () => {
    test(`manifest-trace: ${pyFile}::TestToolLoopErrors.test_non_capable_adapter_raises`, async () => {
      const machine = new FlatMachine({ config: makeMachineConfig() } as any);
      (machine as any).executors.set('coder', new NoToolsExecutor());

      await expect(machine.execute({ task: 'test' })).rejects.toThrow(/does not support/i);
    });

    test(`manifest-trace: ${pyFile}::TestToolLoopErrors.test_agent_error_raises`, async () => {
      const { machine } = buildMachine({
        responses: [
          makeAgentResult({
            finish_reason: 'error',
            error: { type: 'ServerError', message: 'model down' },
          }),
        ],
        toolProvider: new MockToolProvider(),
      });

      await expect(machine.execute({ task: 'test' })).rejects.toThrow(/model down/);
    });

    test(`manifest-trace: ${pyFile}::TestToolLoopErrors.test_no_tool_provider_returns_error_result`, async () => {
      const { machine, executor } = buildMachine({
        responses: [
          makeToolResult([{ id: 'c1', name: 'test', tool: 'test', arguments: {} }]),
          makeAgentResult({ content: 'ok' }),
        ],
      });

      await machine.execute({ task: 'test' });

      const messages = executor.calls[1]?.messages as Array<Record<string, any>>;
      const toolMessages = messages.filter((m) => m.role === 'tool');
      expect(toolMessages).toHaveLength(1);
      expect(String(toolMessages[0]?.content)).toContain('No tool provider configured');
    });
  });

  describe('TestCostTracking', () => {
    test(`manifest-trace: ${pyFile}::TestCostTracking.test_loop_cost_and_machine_total_cost`, async () => {
      const cfg = makeMachineConfig({
        output_to_context: {
          loop_cost: '{{ output._tool_loop_cost }}',
        },
      });
      const { machine } = buildMachine({
        responses: [
          makeToolResult([{ id: 'c1', name: 'test', tool: 'test', arguments: {} }], { cost: { total: 0.01 } }),
          makeAgentResult({ content: 'done', cost: { total: 0.005 } }),
        ],
        config: cfg,
        toolProvider: new MockToolProvider(),
      });

      await machine.execute({ task: 'test' });

      expect((machine as any).totalCost).toBeCloseTo(0.015, 6);
    });
  });

  describe('TestHelperMethods', () => {
    test(`manifest-trace: ${pyFile}::TestHelperMethods.test_find_conditional_transition_skips_unconditional`, () => {
      const cfg = makeMachineConfig({
        transitions: [
          { condition: 'context.flag', to: 'flagged' },
          { to: 'default' },
        ],
      });
      const machine = new FlatMachine({ config: cfg } as any);

      (machine as any).context = { flag: false };
      (machine as any).input = {};
      expect((machine as any).findConditionalTransition('work')).toBeNull();

      (machine as any).context = { flag: true };
      expect((machine as any).findConditionalTransition('work')).toBe('flagged');
    });

    test(`manifest-trace: ${pyFile}::TestHelperMethods.test_render_guardrail_number`, () => {
      const machine = new FlatMachine({ config: makeMachineConfig() } as any);
      const fn = (machine as any)._render_guardrail;
      expect(fn).toBeTypeOf('function');
      expect(fn(42, {}, Number)).toBe(42);
    });

    test(`manifest-trace: ${pyFile}::TestHelperMethods.test_render_guardrail_none`, () => {
      const machine = new FlatMachine({ config: makeMachineConfig() } as any);
      const fn = (machine as any)._render_guardrail;
      expect(fn).toBeTypeOf('function');
      expect(fn(null, {}, Number)).toBeNull();
    });

    test(`manifest-trace: ${pyFile}::TestHelperMethods.test_render_guardrail_jinja`, () => {
      const machine = new FlatMachine({ config: makeMachineConfig() } as any);
      const fn = (machine as any)._render_guardrail;
      expect(fn).toBeTypeOf('function');
      expect(fn('{{ context.budget }}', { context: { budget: '10' } }, Number)).toBe(10);
    });

    test(`manifest-trace: ${pyFile}::TestHelperMethods.test_build_assistant_message_no_tools`, () => {
      const machine = new FlatMachine({ config: makeMachineConfig() } as any);
      const fn = (machine as any)._build_assistant_message;
      expect(fn).toBeTypeOf('function');
      const msg = fn(makeAgentResult({ content: 'hello', tool_calls: null }));
      expect(msg.role).toBe('assistant');
      expect(msg.content).toBe('hello');
      expect(msg.tool_calls).toBeUndefined();
    });

    test(`manifest-trace: ${pyFile}::TestHelperMethods.test_build_assistant_message_with_tools`, () => {
      const machine = new FlatMachine({ config: makeMachineConfig() } as any);
      const fn = (machine as any)._build_assistant_message;
      expect(fn).toBeTypeOf('function');
      const msg = fn(
        makeAgentResult({
          content: 'let me check',
          tool_calls: [{ id: 'c1', name: 'read_file', tool: 'read_file', arguments: { path: 'x.py' } }],
        }),
      );
      expect(msg.role).toBe('assistant');
      expect(msg.tool_calls).toHaveLength(1);
      expect(msg.tool_calls[0].id).toBe('c1');
      expect(msg.tool_calls[0].type).toBe('function');
      expect(msg.tool_calls[0].function.name).toBe('read_file');
      expect(JSON.parse(msg.tool_calls[0].function.arguments)).toEqual({ path: 'x.py' });
    });

    test(`manifest-trace: ${pyFile}::TestHelperMethods.test_extract_cost_from_dict`, () => {
      const machine = new FlatMachine({ config: makeMachineConfig() } as any);
      const fn = (machine as any)._extract_cost;
      expect(fn).toBeTypeOf('function');
      expect(fn(makeAgentResult({ cost: { total: 0.42 } }))).toBeCloseTo(0.42, 6);
    });

    test(`manifest-trace: ${pyFile}::TestHelperMethods.test_extract_cost_from_float`, () => {
      const machine = new FlatMachine({ config: makeMachineConfig() } as any);
      const fn = (machine as any)._extract_cost;
      expect(fn).toBeTypeOf('function');
      expect(fn(makeAgentResult({ cost: 0.99 }))).toBeCloseTo(0.99, 6);
    });

    test(`manifest-trace: ${pyFile}::TestHelperMethods.test_extract_cost_none`, () => {
      const machine = new FlatMachine({ config: makeMachineConfig() } as any);
      const fn = (machine as any)._extract_cost;
      expect(fn).toBeTypeOf('function');
      expect(fn(makeAgentResult({ cost: null }))).toBe(0.0);
    });

    test(`manifest-trace: ${pyFile}::TestHelperMethods.test_resolve_tool_definitions_from_provider`, () => {
      const machine = new FlatMachine({ config: makeMachineConfig() } as any);
      const provider = new MockToolProvider({}, [
        { type: 'function', function: { name: 'read', parameters: {} } },
      ]);

      const fn = (machine as any)._resolve_tool_definitions;
      expect(fn).toBeTypeOf('function');
      const defs = fn('coder', provider);
      expect(defs).toHaveLength(1);
      expect(defs[0].function.name).toBe('read');
    });

    test(`manifest-trace: ${pyFile}::TestHelperMethods.test_resolve_tool_definitions_from_inline_agent`, () => {
      const agentInline = {
        spec: 'flatagent',
        spec_version: '1.1.1',
        data: {
          name: 'test',
          model: { provider: 'test', name: 'test' },
          system: 'test',
          user: '{{ input.task }}',
          tools: [{ type: 'function', function: { name: 'yaml_tool', parameters: {} } }],
        },
      };
      const machine = new FlatMachine({ config: makeMachineConfig({ agent_inline: agentInline }) } as any);

      const fn = (machine as any)._resolve_tool_definitions;
      expect(fn).toBeTypeOf('function');
      const defs = fn('coder', null);
      expect(defs).toHaveLength(1);
      expect(defs[0].function.name).toBe('yaml_tool');
    });

    test(`manifest-trace: ${pyFile}::TestHelperMethods.test_resolve_tool_definitions_merge`, () => {
      const agentInline = {
        spec: 'flatagent',
        spec_version: '1.1.1',
        data: {
          name: 'test',
          model: { provider: 'test', name: 'test' },
          system: 'test',
          user: '{{ input.task }}',
          tools: [
            { type: 'function', function: { name: 'shared', description: 'yaml version', parameters: {} } },
            { type: 'function', function: { name: 'yaml_only', parameters: {} } },
          ],
        },
      };
      const machine = new FlatMachine({ config: makeMachineConfig({ agent_inline: agentInline }) } as any);
      const provider = new MockToolProvider({}, [
        { type: 'function', function: { name: 'shared', description: 'provider version', parameters: {} } },
        { type: 'function', function: { name: 'provider_only', parameters: {} } },
      ]);

      const fn = (machine as any)._resolve_tool_definitions;
      expect(fn).toBeTypeOf('function');
      const defs = fn('coder', provider);
      const names = defs.map((d: any) => d.function.name);
      expect(names).toContain('shared');
      expect(names).toContain('yaml_only');
      expect(names).toContain('provider_only');
      expect(defs.find((d: any) => d.function.name === 'shared')?.function.description).toBe('provider version');
    });
  });

  describe('TestFlatAgentExecutorAdapter', () => {
    test(`manifest-trace: ${pyFile}::TestFlatAgentExecutorAdapter.test_agent_result_fields`, async () => {
      const agent = {
        call: vi.fn().mockResolvedValue({
          content: 'hello',
          tool_calls: [
            { id: 'c1', server: 'local', tool: 'test', arguments: { x: 1 } },
          ],
          rendered_user_prompt: 'prompt text',
        }),
      };

      const executor = new FlatAgentExecutor(agent as any);
      const result = await executor.execute_with_tools({}, []);

      expect(result.tool_calls).toEqual([{ id: 'c1', name: 'test', arguments: { x: 1 } }]);
      expect(result.rendered_user_prompt).toBe('prompt text');
    });

    test(`manifest-trace: ${pyFile}::TestFlatAgentExecutorAdapter.test_coerce_agent_result_with_tool_fields`, () => {
      const value = {
        content: 'hi',
        tool_calls: [{ id: 'x', name: 'y' }],
        rendered_user_prompt: 'prompt text',
      };

      const result = coerceAgentResult(value);
      expect(result.tool_calls).toEqual([{ id: 'x', name: 'y' }]);
      expect(result.rendered_user_prompt).toBe('prompt text');
    });
  });

  describe('TestHookSubclasses', () => {
    test(`manifest-trace: ${pyFile}::TestHookSubclasses.test_composite_hooks_chains_tool_hooks`, () => {
      const callsA: string[] = [];
      const callsB: string[] = [];

      const hooksA = {
        on_tool_calls: (_state: string, _toolCalls: any[], context: Record<string, any>) => {
          callsA.push('tool_calls');
          context.a_saw_calls = true;
          return context;
        },
        on_tool_result: () => {
          callsA.push('tool_result');
          return {};
        },
      };

      const hooksB = {
        on_tool_calls: (_state: string, _toolCalls: any[], context: Record<string, any>) => {
          callsB.push('tool_calls');
          expect(context.a_saw_calls).toBe(true);
          return context;
        },
        on_tool_result: () => {
          callsB.push('tool_result');
          return {};
        },
      };

      const composite = new CompositeHooks([hooksA as any, hooksB as any]);
      const onToolCalls = (composite as any).on_tool_calls;
      expect(onToolCalls).toBeTypeOf('function');

      const ctx = onToolCalls('work', [{ id: 'c1' }], {});
      expect(ctx.a_saw_calls).toBe(true);
      expect(callsA).toEqual(['tool_calls']);
      expect(callsB).toEqual(['tool_calls']);

      const onToolResult = (composite as any).on_tool_result;
      expect(onToolResult).toBeTypeOf('function');
      onToolResult('work', { name: 'test' }, ctx);
      expect(callsA).toEqual(['tool_calls', 'tool_result']);
      expect(callsB).toEqual(['tool_calls', 'tool_result']);
    });

    test(`manifest-trace: ${pyFile}::TestHookSubclasses.test_composite_hooks_get_tool_provider_first_wins`, () => {
      const providerB = new MockToolProvider();
      const hooksA = {};
      const hooksB = {
        get_tool_provider: (_state: string) => providerB,
      };

      const composite = new CompositeHooks([hooksA as any, hooksB as any]);
      const getToolProvider = (composite as any).get_tool_provider;
      expect(getToolProvider).toBeTypeOf('function');
      expect(getToolProvider('work')).toBe(providerB);
    });

    test(`manifest-trace: ${pyFile}::TestHookSubclasses.test_logging_hooks_tool_methods`, () => {
      const LoggingHooks = (SDK as any).LoggingHooks;
      expect(LoggingHooks).toBeTypeOf('function');

      const hooks = new LoggingHooks();
      const afterCalls = hooks.on_tool_calls('work', [{ name: 'test' }], { key: 'val' });
      expect(afterCalls).toEqual({ key: 'val' });

      const afterResult = hooks.on_tool_result('work', { name: 'test', is_error: false }, afterCalls);
      expect(afterResult).toEqual({ key: 'val' });
    });
  });
});

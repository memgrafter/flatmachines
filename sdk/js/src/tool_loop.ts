/**
 * ToolLoopAgent — standalone tool-call loop — Phase 1.2
 *
 * Ports Python SDK's tool_loop.py. Composes with FlatAgent: one FlatAgent
 * handles each LLM call, ToolLoopAgent manages the message chain, tool
 * execution, guardrails, and steering between calls.
 */

import { FinishReason, AgentResponse, AgentToolCall } from './agent_response';
import { ToolResult, ToolProvider, SimpleToolProvider, Tool } from './tools';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

export enum StopReason {
  COMPLETE = 'complete',
  MAX_TOOL_CALLS = 'max_tool_calls',
  MAX_TURNS = 'max_turns',
  TIMEOUT = 'timeout',
  COST_LIMIT = 'cost_limit',
  ABORTED = 'aborted',
  ERROR = 'error',
}

export interface Guardrails {
  max_tool_calls?: number;
  max_turns?: number;
  allowed_tools?: string[];
  denied_tools?: string[];
  tool_timeout?: number;
  total_timeout?: number;
  max_cost?: number;
}

const DEFAULT_GUARDRAILS: Required<Pick<Guardrails, 'max_tool_calls' | 'max_turns' | 'tool_timeout' | 'total_timeout'>> = {
  max_tool_calls: 50,
  max_turns: 20,
  tool_timeout: 30,
  total_timeout: 600,
};

export interface AggregateUsage {
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  total_cost: number;
  api_calls: number;
}

export interface ToolLoopResult {
  content?: string;
  messages: Array<Record<string, any>>;
  tool_calls_count: number;
  turns: number;
  stop_reason: StopReason;
  usage: AggregateUsage;
  error?: string;
}

// ─────────────────────────────────────────────────────────────────────────────
// Steering
// ─────────────────────────────────────────────────────────────────────────────

export interface SteeringProvider {
  getMessages(): Promise<Array<Record<string, any>>>;
}

export type SteeringCallback = () => Promise<Array<Record<string, any>>>;

// ─────────────────────────────────────────────────────────────────────────────
// Agent interface expected by the tool loop
// ─────────────────────────────────────────────────────────────────────────────

export interface ToolLoopAgentLLM {
  /**
   * Call the agent with optional tool definitions and message chain.
   * First call: uses inputData for template rendering.
   * Subsequent calls: uses messages chain only.
   */
  call(opts: {
    inputData?: Record<string, any>;
    tools?: Array<Record<string, any>>;
    messages?: Array<Record<string, any>>;
  }): Promise<AgentResponse>;
}

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────

function serializeArguments(args: any): string {
  if (typeof args === 'string') return args;
  return JSON.stringify(args);
}

function buildAssistantMessage(response: AgentResponse): Record<string, any> {
  const msg: Record<string, any> = { role: 'assistant', content: response.content ?? '' };
  if (response.tool_calls?.length) {
    msg.tool_calls = response.tool_calls.map(tc => ({
      id: tc.id,
      type: 'function',
      function: {
        name: tc.tool,
        arguments: serializeArguments(tc.arguments),
      },
    }));
  }
  return msg;
}

function buildToolResultMessage(toolCallId: string, content: string): Record<string, any> {
  return { role: 'tool', tool_call_id: toolCallId, content };
}

function mapFinishReason(reason?: FinishReason | null): [StopReason, string | undefined] {
  if (reason == null || reason === FinishReason.STOP) return [StopReason.COMPLETE, undefined];
  if (reason === FinishReason.ABORTED) return [StopReason.ABORTED, 'agent aborted'];
  if (reason === FinishReason.LENGTH) return [StopReason.ERROR, 'model stopped due to max token length'];
  if (reason === FinishReason.CONTENT_FILTER) return [StopReason.ERROR, 'model output blocked by content filter'];
  if (reason === FinishReason.ERROR) return [StopReason.ERROR, 'agent returned error finish reason'];
  return [StopReason.ERROR, `unexpected finish reason: ${reason}`];
}

function accumUsage(usage: AggregateUsage, response: AgentResponse): void {
  usage.api_calls += 1;
  if (response.usage) {
    usage.input_tokens += response.usage.input_tokens ?? 0;
    usage.output_tokens += response.usage.output_tokens ?? 0;
    usage.total_tokens += response.usage.total_tokens ?? 0;
    if (response.usage.cost) {
      usage.total_cost += response.usage.cost.total ?? 0;
    }
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// ToolLoopAgent
// ─────────────────────────────────────────────────────────────────────────────

export interface ToolLoopAgentOptions {
  agent: ToolLoopAgentLLM;
  tools?: Tool[];
  toolProvider?: ToolProvider;
  guardrails?: Guardrails;
  steering?: SteeringProvider | SteeringCallback;
}

export class ToolLoopAgent {
  private _agent: ToolLoopAgentLLM;
  private _provider: ToolProvider;
  private _guardrails: Required<Pick<Guardrails, 'max_tool_calls' | 'max_turns' | 'tool_timeout' | 'total_timeout'>> & Guardrails;
  private _llmTools: Array<Record<string, any>>;
  private _steering: SteeringProvider | null;

  constructor(options: ToolLoopAgentOptions) {
    if (options.toolProvider) {
      this._provider = options.toolProvider;
    } else if (options.tools) {
      this._provider = new SimpleToolProvider(options.tools);
    } else {
      throw new Error("Either 'tools' or 'toolProvider' must be provided");
    }

    this._agent = options.agent;
    this._guardrails = { ...DEFAULT_GUARDRAILS, ...options.guardrails };
    this._llmTools = this._provider.get_tool_definitions();

    if (!options.steering) {
      this._steering = null;
    } else if (typeof options.steering === 'function') {
      const cb = options.steering as SteeringCallback;
      this._steering = { getMessages: cb };
    } else {
      this._steering = options.steering as SteeringProvider;
    }
  }

  async run(inputData?: Record<string, any>): Promise<ToolLoopResult> {
    const g = this._guardrails;
    const chain: Array<Record<string, any>> = [];
    const usage: AggregateUsage = {
      input_tokens: 0, output_tokens: 0, total_tokens: 0, total_cost: 0, api_calls: 0,
    };
    let toolCallsCount = 0;
    let turns = 0;
    const startTime = Date.now();
    let lastContent: string | undefined;
    let initialUserPrompt: string | undefined;

    while (true) {
      // Timeout
      if (Date.now() - startTime >= g.total_timeout * 1000) {
        return { content: lastContent, messages: chain, tool_calls_count: toolCallsCount, turns, stop_reason: StopReason.TIMEOUT, usage };
      }

      // Max turns
      if (turns >= g.max_turns) {
        return { content: lastContent, messages: chain, tool_calls_count: toolCallsCount, turns, stop_reason: StopReason.MAX_TURNS, usage };
      }

      // Cost limit
      if (g.max_cost != null && usage.total_cost >= g.max_cost) {
        return { content: lastContent, messages: chain, tool_calls_count: toolCallsCount, turns, stop_reason: StopReason.COST_LIMIT, usage };
      }

      // Call LLM
      let response: AgentResponse;
      if (turns === 0) {
        response = await this._agent.call({ inputData: inputData ?? {}, tools: this._llmTools, messages: chain.length ? chain : undefined });
        initialUserPrompt = response.rendered_user_prompt;
      } else {
        response = await this._agent.call({ tools: this._llmTools, messages: chain });
      }

      turns += 1;
      accumUsage(usage, response);

      // Error response
      if (response.error) {
        return { content: response.content ?? undefined, messages: chain, tool_calls_count: toolCallsCount, turns, stop_reason: StopReason.ERROR, usage, error: response.error.message };
      }

      // Seed chain with initial user prompt
      if (turns === 1 && initialUserPrompt) {
        chain.push({ role: 'user', content: initialUserPrompt });
      }

      // Build assistant message
      const assistantMsg = buildAssistantMessage(response);
      chain.push(assistantMsg);
      lastContent = response.content ?? undefined;

      // Cost limit check after LLM call
      if (response.finish_reason === FinishReason.TOOL_USE && g.max_cost != null && usage.total_cost >= g.max_cost) {
        return { content: lastContent, messages: chain, tool_calls_count: toolCallsCount, turns, stop_reason: StopReason.COST_LIMIT, usage };
      }

      // No tool calls = done
      if (response.finish_reason !== FinishReason.TOOL_USE) {
        const [stopReason, finishError] = mapFinishReason(response.finish_reason);
        return { content: lastContent, messages: chain, tool_calls_count: toolCallsCount, turns, stop_reason: stopReason, usage, error: finishError };
      }

      // Tool call guardrail
      const pendingCalls = response.tool_calls ?? [];
      if (toolCallsCount + pendingCalls.length > g.max_tool_calls) {
        return { content: lastContent, messages: chain, tool_calls_count: toolCallsCount, turns, stop_reason: StopReason.MAX_TOOL_CALLS, usage };
      }

      // Execute tools sequentially
      for (const tc of pendingCalls) {
        const result = await this._executeTool(tc.id, tc.tool, tc.arguments);
        toolCallsCount += 1;
        chain.push(buildToolResultMessage(tc.id, result.content));
      }

      // Steering
      if (this._steering) {
        try {
          const steeringMessages = await this._steering.getMessages();
          for (const msg of steeringMessages) chain.push(msg);
        } catch (e: any) {
          if (e?.name === 'AbortError') {
            return { content: lastContent, messages: chain, tool_calls_count: toolCallsCount, turns, stop_reason: StopReason.ABORTED, usage, error: 'steering cancelled' };
          }
          return { content: lastContent, messages: chain, tool_calls_count: toolCallsCount, turns, stop_reason: StopReason.ERROR, usage, error: `steering provider failed: ${e}` };
        }
      }
    }
  }

  private async _executeTool(toolCallId: string, name: string, args: Record<string, any>): Promise<ToolResult> {
    const g = this._guardrails;

    // Deny/allow check
    if (g.denied_tools?.includes(name)) {
      return { content: `Tool '${name}' is not allowed`, is_error: true };
    }
    if (g.allowed_tools && !g.allowed_tools.includes(name)) {
      return { content: `Tool '${name}' is not allowed`, is_error: true };
    }

    // Execute with timeout
    try {
      const timeoutMs = g.tool_timeout * 1000;
      const result = await Promise.race([
        this._provider.execute_tool(name, toolCallId, args),
        new Promise<ToolResult>((_, reject) => setTimeout(() => reject(new Error('timeout')), timeoutMs)),
      ]);
      return result;
    } catch (e: any) {
      if (e?.message === 'timeout') {
        return { content: `Tool '${name}' timed out after ${g.tool_timeout}s`, is_error: true };
      }
      return { content: `Error executing '${name}': ${e}`, is_error: true };
    }
  }
}

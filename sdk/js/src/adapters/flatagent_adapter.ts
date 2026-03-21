/**
 * FlatAgent adapter for FlatMachines — Phase 2.2
 *
 * Ports Python SDK's adapters/flatagent.py. Wraps the existing FlatAgent
 * class to implement the AgentExecutor interface for machine-driven execution.
 */

import { FlatAgent } from '../flatagent';
import {
  AgentAdapter,
  AgentAdapterContext,
  AgentExecutor,
  AgentRef,
  AgentResult,
  AgentErrorDict,
  RateLimitState,
  buildRateLimitState,
} from '../agents';
import { AgentResponse, FinishReason } from '../agent_response';
import { resolve } from 'path';

// ─────────────────────────────────────────────────────────────────────────────
// Error code mapping
// ─────────────────────────────────────────────────────────────────────────────

function mapErrorCode(errorType: string, statusCode?: number): string {
  if (statusCode === 429) return 'rate_limit';
  if (statusCode === 401 || statusCode === 403) return 'auth_error';
  if (statusCode === 400) return 'invalid_request';
  if (statusCode != null && statusCode >= 500 && statusCode < 600) return 'server_error';
  const lower = errorType.toLowerCase();
  if (lower.includes('ratelimit') || lower.includes('rate_limit')) return 'rate_limit';
  if (lower.includes('timeout')) return 'timeout';
  if (lower.includes('content') && lower.includes('filter')) return 'content_filter';
  if (lower.includes('context') && lower.includes('length')) return 'context_length';
  return 'server_error';
}

// ─────────────────────────────────────────────────────────────────────────────
// FlatAgentExecutor
// ─────────────────────────────────────────────────────────────────────────────

export class FlatAgentExecutor implements AgentExecutor {
  private _agent: FlatAgent;

  constructor(agent: FlatAgent) {
    this._agent = agent;
  }

  get metadata(): Record<string, any> {
    return {};
  }

  private _mapResponse(response: AgentResponse): AgentResult {
    // Usage
    let usage: Record<string, any> | null = null;
    if (response.usage) {
      usage = {
        input_tokens: response.usage.input_tokens,
        output_tokens: response.usage.output_tokens,
        total_tokens: response.usage.total_tokens,
        cache_read_tokens: response.usage.cache_read_tokens,
        cache_write_tokens: response.usage.cache_write_tokens,
      };
    }

    // Cost
    let cost: Record<string, number> | null = null;
    if (response.usage?.cost) {
      cost = {
        input: response.usage.cost.input,
        output: response.usage.cost.output,
        cache_read: response.usage.cost.cache_read,
        cache_write: response.usage.cost.cache_write,
        total: response.usage.cost.total,
      };
    }

    // Error
    let error: AgentErrorDict | null = null;
    if (response.error) {
      error = {
        code: mapErrorCode(response.error.error_type, response.error.status_code),
        type: response.error.error_type,
        message: response.error.message,
        retryable: response.error.retryable,
      };
      if (response.error.status_code != null) error.status_code = response.error.status_code;
    }

    // Rate limit
    let rateLimit: RateLimitState | null = null;
    if (response.rate_limit) {
      const rawHeaders = response.rate_limit.raw_headers ?? {};
      rateLimit = buildRateLimitState(rawHeaders, response.rate_limit.retry_after);
      // Fallback from normalized fields
      if (!rateLimit.windows?.length) {
        const windows: any[] = [];
        if (response.rate_limit.remaining_requests != null) {
          windows.push({ name: 'requests', resource: 'requests', remaining: response.rate_limit.remaining_requests, limit: response.rate_limit.limit_requests });
        }
        if (response.rate_limit.remaining_tokens != null) {
          windows.push({ name: 'tokens', resource: 'tokens', remaining: response.rate_limit.remaining_tokens, limit: response.rate_limit.limit_tokens });
        }
        if (windows.length) rateLimit.windows = windows;
      }
      if (!rateLimit.limited) {
        rateLimit.limited = (response.rate_limit.remaining_requests === 0) || (response.rate_limit.remaining_tokens === 0);
      }
    }

    // Finish reason
    let finishReason: string | null = null;
    if (response.finish_reason) finishReason = response.finish_reason;
    else if (response.error) finishReason = 'error';

    // Tool calls
    let toolCalls: Array<Record<string, any>> | null = null;
    if (response.tool_calls?.length) {
      toolCalls = response.tool_calls.map(tc => ({
        id: tc.id,
        name: tc.tool,
        arguments: tc.arguments,
      }));
    }

    // Provider data
    let providerData: Record<string, any> | null = null;
    if (response.rate_limit) {
      const agentConfig = (this._agent as any).config;
      const resolvedModel = (this._agent as any).resolvedModelConfig;
      providerData = {
        provider: resolvedModel?.provider ?? agentConfig?.data?.model?.provider ?? 'cerebras',
        model: resolvedModel?.name ?? agentConfig?.data?.model?.name ?? null,
        raw_headers: response.rate_limit.raw_headers ?? {},
      };
    }

    return {
      output: response.output ?? null,
      content: response.content ?? null,
      raw: response,
      usage,
      cost,
      finish_reason: finishReason,
      error,
      rate_limit: rateLimit,
      tool_calls: toolCalls,
      rendered_user_prompt: response.rendered_user_prompt ?? null,
      provider_data: providerData,
    };
  }

  async execute(
    inputData: Record<string, any>,
    context?: Record<string, any>,
  ): Promise<AgentResult> {
    const response = await this._agent.call(inputData);
    return this._mapResponse(response);
  }

  async execute_with_tools(
    inputData: Record<string, any>,
    tools: Array<Record<string, any>>,
    messages?: Array<Record<string, any>> | null,
    context?: Record<string, any>,
  ): Promise<AgentResult> {
    const response = await this._agent.call(inputData, { tools, messages: messages ?? undefined });
    return this._mapResponse(response);
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// FlatAgentAdapter
// ─────────────────────────────────────────────────────────────────────────────

export class FlatAgentAdapter implements AgentAdapter {
  readonly type_name = 'flatagent';

  create_executor(opts: {
    agent_name: string;
    agent_ref: AgentRef;
    context: AgentAdapterContext;
  }): AgentExecutor {
    const { agent_ref, context } = opts;

    if (agent_ref.ref) {
      const refPath = resolve(context.config_dir, agent_ref.ref);
      return new FlatAgentExecutor(
        new FlatAgent({ config: refPath, profilesFile: context.profiles_file }),
      );
    }
    if (agent_ref.config) {
      return new FlatAgentExecutor(
        new FlatAgent({ config: agent_ref.config as any, profilesFile: context.profiles_file }),
      );
    }
    throw new Error(`FlatAgent reference missing ref/config for agent '${opts.agent_name}'`);
  }
}

// Auto-register as built-in adapter
import { AgentAdapterRegistry } from '../agents';
AgentAdapterRegistry.registerBuiltinFactory(() => new FlatAgentAdapter());

/**
 * CodexLLMBackend — LLM backend using the Codex SSE client.
 */

import { CodexClient } from '../providers/codex_client';
import type { LLMBackend, LLMOptions, Message } from './types';

function safeJsonParse(value: string): Record<string, any> {
  try {
    const parsed = JSON.parse(value);
    return typeof parsed === 'object' && parsed ? parsed : {};
  } catch {
    return {};
  }
}

export class CodexLLMBackend implements LLMBackend {
  totalCost = 0;
  totalApiCalls = 0;

  private client: CodexClient;
  private modelConfig: Record<string, any>;

  constructor(modelConfig: Record<string, any>, opts?: { configDir?: string }) {
    this.modelConfig = modelConfig;
    this.client = new CodexClient(modelConfig, { configDir: opts?.configDir });
  }

  async call(messages: Message[], options?: LLMOptions): Promise<string> {
    const raw = await this.callRaw(messages, options);
    return String(raw?.text ?? '');
  }

  async callRaw(messages: Message[], options?: LLMOptions): Promise<any> {
    this.totalApiCalls += 1;

    const result = await this.client.call({
      model: this.modelConfig.name,
      base_url: this.modelConfig.base_url,
      messages,
      temperature: options?.temperature,
      tools: options?.tools,
      headers: this.modelConfig.headers,
      reasoning_effort: this.modelConfig.reasoning_effort ?? this.modelConfig.codex_reasoning_effort,
      reasoning_summary: this.modelConfig.reasoning_summary ?? this.modelConfig.codex_reasoning_summary,
      verbosity: this.modelConfig.verbosity ?? this.modelConfig.codex_text_verbosity,
      service_tier: this.modelConfig.service_tier,
    });

    const toolCalls = (result.tool_calls ?? []).map(tc => {
      const args = safeJsonParse(tc.arguments_json || '{}');
      return {
        id: tc.id,
        name: tc.name,
        args,
        function: {
          name: tc.name,
          arguments: JSON.stringify(args),
        },
      };
    });

    const usage = {
      prompt_tokens: result.usage?.input_tokens ?? 0,
      completion_tokens: result.usage?.output_tokens ?? 0,
      total_tokens: result.usage?.total_tokens ?? 0,
      prompt_tokens_details: {
        cached_tokens: result.usage?.cached_tokens ?? 0,
      },
    };

    return {
      text: result.content ?? '',
      tool_calls: toolCalls,
      finish_reason: result.finish_reason ?? (toolCalls.length ? 'tool_calls' : 'stop'),
      usage,
      _response_headers: result.response_headers ?? {},
      _response_status_code: result.response_status_code,
      _request_meta: result.request_meta ?? {},
    };
  }
}

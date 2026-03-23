import {
  CodexClient,
  FlatAgent,
  FlatAgentExecutor,
  type AgentAdapter,
  type AgentAdapterContext,
  type AgentExecutor,
  type AgentRef,
  type LLMBackend,
  type LLMOptions,
  type Message,
} from '@memgrafter/flatmachines';
import { dirname, resolve } from 'path';

function safeJsonParse(value: string): Record<string, any> {
  try {
    const parsed = JSON.parse(value);
    return typeof parsed === 'object' && parsed ? parsed : {};
  } catch {
    return {};
  }
}

class CodexLLMBackend implements LLMBackend {
  totalCost = 0;
  totalApiCalls = 0;

  private readonly client: CodexClient;
  private readonly modelConfig: Record<string, any>;

  constructor(modelConfig: Record<string, any>, configDir?: string) {
    this.modelConfig = modelConfig;
    this.client = new CodexClient(modelConfig, { configDir });
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

    const toolCalls = (result.tool_calls ?? []).map(tc => ({
      id: tc.id,
      name: tc.name,
      args: safeJsonParse(tc.arguments_json || '{}'),
    }));

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

export class CodexAwareFlatAgentAdapter implements AgentAdapter {
  readonly type_name = 'flatagent';

  private withCodexBackend(agent: FlatAgent, configDir?: string): FlatAgent {
    const resolvedModelConfig = ((agent as any).resolvedModelConfig ?? {}) as Record<string, any>;
    const backend = String(resolvedModelConfig.backend ?? '').toLowerCase();
    if (backend === 'codex') {
      (agent as any).llmBackend = new CodexLLMBackend(resolvedModelConfig, configDir);
    }
    return agent;
  }

  create_executor(opts: {
    agent_name: string;
    agent_ref: AgentRef;
    context: AgentAdapterContext;
  }): AgentExecutor {
    const { agent_ref, context } = opts;

    if (agent_ref.ref) {
      const refPath = resolve(context.config_dir, agent_ref.ref);
      const agent = new FlatAgent({
        config: refPath,
        profilesFile: context.profiles_file,
      });
      return new FlatAgentExecutor(this.withCodexBackend(agent, dirname(refPath)));
    }

    if (agent_ref.config) {
      const agent = new FlatAgent({
        config: agent_ref.config as any,
        configDir: context.config_dir,
        profilesFile: context.profiles_file,
      });
      return new FlatAgentExecutor(this.withCodexBackend(agent, context.config_dir));
    }

    throw new Error(`FlatAgent reference missing ref/config for agent '${opts.agent_name}'`);
  }
}

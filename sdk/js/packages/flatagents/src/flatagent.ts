import * as yaml from 'yaml';
import { readFileSync, existsSync } from 'fs';
import { dirname, resolve } from 'path';
import { AgentConfig, ModelConfig } from './types';
import { MCPToolProvider } from './mcp';
import { LLMBackend, Message, VercelAIBackend, CodexLLMBackend } from './llm';
import { resolveModelConfig } from './profiles';
import { renderTemplate } from './templating';
import {
  AgentResponse,
  AgentToolCall,
  FinishReason,
  UsageInfo,
  CostInfo,
  RateLimitInfo,
  ErrorInfo,
  extractRateLimitInfo,
  normalizeHeaders,
  extractStatusCode,
  isRetryableError,
} from './agent_response';

/**
 * Options for constructing a FlatAgent with custom backends.
 */
export interface AgentOptions {
  /** Path to YAML config file or inline AgentConfig */
  config: string | AgentConfig;

  /** Custom LLM backend (if not provided, uses VercelAIBackend based on config) */
  llmBackend?: LLMBackend;

  /** Base directory for resolving relative paths */
  configDir?: string;

  /** Path to profiles.yml for model profile resolution */
  profilesFile?: string;
}

export class FlatAgent {
  public config: AgentConfig;
  private mcpProvider?: MCPToolProvider;
  private llmBackend?: LLMBackend;
  private configDir: string;
  private profilesFile?: string;
  private resolvedModelConfig: ModelConfig;

  /**
   * Create a FlatAgent.
   *
   * @param configOrOptions - Config path, config object, or AgentOptions
   */
  constructor(configOrOptions: AgentConfig | string | AgentOptions) {
    let configPath: string | undefined;

    if (configOrOptions && typeof configOrOptions === 'object' && 'config' in configOrOptions && !('spec' in configOrOptions)) {
      // AgentOptions provided
      const options = configOrOptions as AgentOptions;
      if (typeof options.config === 'string') {
        configPath = options.config;
        this.config = yaml.parse(readFileSync(options.config, 'utf-8')) as AgentConfig;
      } else {
        this.config = options.config;
      }
      this.llmBackend = options.llmBackend;
      this.configDir = options.configDir ?? (configPath ? dirname(configPath) : process.cwd());
      this.profilesFile = options.profilesFile;
    } else if (typeof configOrOptions === 'string') {
      // Path provided
      configPath = configOrOptions;
      this.config = yaml.parse(readFileSync(configOrOptions, 'utf-8')) as AgentConfig;
      this.configDir = dirname(configOrOptions);
    } else {
      // AgentConfig provided directly
      this.config = configOrOptions as AgentConfig;
      this.configDir = process.cwd();
    }

    // Auto-discover profiles.yml if not explicitly set
    if (!this.profilesFile) {
      const discovered = resolve(this.configDir, 'profiles.yml');
      if (existsSync(discovered)) {
        this.profilesFile = discovered;
      }
    }

    const configData = this.config?.data;
    // CEL expression engine is now supported via cel-js (optional dependency)

    // Resolve model config through profiles (only if we have valid config data)
    if (configData?.model) {
      this.resolvedModelConfig = resolveModelConfig(
        configData.model,
        this.configDir,
        this.profilesFile
      );
    } else {
      // Fallback for malformed/incomplete configs
      this.resolvedModelConfig = { name: '' };
    }
  }

  /**
   * Get or create the LLM backend.
   */
  private getBackend(): LLMBackend {
    if (!this.llmBackend) {
      const model = this.resolvedModelConfig as Record<string, any>;
      const backend = String(model.backend ?? '').toLowerCase();
      const provider = String(model.provider ?? '').toLowerCase();

      if (backend === 'codex' || provider === 'openai-codex') {
        this.llmBackend = new CodexLLMBackend(model, { configDir: this.configDir });
      } else {
        this.llmBackend = new VercelAIBackend({
          provider: this.resolvedModelConfig.provider ?? 'openai',
          name: this.resolvedModelConfig.name,
          baseURL: this.resolvedModelConfig.base_url,
        });
      }
    }
    return this.llmBackend;
  }

  /**
   * Call the agent and return a structured AgentResponse.
   *
   * @param input - Template input variables
   * @param opts - Optional: tools for tool calling, messages for continuation chain
   */
  async call(
    input: Record<string, any>,
    opts?: { tools?: Array<Record<string, any>>; messages?: Array<Record<string, any>> },
  ): Promise<AgentResponse> {
    try {
      // Connect MCP if configured
      if (this.config.data.mcp && !this.mcpProvider) {
        this.mcpProvider = new MCPToolProvider();
        await this.mcpProvider.connect(this.config.data.mcp.servers);
      }

      // Render prompts
      const mcpTools = this.mcpProvider ? await this.mcpProvider.listTools(this.config.data.mcp?.tool_filter) : [];
      const toolsPrompt = this.config.data.mcp?.tool_prompt
        ? renderTemplate(this.config.data.mcp.tool_prompt, { tools: mcpTools }, "flatagent.tool_prompt")
        : "";
      const templateVars = { input, tools: mcpTools, tools_prompt: toolsPrompt, model: this.resolvedModelConfig };
      const system = renderTemplate(this.config.data.system, templateVars, "flatagent.system");
      let user = renderTemplate(this.config.data.user, templateVars, "flatagent.user");
      if (this.config.data.instruction_suffix) {
        user = `${user}\n\n${this.config.data.instruction_suffix}`;
      }

      // Build messages for LLM backend
      let messages: Message[];
      if (opts?.messages?.length) {
        // Continuation call — use provided chain (system + chain)
        messages = [
          { role: 'system' as const, content: system },
          ...(opts.messages as Message[]),
        ];
      } else {
        messages = [
          { role: 'system' as const, content: system },
          { role: 'user' as const, content: user },
        ];
      }

      // Call LLM via backend with resolved model config
      const backend = this.getBackend();
      const llmOptions: any = {
        temperature: this.resolvedModelConfig.temperature,
        max_tokens: this.resolvedModelConfig.max_tokens,
        top_p: this.resolvedModelConfig.top_p,
        top_k: this.resolvedModelConfig.top_k,
        frequency_penalty: this.resolvedModelConfig.frequency_penalty,
        presence_penalty: this.resolvedModelConfig.presence_penalty,
        seed: this.resolvedModelConfig.seed,
      };

      // Add tools if provided
      if (opts?.tools?.length) {
        llmOptions.tools = opts.tools;
      }

      const rawResponse = await backend.callRaw(messages, llmOptions);
      const text: string = rawResponse?.text ?? rawResponse?.choices?.[0]?.message?.content ?? '';

      // Extract usage info from raw response
      const usage = this._extractUsage(rawResponse);

      // Extract rate limit info
      const headers = normalizeHeaders(rawResponse?._response_headers ?? rawResponse?.headers);
      const rateLimit = Object.keys(headers).length > 0 ? extractRateLimitInfo(headers) : undefined;

      // Extract tool calls
      const toolCalls = this._extractToolCalls(rawResponse);
      const finishReason = this._extractFinishReasonInternal(rawResponse, toolCalls);

      // Extract structured output
      const output = finishReason === FinishReason.TOOL_USE ? undefined : this.extractOutput(text);

      return new AgentResponse({
        content: text,
        output: output ?? null,
        tool_calls: toolCalls?.length ? toolCalls : null,
        raw_response: rawResponse,
        usage: usage ?? null,
        rate_limit: rateLimit ?? null,
        finish_reason: finishReason,
        rendered_user_prompt: opts?.messages?.length ? undefined : user,
      });
    } catch (err: any) {
      const statusCode = extractStatusCode(err);
      return new AgentResponse({
        content: null,
        output: null,
        error: new ErrorInfo({
          error_type: err?.name ?? err?.constructor?.name ?? 'Error',
          message: err?.message ?? String(err),
          status_code: statusCode ?? null,
          retryable: isRetryableError(err, statusCode),
        }),
        finish_reason: FinishReason.ERROR,
      });
    }
  }

  private _extractUsage(rawResponse: any): UsageInfo | undefined {
    const usage = rawResponse?.usage;
    if (!usage) return undefined;

    const inputTokens = Number(usage.promptTokens ?? usage.prompt_tokens ?? 0);
    const outputTokens = Number(usage.completionTokens ?? usage.completion_tokens ?? 0);
    const totalTokens = Number(usage.totalTokens ?? usage.total_tokens ?? (inputTokens + outputTokens));

    const [fallbackCacheRead, fallbackCacheWrite] = this._extract_cache_tokens(usage);
    const cacheReadTokens = Number(usage.cacheReadTokens ?? usage.cache_read_tokens ?? fallbackCacheRead ?? 0);
    const cacheWriteTokens = Number(usage.cacheWriteTokens ?? usage.cache_write_tokens ?? fallbackCacheWrite ?? 0);

    const usageInfo = new UsageInfo({
      input_tokens: inputTokens,
      output_tokens: outputTokens,
      total_tokens: totalTokens,
      cache_read_tokens: cacheReadTokens,
      cache_write_tokens: cacheWriteTokens,
    });

    usageInfo.cost = this._calculate_cost({
      response: rawResponse,
      input_tokens: inputTokens,
      output_tokens: outputTokens,
      cache_read_tokens: cacheReadTokens,
      cache_write_tokens: cacheWriteTokens,
    });

    return usageInfo;
  }

  private _extractToolCalls(rawResponse: any): AgentToolCall[] | undefined {
    // Vercel AI SDK format
    const toolCalls = rawResponse?.toolCalls ?? rawResponse?.tool_calls;
    if (!toolCalls?.length) return undefined;

    return toolCalls.map((tc: any) => new AgentToolCall({
      id: tc.toolCallId ?? tc.id ?? '',
      server: '',
      tool: tc.toolName ?? tc.function?.name ?? tc.name ?? '',
      arguments: tc.args ?? (typeof tc.function?.arguments === 'string' ? JSON.parse(tc.function.arguments) : tc.function?.arguments) ?? {},
    }));
  }

  /**
   * Extract finish reason from response. Supports choices-style (litellm/OpenAI)
   * and Vercel AI style responses.
   */
  _extract_finish_reason(rawResponse: any): FinishReason | null {
    if (!rawResponse) return null;
    
    // Vercel AI style
    let reason = rawResponse?.finishReason ?? rawResponse?.finish_reason;
    
    // OpenAI/litellm choices-style
    if (!reason && rawResponse?.choices?.length) {
      reason = rawResponse.choices[0]?.finish_reason;
    }
    
    if (!reason) return null;
    
    const lower = String(reason).toLowerCase();
    if (lower === 'stop' || lower === 'end_turn') return FinishReason.STOP;
    if (lower === 'length' || lower === 'max_tokens') return FinishReason.LENGTH;
    if (lower === 'tool_calls' || lower === 'tool_use' || lower === 'function_call') return FinishReason.TOOL_USE;
    if (lower === 'content_filter') return FinishReason.CONTENT_FILTER;
    return FinishReason.STOP; // unknown defaults to stop
  }

  private _extractFinishReasonInternal(rawResponse: any, toolCalls?: AgentToolCall[]): FinishReason {
    if (toolCalls?.length) return FinishReason.TOOL_USE;
    return this._extract_finish_reason(rawResponse) ?? FinishReason.STOP;
  }

  /**
   * Extract cache token counts from raw usage dict.
   */
  _extract_cache_tokens(usage: any): [number, number] {
    if (!usage) return [0, 0];
    
    // Anthropic-style: cache_read_input_tokens, cache_creation_input_tokens
    const anthropicRead = usage.cache_read_input_tokens;
    const anthropicWrite = usage.cache_creation_input_tokens;
    
    if (anthropicRead != null && anthropicRead !== 0) {
      return [anthropicRead, anthropicWrite ?? 0];
    }
    if (anthropicWrite != null && anthropicWrite !== 0) {
      return [anthropicRead ?? 0, anthropicWrite];
    }
    
    // OpenAI-style: prompt_tokens_details.cached_tokens
    const cached = usage.prompt_tokens_details?.cached_tokens;
    if (cached != null && cached !== 0) {
      return [cached, 0];
    }
    
    // Check zero values
    if (anthropicRead === 0 && anthropicWrite === 0) {
      return [0, 0];
    }
    
    return [0, 0];
  }

  /**
   * Calculate cost breakdown from token counts.
   */
  _calculate_cost(args: {
    response?: any;
    input_tokens: number;
    output_tokens: number;
    cache_read_tokens: number;
    cache_write_tokens: number;
  }): CostInfo {
    const { input_tokens, output_tokens, cache_read_tokens, cache_write_tokens } = args;
    
    // Fallback estimation using rough per-token costs.
    // These are approximate and will drift from actual provider pricing.
    // For accurate cost tracking, use provider-specific pricing APIs.
    const INPUT_COST_PER_TOKEN = 0.000001;
    const OUTPUT_COST_PER_TOKEN = 0.000003;
    const CACHE_READ_COST_PER_TOKEN = 0.0000001;
    const CACHE_WRITE_COST_PER_TOKEN = 0.0000015;

    const inputCost = input_tokens * INPUT_COST_PER_TOKEN;
    const outputCost = output_tokens * OUTPUT_COST_PER_TOKEN;
    const cacheReadCost = cache_read_tokens * CACHE_READ_COST_PER_TOKEN;
    const cacheWriteCost = cache_write_tokens * CACHE_WRITE_COST_PER_TOKEN;

    return new CostInfo({
      input: inputCost,
      output: outputCost,
      cache_read: cacheReadCost,
      cache_write: cacheWriteCost,
      total: inputCost + outputCost + cacheReadCost + cacheWriteCost,
    });
  }

  /**
   * Record rate limit metrics to a monitor.
   */
  _record_rate_limit_metrics(monitor: any, rateLimitInfo: any): void {
    if (!monitor?.metrics || !rateLimitInfo) return;
    
    const fieldMappings: Array<[string, string]> = [
      ['remaining_requests', 'ratelimit_remaining_requests'],
      ['remaining_tokens', 'ratelimit_remaining_tokens'],
      ['limit_requests', 'ratelimit_limit_requests'],
      ['limit_tokens', 'ratelimit_limit_tokens'],
      ['reset_at', 'ratelimit_reset_at'],
      ['retry_after', 'ratelimit_retry_after'],
    ];
    
    for (const [sourceKey, targetKey] of fieldMappings) {
      const value = rateLimitInfo[sourceKey];
      if (value != null) {
        monitor.metrics[targetKey] = value;
      }
    }
  }

  private extractOutput(text: string): any {
    // Strip markdown fences and parse JSON
    const match = text.match(/```(?:json)?\s*([\s\S]*?)```/);
    const json = match ? match[1]!.trim() : text.trim();

    try {
      const parsed = JSON.parse(json);

      // If we got a primitive but have a schema expecting an object,
      // map it to the first field
      if (this.config.data.output && parsed !== null && typeof parsed !== 'object') {
        const fields = Object.keys(this.config.data.output);
        if (fields.length === 1) {
          return { [fields[0]!]: parsed };
        }
      }

      return parsed;
    } catch {
      // If JSON parsing fails, check if we have a single field schema
      // and the response looks like a quoted value
      if (this.config.data.output) {
        const fields = Object.keys(this.config.data.output);
        if (fields.length === 1) {
          // Try strict match first - entire response is quoted
          const strictMatch = json.trim().match(/^"([^"]*)"$/);
          if (strictMatch) {
            return { [fields[0]!]: strictMatch[1] };
          }
          // Fall back to finding any quoted string in response
          const lenientMatch = json.match(/"([^"]+)"/);
          if (lenientMatch) {
            return { [fields[0]!]: lenientMatch[1] };
          }
          // If not quoted, use the raw text as the value
          if (json.trim()) {
            return { [fields[0]!]: json.trim() };
          }
        }
      }
      return { content: text };
    }
  }
}
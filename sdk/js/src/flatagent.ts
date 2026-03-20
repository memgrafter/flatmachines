import * as yaml from "yaml";
import { readFileSync } from 'fs';
import { dirname } from 'path';
import { AgentConfig, ModelConfig } from './types';
import { MCPToolProvider } from './mcp';
import { LLMBackend, Message, VercelAIBackend } from './llm';
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

    const configData = this.config && typeof this.config === "object"
      ? (this.config as any).data
      : undefined;
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
      this.llmBackend = new VercelAIBackend({
        provider: this.resolvedModelConfig.provider ?? 'openai',
        name: this.resolvedModelConfig.name,
        baseURL: this.resolvedModelConfig.base_url,
      });
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
      const finishReason = this._extractFinishReason(rawResponse, toolCalls);

      // Extract structured output
      const output = finishReason === FinishReason.TOOL_USE ? undefined : this.extractOutput(text);

      return {
        content: text,
        output,
        tool_calls: toolCalls?.length ? toolCalls : undefined,
        raw_response: rawResponse,
        usage,
        rate_limit: rateLimit,
        finish_reason: finishReason,
        rendered_user_prompt: opts?.messages?.length ? undefined : user,
      };
    } catch (err: any) {
      const statusCode = extractStatusCode(err);
      return {
        content: undefined,
        output: undefined,
        error: {
          error_type: err?.name ?? err?.constructor?.name ?? 'Error',
          message: err?.message ?? String(err),
          status_code: statusCode,
          retryable: isRetryableError(err, statusCode),
        },
        finish_reason: FinishReason.ERROR,
      };
    }
  }

  private _extractUsage(rawResponse: any): UsageInfo | undefined {
    const usage = rawResponse?.usage;
    if (!usage) return undefined;
    return {
      input_tokens: usage.promptTokens ?? usage.prompt_tokens ?? 0,
      output_tokens: usage.completionTokens ?? usage.completion_tokens ?? 0,
      total_tokens: usage.totalTokens ?? usage.total_tokens ?? 0,
      cache_read_tokens: usage.cacheReadTokens ?? usage.cache_read_tokens ?? 0,
      cache_write_tokens: usage.cacheWriteTokens ?? usage.cache_write_tokens ?? 0,
    };
  }

  private _extractToolCalls(rawResponse: any): AgentToolCall[] | undefined {
    // Vercel AI SDK format
    const toolCalls = rawResponse?.toolCalls ?? rawResponse?.tool_calls;
    if (!toolCalls?.length) return undefined;

    return toolCalls.map((tc: any) => ({
      id: tc.toolCallId ?? tc.id ?? '',
      server: '',
      tool: tc.toolName ?? tc.function?.name ?? tc.name ?? '',
      arguments: tc.args ?? (typeof tc.function?.arguments === 'string' ? JSON.parse(tc.function.arguments) : tc.function?.arguments) ?? {},
    }));
  }

  private _extractFinishReason(rawResponse: any, toolCalls?: AgentToolCall[]): FinishReason {
    if (toolCalls?.length) return FinishReason.TOOL_USE;

    const reason = rawResponse?.finishReason ?? rawResponse?.finish_reason;
    if (reason === 'stop' || reason === 'end_turn') return FinishReason.STOP;
    if (reason === 'length' || reason === 'max_tokens') return FinishReason.LENGTH;
    if (reason === 'tool_calls' || reason === 'tool_use') return FinishReason.TOOL_USE;
    if (reason === 'content_filter') return FinishReason.CONTENT_FILTER;
    return FinishReason.STOP;
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

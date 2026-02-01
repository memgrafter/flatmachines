import * as yaml from "yaml";
import { readFileSync } from 'fs';
import { dirname } from 'path';
import { AgentConfig, ModelConfig } from './types';
import { MCPToolProvider } from './mcp';
import { LLMBackend, Message, VercelAIBackend } from './llm';
import { resolveModelConfig } from './profiles';
import { renderTemplate } from './templating';

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
    if (configData?.expression_engine === "cel") {
      throw new Error("expression_engine 'cel' is not supported in the JS SDK yet");
    }

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

  async call(input: Record<string, any>): Promise<{ content: string; output: any }> {
    // Connect MCP if configured
    if (this.config.data.mcp && !this.mcpProvider) {
      this.mcpProvider = new MCPToolProvider();
      await this.mcpProvider.connect(this.config.data.mcp.servers);
    }

    // Render prompts
    const tools = this.mcpProvider ? await this.mcpProvider.listTools(this.config.data.mcp?.tool_filter) : [];
    const toolsPrompt = this.config.data.mcp?.tool_prompt
      ? renderTemplate(this.config.data.mcp.tool_prompt, { tools }, "flatagent.tool_prompt")
      : "";
    const templateVars = { input, tools, tools_prompt: toolsPrompt, model: this.resolvedModelConfig };
    const system = renderTemplate(this.config.data.system, templateVars, "flatagent.system");
    let user = renderTemplate(this.config.data.user, templateVars, "flatagent.user");
    if (this.config.data.instruction_suffix) {
      user = `${user}\n\n${this.config.data.instruction_suffix}`;
    }

    // Build messages for LLM backend
    const messages: Message[] = [
      { role: 'system', content: system },
      { role: 'user', content: user },
    ];

    // Call LLM via backend with resolved model config
    const backend = this.getBackend();
    const text = await backend.call(messages, {
      temperature: this.resolvedModelConfig.temperature,
      max_tokens: this.resolvedModelConfig.max_tokens,
      top_p: this.resolvedModelConfig.top_p,
      top_k: this.resolvedModelConfig.top_k,
      frequency_penalty: this.resolvedModelConfig.frequency_penalty,
      presence_penalty: this.resolvedModelConfig.presence_penalty,
      repetition_penalty: this.resolvedModelConfig.repetition_penalty,
      seed: this.resolvedModelConfig.seed,
      stop: this.resolvedModelConfig.stop,
      logit_bias: this.resolvedModelConfig.logit_bias,
      tools: this.resolvedModelConfig.tools,
      tool_choice: this.resolvedModelConfig.tool_choice,
      parallel_tool_calls: this.resolvedModelConfig.parallel_tool_calls,
      response_format: this.resolvedModelConfig.response_format,
    });

    // Extract structured output
    const output = this.extractOutput(text);
    return { content: text, output };
  }

  private extractOutput(text: string): any {
    // Strip markdown fences and parse JSON
    const match = text.match(/```(?:json)?\s*([\s\S]*?)```/);
    const json = match ? match[1].trim() : text.trim();

    try {
      const parsed = JSON.parse(json);

      // If we got a primitive but have a schema expecting an object,
      // map it to the first field
      if (this.config.data.output && parsed !== null && typeof parsed !== 'object') {
        const fields = Object.keys(this.config.data.output);
        if (fields.length === 1) {
          return { [fields[0]]: parsed };
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
            return { [fields[0]]: strictMatch[1] };
          }
          // Fall back to finding any quoted string in response
          const lenientMatch = json.match(/"([^"]+)"/);
          if (lenientMatch) {
            return { [fields[0]]: lenientMatch[1] };
          }
          // If not quoted, use the raw text as the value
          if (json.trim()) {
            return { [fields[0]]: json.trim() };
          }
        }
      }
      return { content: text };
    }
  }
}

import { generateText, LanguageModel } from "ai";
import { createOpenAI } from "@ai-sdk/openai";
import { createAnthropic } from "@ai-sdk/anthropic";
import { createCerebras } from "@ai-sdk/cerebras";
import { createOpenAICompatible } from "@ai-sdk/openai-compatible";
import * as nunjucks from "nunjucks";
import * as yaml from "yaml";
import { readFileSync } from 'fs';
import { AgentConfig } from './types';
import { MCPToolProvider } from './mcp';

// Known provider base URLs for OpenAI-compatible providers
const PROVIDER_BASE_URLS: Record<string, string> = {
  cerebras: "https://api.cerebras.ai/v1",
  groq: "https://api.groq.com/openai/v1",
  together: "https://api.together.xyz/v1",
  fireworks: "https://api.fireworks.ai/inference/v1",
  deepseek: "https://api.deepseek.com/v1",
  mistral: "https://api.mistral.ai/v1",
  perplexity: "https://api.perplexity.ai",
};

export class FlatAgent {
  public config: AgentConfig;
  private mcpProvider?: MCPToolProvider;
  private model?: LanguageModel;

  constructor(configOrPath: AgentConfig | string) {
    this.config = typeof configOrPath === "string"
      ? yaml.parse(readFileSync(configOrPath, "utf-8")) as AgentConfig
      : configOrPath;
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
      ? nunjucks.renderString(this.config.data.mcp.tool_prompt, { tools })
      : "";
    const templateVars = { input, tools, tools_prompt: toolsPrompt, model: this.config.data.model };
    const system = nunjucks.renderString(this.config.data.system, templateVars);
    let user = nunjucks.renderString(this.config.data.user, templateVars);
    if (this.config.data.instruction_suffix) {
      user = `${user}\n\n${this.config.data.instruction_suffix}`;
    }

    // Get model
    const model = this.getModel();
    const modelConfig = this.config.data.model;

    // Call LLM via Vercel AI SDK
    const generateParams: any = {
      model,
      system,
      prompt: user,
    };
    if (modelConfig.temperature !== undefined) generateParams.temperature = modelConfig.temperature;
    if (modelConfig.max_tokens !== undefined) generateParams.maxTokens = modelConfig.max_tokens;
    if (modelConfig.top_p !== undefined) generateParams.topP = modelConfig.top_p;
    if (modelConfig.frequency_penalty !== undefined) generateParams.frequencyPenalty = modelConfig.frequency_penalty;
    if (modelConfig.presence_penalty !== undefined) generateParams.presencePenalty = modelConfig.presence_penalty;

    const response = await generateText(generateParams);

    const text = response.text;

    // Extract structured output
    const output = this.extractOutput(text);
    return { content: text, output };
  }

  private getModel(): LanguageModel {
    if (this.model) return this.model;

    const { provider = "openai", name: modelName } = this.config.data.model;
    const providerLower = provider.toLowerCase();
    const providerUpper = provider.toUpperCase();
    const apiKey = process.env[`${providerUpper}_API_KEY`];
    const baseURL = process.env[`${providerUpper}_BASE_URL`] || PROVIDER_BASE_URLS[providerLower];

    if (providerLower === "openai") {
      const openai = createOpenAI({ apiKey });
      this.model = openai.chat(modelName);
    } else if (providerLower === "anthropic") {
      const anthropic = createAnthropic({ apiKey });
      this.model = anthropic(modelName);
    } else if (providerLower === "cerebras") {
      const cerebras = createCerebras({ apiKey });
      this.model = cerebras(modelName);
    } else {
      // Use createOpenAICompatible for any other OpenAI-compatible provider
      if (!baseURL) {
        throw new Error(`Unknown provider "${provider}". Set ${providerUpper}_BASE_URL environment variable.`);
      }
      const compatible = createOpenAICompatible({
        name: providerLower,
        baseURL,
        headers: {
          Authorization: `Bearer ${apiKey}`,
        },
      });
      this.model = compatible(modelName);
    }

    return this.model!;
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

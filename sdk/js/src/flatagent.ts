import { generateText } from "ai";
import { createOpenAI } from "@ai-sdk/openai";
import { createAnthropic } from "@ai-sdk/anthropic";
import * as nunjucks from "nunjucks";
import * as yaml from "yaml";
import { readFileSync } from 'fs';
import { AgentConfig } from './types';
import { MCPToolProvider } from './mcp';

export class FlatAgent {
  public config: AgentConfig;
  private mcpProvider?: MCPToolProvider;

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
    const system = nunjucks.renderString(this.config.data.system, { input, tools });
    const user = nunjucks.renderString(this.config.data.user, { input, tools });

    // Call LLM
    const { text } = await generateText({
      model: this.getModel(),
      system,
      prompt: user,
    });

    // Extract structured output
    const output = this.extractOutput(text);
    return { content: text, output };
  }

  private getModel() {
    const { provider = "openai", name } = this.config.data.model;
    if (provider === "anthropic") return createAnthropic()(`anthropic/${name}`);
    return createOpenAI()(`openai/${name}`);
  }

  private extractOutput(text: string): any {
    // Strip markdown fences and parse JSON
    const match = text.match(/```(?:json)?\s*([\s\S]*?)```/);
    const json = match ? match[1].trim() : text.trim();
    try { return JSON.parse(json); } catch { return { content: text }; }
  }
}
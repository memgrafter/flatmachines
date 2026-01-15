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
    let user = nunjucks.renderString(this.config.data.user, { input, tools });

    // Add output instruction if we have a schema and no tools
    if (this.config.data.output && !tools) {
      const outputInstruction = this.buildOutputInstruction();
      if (outputInstruction) {
        user = `${user}\n\n${outputInstruction}`;
      }
    }

    // Call LLM
    const params: any = {
      model: this.getModel(),
      system,
      prompt: user,
    };

    // Use JSON mode if we have an output schema and no tools
    if (this.config.data.output && !tools) {
      // Note: @ai-sdk/openai doesn't directly support response_format, 
      // but we can achieve similar behavior through prompting
    }

    const { text } = await generateText(params);

    // Extract structured output
    const output = this.extractOutput(text);
    return { content: text, output };
  }

  private getModel() {
    const { provider = "openai", name } = this.config.data.model;
    if (provider === "anthropic") return createAnthropic()(`anthropic/${name}`);
    if (provider === "cerebras") return createOpenAI({ 
      baseURL: 'https://api.cerebras.ai/v1',
      apiKey: process.env.CEREBRAS_API_KEY || process.env.OPENAI_API_KEY 
    })(name);
    return createOpenAI()(`openai/${name}`);
  }

  private buildOutputInstruction(): string {
    if (!this.config.data.output) return "";

    const fields = [];
    for (const [name, fieldDef] of Object.entries(this.config.data.output)) {
      const def = fieldDef as any;
      const desc = def.description || '';
      const parts = [`"${name}"`];
      if (desc) parts.push(`(${desc})`);
      fields.push(parts.join(" "));
    }

    return `Respond with JSON containing: ${fields.join(", ")}`;
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
          // Try to extract a quoted value from the text
          const quotedMatch = json.trim().match(/^"([^"]*)"$/);
          if (quotedMatch) {
            return { [fields[0]]: quotedMatch[1] };
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
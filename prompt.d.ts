/**
 * Prompt Configuration Schema
 * ===========================
 *
 * Prompt is the pure prompt/output contract used by FlatMachine.
 *
 * A Prompt defines:
 * - authored prompt text (`system`, `user`, `instruction_suffix`)
 * - expected structured output (`output`)
 * - optional model-facing tool context (`tools`, `mcp`)
 *
 * A Prompt does NOT define runtime, model, profile, or adapter selection.
 * Those belong to `profiles.d.ts` and `flatmachine.d.ts`.
 *
 * This file is the source of truth for prompt config shapes.
 * Generated schema assets may be derived from this file.
 */

export const SPEC_VERSION = "4.0.0";

export interface PromptWrapper {
  spec: "prompt";
  spec_version: string;
  data: PromptData;
  metadata?: Record<string, any>;
}

/**
 * Pure prompt contract.
 *
 * `tools` and `mcp` are prompt-local declarations. They are only meaningful
 * when the selected execution profile/agent supports model-facing tool use.
 */
export interface PromptData {
  name?: string;
  system?: string;
  user: string;
  instruction_suffix?: string;
  output?: OutputSchema;
  mcp?: MCPConfig;
  tools?: ToolDefinition[];
}

/**
 * Model-facing function tool definition.
 */
export interface ToolDefinition {
  type: "function";
  function: {
    name: string;
    description?: string;
    parameters?: Record<string, any>;
  };
}

/**
 * MCP configuration for prompt-local tool discovery/injection.
 */
export interface MCPConfig {
  servers: Record<string, MCPServerDef>;
  tool_filter?: ToolFilter;
  tool_prompt: string;
}

export interface MCPServerDef {
  command?: string;
  args?: string[];
  env?: Record<string, string>;
  server_url?: string;
  headers?: Record<string, string>;
  timeout?: number;
}

export interface ToolFilter {
  allow?: string[];
  deny?: string[];
}

export type OutputSchema = Record<string, OutputFieldDef>;

export interface OutputFieldDef {
  type: "str" | "int" | "float" | "bool" | "json" | "list" | "object";
  description?: string;
  enum?: string[];
  required?: boolean;
  items?: OutputFieldDef;
  properties?: OutputSchema;
}

export type FlatpromptConfig = PromptWrapper;

/**
 * Prompt Configuration Schema
 * ===========================
 *
 * Prompt is the pure prompt/output contract.
 *
 * It defines:
 * - authored prompt text (`system`, `user`, `instruction_suffix`, `post_history_instructions`)
 * - expected structured output (`output`)
 * - optional model-facing tool declarations (`tools`, `mcp`)
 *
 * It does not define runtime, model, profile, or adapter selection.
 */

export const SPEC_VERSION = "4.2.1";

export interface PromptWrapper {
  spec: "prompt";
  spec_version: string;
  data: PromptData;
  metadata?: Record<string, any>;
}

export interface PromptData {
  name?: string;
  system?: string;
  user: string;
  instruction_suffix?: string;
  post_history_instructions?: string;
  output?: OutputSchema;
  mcp?: MCPConfig;
  tools?: ToolDefinition[];
}

/**
 * Prompt inline-or-ref value.
 * - string: path/ref to a prompt file
 * - object: inline prompt config
 */
export type PromptRef = string | PromptData | PromptWrapper;

export interface ToolDefinition {
  type: "function";
  function: {
    name: string;
    description?: string;
    parameters?: Record<string, any>;
  };
}

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

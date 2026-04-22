/**
 * FlatAgent Configuration Schema
 * =============================
 *
 * FlatAgent is the prompt-first wrapper for agent execution.
 *
 * FlatAgent should stay focused on:
 * - prompting (`system`, `user`, `instruction_suffix`)
 * - structured output (`output`)
 * - model-facing tool use (`tools`, `mcp`) when the selected profile uses the built-in `llm` runtime
 * - selecting a reusable execution profile (`profile`)
 *
 * Runtime identity and operational configuration belong in `profiles.d.ts`.
 * That keeps FlatAgent authoring centered on prompts instead of runtime knobs.
 *
 * This file is the source of truth for FlatAgent config shapes.
 * Generated schema assets are derived from this file.
 */

export const SPEC_VERSION = "4.0.0";

export interface AgentWrapper {
  spec: "flatagent";
  spec_version: string;
  data: AgentData;
  metadata?: Record<string, any>;
}

/**
 * FlatAgent remains prompt-shaped.
 *
 * `profile` selects a named execution profile from `profiles.d.ts`.
 * If omitted, the runtime may use `profiles.d.ts` default/override resolution.
 *
 * `tools` and `mcp` are prompt-local and are only meaningful when the resolved
 * profile uses the built-in `llm` runtime.
 */
export interface AgentData {
  name?: string;
  profile?: string;
  system?: string;
  user: string;
  instruction_suffix?: string;
  output?: OutputSchema;
  mcp?: MCPConfig;
  tools?: ToolDefinition[];
}

/**
 * FlatAgent function tool definitions.
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
 * MCP configuration.
 * Used only when the resolved profile executes with the built-in `llm` runtime.
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

/**
 * Shared model/OAuth vocabulary used by `profiles.d.ts`.
 *
 * These types are retained here as the canonical FlatAgent-side type surface
 * for model configuration, even though agents now typically reference only a
 * named `profile` instead of embedding model config inline.
 */
export interface OAuthConfig {
  provider?: "openai-codex" | string;
  auth_file?: string;
  refresh?: boolean;
  originator?: string;
  timeout_seconds?: number;
  max_retries?: number;
  token_url?: string;
  client_id?: string;
}

export interface ModelConfig {
  name: string;
  provider?: string;
  temperature?: number;
  max_tokens?: number;
  top_p?: number;
  top_k?: number;
  frequency_penalty?: number;
  presence_penalty?: number;
  seed?: number;
  base_url?: string;
  backend?: "litellm" | "aisuite" | "codex" | "copilot";
  api?: string;
  oauth?: OAuthConfig;
}

export interface ProfiledModelConfig extends Partial<ModelConfig> {
  profile: string;
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

export type FlatagentsConfig = AgentWrapper;

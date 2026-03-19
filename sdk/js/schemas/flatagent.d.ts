/**
 * FlatAgents Configuration Schema
 * ===============================
 *
 * An agent is a single LLM call: model + prompts + output schema.
 * Workflows handle composition, branching, and loops.
 *
 * STRUCTURE:
 * ----------
 * spec           - Fixed string "flatagents"
 * spec_version   - Semver string
 * data           - The agent configuration
 * metadata       - Extensibility layer (runners ignore unrecognized keys)
 *
 * DERIVED SCHEMAS:
 * ----------------
 * This file (/flatagent.d.ts) is the SOURCE OF TRUTH for all FlatAgent schemas.
 * Other schemas (JSON Schema, etc.) are DERIVED from this file using scripts.
 * See: /scripts/generate-spec-assets.ts
 *
 * DATA FIELDS:
 * ------------
 * name               - Agent identifier (inferred from filename if omitted)
 * model              - LLM configuration
 * system             - System prompt (Jinja2 template)
 * user               - User prompt template (Jinja2)
 * instruction_suffix - Optional instruction appended after user prompt
 * output             - Output schema (what fields we want)
 * mcp                - Optional MCP (Model Context Protocol) configuration
 *
 * MCP FIELDS:
 * -----------
 * servers            - Map of server name to MCPServerDef
 * tool_filter        - Optional allow/deny lists using "server:tool" format
 * tool_prompt        - Jinja2 template for tool prompt (uses {{ tools }} variable)
 *
 * MODEL FIELDS:
 * -------------
 * name              - Model name (e.g., "gpt-4", "zai-glm-4.6")
 * provider          - Provider name (e.g., "openai", "anthropic", "cerebras")
 * temperature       - Sampling temperature (0.0 to 2.0)
 * max_tokens        - Maximum tokens to generate
 * top_p             - Nucleus sampling parameter
 * top_k             - Top-k sampling parameter
 * frequency_penalty - Frequency penalty (-2.0 to 2.0)
 * presence_penalty  - Presence penalty (-2.0 to 2.0)
 * seed              - Random seed for reproducibility
 * base_url          - Custom API base URL (for local models/proxies)
 * backend           - Runtime backend override (litellm, aisuite, codex)
 * oauth             - OAuth settings (used by codex backend)
 *
 * MODEL PROFILES:
 * ---------------
 * Agents can reference model profiles from profiles.yml:
 *   model: "fast-cheap"                    # String = profile lookup
 *   model: { profile: "fast-cheap" }       # Profile with optional overrides
 *   model: { provider: x, name: y, ... }   # Inline config (no profile)
 *
 * OUTPUT FIELD DEFINITION:
 * ------------------------
 * type        - Field type: str, int, float, bool, json, list, object
 * description - Description (used for structured output / tool calls)
 * enum        - Allowed values (for enum-like fields)
 * required    - Whether the field is required (default: true)
 * items       - For list type: the type of items
 * properties  - For object type: nested properties
 *
 * TEMPLATE SYNTAX:
 * ----------------
 * Prompts use Jinja2 templating. Available variables:
 *   - input.*  - Values passed to the agent at runtime
 *
 * Example: "Question: {{ input.question }}"
 *
 * EXAMPLE CONFIGURATION:
 * ----------------------
 *
 *   spec: flatagents
 *   spec_version: "0.7.0"
 *
 *   data:
 *     name: critic
 *
 *     model:
 *       provider: cerebras
 *       name: zai-glm-4.6
 *       temperature: 0.5
 *
 *     system: |
 *       Act as a ruthless critic. Analyze drafts for errors.
 *       Rate severity as: High, Medium, or Low.
 *
 *     user: |
 *       Question: {{ input.question }}
 *       Draft: {{ input.draft }}
 *
 *     output:
 *       critique:
 *         type: str
 *         description: "Specific errors found in the draft"
 *       severity:
 *         type: str
 *         description: "Error severity"
 *         enum: ["High", "Medium", "Low"]
 *
 *   metadata:
 *     description: "Critiques draft answers"
 *     tags: ["reflection", "qa"]
 *
 * MCPCONFIG:
 * ----------
 * MCP (Model Context Protocol) configuration.
 * Defines MCP servers and tool filtering rules.
 *   servers     - MCP server definitions, keyed by server name
 *   tool_filter - Optional tool filtering rules
 *   tool_prompt - Jinja2 template for tool prompt injection.
 *                 Available variables: tools (list of discovered tools)
 *                 Example: "{% for tool in tools %}{{ tool.name }}: {{ tool.description }}{% endfor %}"
 *
 * MCPSERVERDEF:
 * -------------
 * MCP server definition.
 * Supports stdio transport (command) or HTTP transport (server_url).
 * Stdio transport:
 *   command - Command to start the MCP server (e.g., "npx", "python")
 *   args    - Arguments for the command
 *   env     - Environment variables for the server process
 * HTTP transport:
 *   server_url - Base URL of the MCP server (e.g., "http://localhost:8000")
 *   headers    - HTTP headers (e.g., for authentication)
 *   timeout    - Request timeout in seconds
 *
 * TOOLFILTER:
 * -----------
 * Tool filtering rules using "server:tool" format.
 * Supports wildcards: "server:*" matches all tools from a server.
 *   allow - Tools to allow (if specified, only these are included)
 *   deny  - Tools to deny (takes precedence over allow)
 *
 * AGENTDATA MODEL FIELD:
 * ----------------------
 * Model configuration accepts three forms:
 *   - String: Profile name lookup (e.g., "fast-cheap")
 *   - ModelConfig: Inline config with name, provider, etc.
 *   - ProfiledModelConfig: Profile reference with optional overrides
 *
 * PROFILEDMODELCONFIG:
 * --------------------
 * Model config that references a profile with optional overrides.
 * Example: { profile: "fast-cheap", temperature: 0.8 }
 * The profile field specifies which profile name to use as base.
 */

export const SPEC_VERSION = "2.4.0";

export interface AgentWrapper {
  spec: "flatagent";
  spec_version: string;
  data: AgentData;
  metadata?: Record<string, any>;
}

export interface AgentData {
  name?: string;
  model: string | ModelConfig | ProfiledModelConfig;
  system: string;
  user: string;
  instruction_suffix?: string;
  output?: OutputSchema;
  mcp?: MCPConfig;
  tools?: ToolDefinition[];
}

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
  backend?: "litellm" | "aisuite" | "codex";
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

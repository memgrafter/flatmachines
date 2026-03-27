/**
 * FlatAgents types — agent-level configuration and model types.
 */

/**
 * Model configuration for an agent.
 * Can be inline config, profile reference, or profile with overrides.
 */
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
}

/**
 * Model config that references a profile with optional overrides.
 */
export interface ProfiledModelConfig extends Partial<ModelConfig> {
  profile: string;
}

/**
 * Model profile configuration (used in profiles.yml).
 */
export interface ModelProfileConfig {
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
}

/**
 * Profiles configuration (profiles.yml structure).
 */
export interface ProfilesConfig {
  spec: "flatprofiles";
  spec_version: string;
  data: {
    model_profiles: Record<string, ModelProfileConfig>;
    default?: string;
    override?: string;
  };
  metadata?: Record<string, any>;
}

export interface AgentConfig {
  spec: "flatagent";
  spec_version: string;
  data: {
    name?: string;
    /**
     * Model configuration.
     * - String: Profile name lookup (e.g., "fast-cheap")
     * - ModelConfig: Inline config with name, provider, etc.
     * - ProfiledModelConfig: Profile reference with optional overrides
     */
    model: string | ModelConfig | ProfiledModelConfig;
    system: string;
    user: string;
    instruction_suffix?: string;
    output?: Record<string, { type: string; description?: string; enum?: string[]; required?: boolean; items?: any; properties?: any }>;
    mcp?: { servers: Record<string, MCPServer>; tool_filter?: ToolFilter; tool_prompt?: string };
  };
}

// Matches flatagent.d.ts:154-161
export interface MCPServer {
  command?: string;
  args?: string[];
  env?: Record<string, string>;
  serverUrl?: string;
  headers?: Record<string, string>;
  timeout?: number;
}

export interface ToolFilter {
  allow?: string[];
  deny?: string[];
}

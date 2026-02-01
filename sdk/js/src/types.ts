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
  repetition_penalty?: number;
  seed?: number;
  base_url?: string;
  stop?: string | string[];
  logit_bias?: Record<string, number>;
  tools?: ToolDefinition[];
  tool_choice?: ToolChoice;
  parallel_tool_calls?: boolean;
  response_format?: ResponseFormat;
}

export type ToolChoice =
  | "none"
  | "auto"
  | "required"
  | { type: "function"; function: { name: string } };

export type ResponseFormat =
  | { type: "text" }
  | { type: "json_object" }
  | { type: "json_schema"; json_schema: JsonSchemaResponseFormat };

export interface JsonSchemaResponseFormat {
  name: string;
  description?: string;
  schema: Record<string, any>;
  strict?: boolean;
}

export interface ToolDefinition {
  type: "function";
  function: ToolFunction;
}

export interface ToolFunction {
  name: string;
  description?: string;
  parameters?: Record<string, any>;
  strict?: boolean;
}

/**
 * Configuration for multi-round tool calling loops.
 */
export interface ToolLoopConfig {
  /** Maximum number of tool call rounds (default: 10) */
  max_rounds?: number;
  /** Tool definitions (OpenAI function calling format) */
  tools?: ToolDefinition[];
  /** Control tool usage */
  tool_choice?: ToolChoice;
  /** Allow parallel tool calls in single response (default: true) */
  parallel_tool_calls?: boolean;
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
  repetition_penalty?: number;
  seed?: number;
  base_url?: string;
  stop?: string | string[];
  logit_bias?: Record<string, number>;
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

export interface MachineConfig {
  spec: "flatmachine";
  spec_version: string;
  data: {
    name?: string;
    expression_engine?: "simple" | "cel";
    context?: Record<string, any>;
    agents?: Record<string, string>;
    machines?: Record<string, string | MachineConfig | MachineWrapper | MachineReference>;
    states: Record<string, State>;
    settings?: { max_steps?: number; backends?: BackendConfig; [key: string]: any };
    persistence?: { enabled: boolean; backend: "local" | "memory" | "redis" | string; checkpoint_on?: string[];[key: string]: any };
  };
}

export interface State {
  type?: "initial" | "final";
  agent?: string;
  machine?: string | string[] | MachineInput[];
  action?: string;
  execution?: { type: "default" | "retry" | "parallel" | "mdap_voting"; backoffs?: number[]; jitter?: number; n_samples?: number; k_margin?: number; max_candidates?: number };
  input?: Record<string, any>;
  output_to_context?: Record<string, any>;
  output?: Record<string, any>;
  transitions?: { condition?: string; to: string }[];
  tool_loop?: boolean | ToolLoopConfig;
  tools?: ToolDefinition[];
  on_error?: string | Record<string, string>;
  foreach?: string;
  as?: string;
  key?: string;
  mode?: "settled" | "any";
  timeout?: number;
  launch?: string | string[];
  launch_input?: Record<string, any>;
  sampling?: "single" | "multi";
}

// Matches flatmachine.d.ts:333-351 exactly
export interface MachineSnapshot {
  execution_id: string;
  machine_name: string;
  spec_version: string;
  current_state: string;
  context: Record<string, any>;
  step: number;
  created_at: string;
  event?: string;
  output?: Record<string, any>;
  total_api_calls?: number;
  total_cost?: number;
  parent_execution_id?: string;
  pending_launches?: LaunchIntent[];
}

// Matches flatmachine.d.ts:326-331
export interface LaunchIntent {
  execution_id: string;
  machine: string;
  input: Record<string, any>;
  launched: boolean;
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

export interface ExecutionConfig {
  type: "default" | "retry" | "parallel" | "mdap_voting";
  backoffs?: number[];
  jitter?: number;
  n_samples?: number;
  k_margin?: number;
  max_candidates?: number;
}

export interface ExecutionType {
  execute<T>(fn: () => Promise<T>): Promise<T>;
}

export interface MachineHooks {
  onMachineStart?(context: Record<string, any>): Record<string, any> | Promise<Record<string, any>>;
  onMachineEnd?(context: Record<string, any>, output: any): any | Promise<any>;
  onStateEnter?(state: string, context: Record<string, any>): Record<string, any> | Promise<Record<string, any>>;
  onStateExit?(state: string, context: Record<string, any>, output: any): any | Promise<any>;
  onTransition?(from: string, to: string, context: Record<string, any>): string | Promise<string>;
  onError?(state: string, error: Error, context: Record<string, any>): string | null | Promise<string | null>;
  onAction?(action: string, context: Record<string, any>): Record<string, any> | Promise<Record<string, any>>;
}

export interface PersistenceBackend {
  save(key: string, snapshot: MachineSnapshot): Promise<void>;
  load(key: string): Promise<MachineSnapshot | null>;
  delete(key: string): Promise<void>;
  list(prefix: string): Promise<string[]>;
}

export interface ResultBackend {
  write(uri: string, data: any): Promise<void>;
  read(uri: string, options?: { block?: boolean; timeout?: number }): Promise<any>;
  exists(uri: string): Promise<boolean>;
  delete(uri: string): Promise<void>;
}

export interface MachineOptions {
  config: MachineConfig | string;
  hooks?: MachineHooks;
  persistence?: PersistenceBackend;
  resultBackend?: ResultBackend;
  executionLock?: ExecutionLock;
  configDir?: string;
  executionId?: string;
  parentExecutionId?: string;
  /** Path to profiles.yml for model profile resolution */
  profilesFile?: string;
}

export interface MachineInput {
  name: string;
  input?: Record<string, any>;
}

export interface MachineReference {
  path?: string;
  inline?: MachineConfig;
}

export interface MachineWrapper {
  spec: "flatmachine";
  spec_version: string;
  data: MachineConfig["data"];
}

// Matches flatagents-runtime.d.ts BackendConfig
export interface BackendConfig {
  persistence?: "memory" | "local" | "redis" | "postgres" | "s3";
  locking?: "none" | "local" | "redis" | "consul";
  results?: "memory" | "redis";
}

// =============================================================================
// Runtime Interfaces (see flatagents-runtime.d.ts for canonical definitions)
// =============================================================================

/**
 * Prevents concurrent execution of the same machine instance.
 * See flatagents-runtime.d.ts for spec.
 */
export interface ExecutionLock {
  acquire(key: string): Promise<boolean>;
  release(key: string): Promise<void>;
}

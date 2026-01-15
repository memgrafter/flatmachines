export interface AgentConfig {
  spec: "flatagent";
  spec_version: string;
  data: {
    name?: string;
    model: {
      name: string;
      provider?: string;
      temperature?: number;
      max_tokens?: number;
      top_p?: number;
      frequency_penalty?: number;
      presence_penalty?: number;
    };
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
    settings?: { max_steps?: number; [key: string]: any };
    persistence?: { enabled: boolean; backend: "local" | "memory" | "redis" | string; checkpoint_on?: string[]; [key: string]: any };
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
  on_error?: string | Record<string, string>;
  foreach?: string;
  as?: string;
  key?: string;
  mode?: "settled" | "any";
  timeout?: number;
  launch?: string | string[];
  launch_input?: Record<string, any>;
  tool_loop?: boolean;
  sampling?: "single" | "multi";
}

export interface MachineSnapshot {
  executionId: string;
  machineName: string;
  currentState: string;
  context: Record<string, any>;
  step: number;
  createdAt: string;
  parentExecutionId?: string;
  event?: string;
  output?: Record<string, any>;
}

export interface MCPServer {
  command?: string;
  args?: string[];
  serverUrl?: string;
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
  configDir?: string;
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

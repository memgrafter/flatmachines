export interface AgentConfig {
  spec: "flatagent";
  spec_version: string;
  data: {
    name?: string;
    model: { name: string; provider?: string; temperature?: number; max_tokens?: number };
    system: string;
    user: string;
    output?: Record<string, { type: string; description?: string }>;
    mcp?: { servers: Record<string, MCPServer>; tool_filter?: ToolFilter; tool_prompt?: string };
  };
}

export interface MachineConfig {
  spec: "flatmachine";
  spec_version: string;
  data: {
    name?: string;
    context?: Record<string, any>;
    agents?: Record<string, string>;
    states: Record<string, State>;
    persistence?: { enabled: boolean; backend: "local" | "memory" };
  };
}

export interface State {
  type?: "initial" | "final";
  agent?: string;
  machine?: string | string[];
  execution?: { type: "default" | "retry"; backoffs?: number[]; jitter?: number };
  input?: Record<string, any>;
  output_to_context?: Record<string, any>;
  output?: Record<string, any>;
  transitions?: { condition?: string; to: string }[];
  on_error?: string;
  foreach?: string;
  as?: string;
  launch?: string | string[];
  launch_input?: Record<string, any>;
}

export interface MachineSnapshot {
  executionId: string;
  machineName: string;
  currentState: string;
  context: Record<string, any>;
  step: number;
  createdAt: string;
  parentExecutionId?: string;
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
  type: "default" | "retry";
  backoffs?: number[];
  jitter?: number;
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
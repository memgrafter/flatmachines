export const SPEC_VERSION = "2.0.0";
export interface MachineWrapper {
    spec: "flatmachine";
    spec_version: string;
    data: MachineData;
    metadata?: Record<string, any>;
}
export interface MachineData {
    name?: string;
    expression_engine?: "simple" | "cel";
    context?: Record<string, any>;
    agents?: Record<string, AgentRef>;
    machines?: Record<string, string | MachineWrapper>;
    states: Record<string, StateDefinition>;
    settings?: MachineSettings;
    persistence?: PersistenceConfig;
    hooks?: HooksRef;
}
export interface AgentRefConfig {
    type: string;
    ref?: string;
    config?: Record<string, any>;
}
export type AgentRef = string | AgentWrapper | AgentRefConfig;
export type HooksRef = string | HooksRefConfig | Array<string | HooksRefConfig>;
export interface HooksRefConfig {
    name: string;
    args?: Record<string, any>;
}
export interface MachineSettings {
    max_steps?: number;
    parallel_fallback?: "sequential" | "error";
    [key: string]: any;
}
export interface StateDefinition {
    type?: "initial" | "final";
    agent?: string;
    machine?: string | string[] | MachineInput[];
    action?: string;
    execution?: ExecutionConfig;
    on_error?: string | Record<string, string>;
    wait_for?: string;
    input?: Record<string, any>;
    output_to_context?: Record<string, any>;
    output?: Record<string, any>;
    transitions?: Transition[];
    tool_loop?: boolean | ToolLoopStateConfig;
    sampling?: "single" | "multi";
    foreach?: string;
    as?: string;
    key?: string;
    mode?: "settled" | "any";
    timeout?: number;
    launch?: string | string[];
    launch_input?: Record<string, any>;
}
export interface ToolLoopStateConfig {
    max_tool_calls?: number;
    max_turns?: number;
    allowed_tools?: string[];
    denied_tools?: string[];
    tool_timeout?: number;
    total_timeout?: number;
    max_cost?: number;
}
export interface MachineInput {
    name: string;
    input?: Record<string, any>;
}
export interface ExecutionConfig {
    type: "default" | "retry" | "parallel" | "mdap_voting";
    backoffs?: number[];
    jitter?: number;
    n_samples?: number;
    k_margin?: number;
    max_candidates?: number;
}
export interface Transition {
    condition?: string;
    to: string;
}
import { AgentWrapper, OutputSchema, ModelConfig } from "./flatagent";
export { AgentWrapper, OutputSchema };
export type FlatmachineConfig = MachineWrapper;
export interface LaunchIntent {
    execution_id: string;
    machine: string;
    input: Record<string, any>;
    launched: boolean;
}
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
    waiting_channel?: string;
    tool_loop_state?: {
        chain: Array<Record<string, any>>;
        turns: number;
        tool_calls_count: number;
        loop_cost: number;
    };
}
export interface PersistenceConfig {
    enabled: boolean;
    backend: "local" | "redis" | "memory" | string;
    checkpoint_on?: string[];
    [key: string]: any;
}
export interface MachineReference {
    path?: string;
    inline?: MachineWrapper;
}

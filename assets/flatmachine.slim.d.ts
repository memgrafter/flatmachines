export const SPEC_VERSION = "0.3.0";
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
    agents?: Record<string, string | AgentWrapper>;
    machines?: Record<string, string | MachineWrapper>;
    states: Record<string, StateDefinition>;
    settings?: MachineSettings;
    persistence?: PersistenceConfig;
}
export interface MachineSettings {
    hooks?: string;
    max_steps?: number;
    [key: string]: any;
}
export interface StateDefinition {
    type?: "initial" | "final";
    agent?: string;
    machine?: string;
    action?: string;
    execution?: ExecutionConfig;
    on_error?: string | Record<string, string>;
    input?: Record<string, any>;
    output_to_context?: Record<string, any>;
    output?: Record<string, any>;
    transitions?: Transition[];
    tool_loop?: boolean;
    sampling?: "single" | "multi";
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

export interface ExecutionLock {
    acquire(key: string): Promise<boolean>;
    release(key: string): Promise<void>;
}
export interface PersistenceBackend {
    save(key: string, snapshot: MachineSnapshot): Promise<void>;
    load(key: string): Promise<MachineSnapshot | null>;
    delete(key: string): Promise<void>;
    list(prefix: string): Promise<string[]>;
    listExecutionIds?(options?: {
        event?: string;
        waiting_channel?: string;
    }): Promise<string[]>;
    deleteExecution?(execution_id: string): Promise<void>;
}
export interface ResultBackend {
    write(uri: string, data: any): Promise<void>;
    read(uri: string, options?: {
        block?: boolean;
        timeout?: number;
    }): Promise<any>;
    exists(uri: string): Promise<boolean>;
    delete(uri: string): Promise<void>;
}
export interface AgentResult {
    output?: Record<string, any> | null;
    content?: string | null;
    raw?: any;
    usage?: UsageInfo | null;
    cost?: CostInfo | number | null;
    metadata?: Record<string, any> | null;
    finish_reason?: string | null;
    error?: AgentError | null;
    rate_limit?: RateLimitState | null;
    provider_data?: ProviderData | null;
}
export interface UsageInfo {
    input_tokens?: number;
    output_tokens?: number;
    total_tokens?: number;
    cache_read_tokens?: number;
    cache_write_tokens?: number;
}
export interface CostInfo {
    input?: number;
    output?: number;
    cache_read?: number;
    cache_write?: number;
    total?: number;
}
export interface AgentError {
    code?: string;
    type?: string;
    message: string;
    status_code?: number;
    retryable?: boolean;
}
export interface RateLimitState {
    limited: boolean;
    retry_after?: number;
    windows?: RateLimitWindow[];
}
export interface RateLimitWindow {
    name: string;
    resource: string;
    remaining?: number;
    limit?: number;
    resets_in?: number;
    reset_at?: number;
}
export interface ProviderData {
    provider?: string;
    model?: string;
    request_id?: string;
    raw_headers?: Record<string, string>;
    [key: string]: any;
}
export interface AgentExecutor {
    execute(input: Record<string, any>, context?: Record<string, any>): Promise<AgentResult>;
    metadata?: Record<string, any>;
}
export interface ExecutionType {
    execute(executor: AgentExecutor, input: Record<string, any>, context?: Record<string, any>): Promise<AgentResult>;
}
export interface ExecutionConfig {
    type: "default" | "retry" | "parallel" | "mdap_voting";
    backoffs?: number[];
    jitter?: number;
    n_samples?: number;
    k_margin?: number;
    max_candidates?: number;
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
export interface HooksRegistry {
    register(name: string, factory: HooksFactory): void;
    resolve(ref: HooksRef): MachineHooks;
    has(name: string): boolean;
}
export type HooksFactory = {
    new (args?: Record<string, any>): MachineHooks;
} | ((args?: Record<string, any>) => MachineHooks);
import { HooksRef, HooksRefConfig } from "./flatmachine";
export interface LLMBackend {
    totalCost: number;
    totalApiCalls: number;
    call(messages: Message[], options?: LLMOptions): Promise<string>;
    callRaw(messages: Message[], options?: LLMOptions): Promise<any>;
}
export interface Message {
    role: "system" | "user" | "assistant" | "tool";
    content: string;
    tool_call_id?: string;
    tool_calls?: ToolCall[];
}
export interface ToolCall {
    id: string;
    type: "function";
    function: {
        name: string;
        arguments: string;
    };
}
export interface LLMOptions {
    temperature?: number;
    max_tokens?: number;
    tools?: ToolDefinition[];
    response_format?: {
        type: "json_object";
    } | {
        type: "text";
    };
}
export interface ToolDefinition {
    type: "function";
    function: {
        name: string;
        description?: string;
        parameters?: Record<string, any>;
    };
}
export interface MachineInvoker {
    invoke(machineName: string, input: Record<string, any>, options?: {
        timeout?: number;
    }): Promise<Record<string, any>>;
    launch(machineName: string, input: Record<string, any>): Promise<string>;
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
}
export interface SnapshotRuntime {
    clone_snapshot(snapshot: MachineSnapshot, new_execution_id: string, persistence: PersistenceBackend): Promise<MachineSnapshot>;
}
export interface LaunchIntent {
    execution_id: string;
    machine: string;
    input: Record<string, any>;
    launched: boolean;
}
export interface RegistrationBackend {
    register(worker: WorkerRegistration): Promise<WorkerRecord>;
    heartbeat(worker_id: string, metadata?: Record<string, any>): Promise<void>;
    updateStatus(worker_id: string, status: string): Promise<void>;
    get(worker_id: string): Promise<WorkerRecord | null>;
    list(filter?: WorkerFilter): Promise<WorkerRecord[]>;
}
export interface WorkerRegistration {
    worker_id: string;
    host?: string;
    pid?: number;
    capabilities?: string[];
    pool_id?: string;
    started_at: string;
}
export interface WorkerRecord extends WorkerRegistration {
    status: string;
    last_heartbeat: string;
    current_task_id?: string;
}
export interface WorkerFilter {
    status?: string | string[];
    capability?: string;
    pool_id?: string;
    stale_threshold_seconds?: number;
}
export interface WorkBackend {
    pool(name: string): WorkPool;
}
export interface WorkPool {
    push(item: any, options?: {
        max_retries?: number;
    }): Promise<string>;
    claim(worker_id: string): Promise<WorkItem | null>;
    complete(item_id: string, result?: any): Promise<void>;
    fail(item_id: string, error?: string): Promise<void>;
    size(): Promise<number>;
    releaseByWorker(worker_id: string): Promise<number>;
}
export interface WorkItem {
    id: string;
    data: any;
    claimed_by?: string;
    claimed_at?: string;
    attempts: number;
    max_retries: number;
}
export interface SignalBackend {
    send(channel: string, data: any): Promise<string>;
    consume(channel: string): Promise<Signal | null>;
    peek(channel: string): Promise<Signal[]>;
    channels(): Promise<string[]>;
}
export interface Signal {
    id: string;
    channel: string;
    data: any;
    created_at: string;
}
export interface TriggerBackend {
    notify(channel: string): Promise<void>;
}
export interface BackendConfig {
    persistence?: "memory" | "local" | "sqlite" | "redis" | "postgres" | "s3" | "dynamodb";
    locking?: "none" | "local" | "sqlite" | "redis" | "consul" | "dynamodb";
    results?: "memory" | "redis" | "dynamodb";
    registration?: "memory" | "sqlite" | "redis" | "dynamodb";
    work?: "memory" | "sqlite" | "redis" | "dynamodb";
    signal?: "memory" | "sqlite" | "redis" | "dynamodb";
    trigger?: "none" | "file" | "socket";
    sqlite_path?: string;
    trigger_path?: string;
    dynamodb_table?: string;
    aws_region?: string;
}
export const SPEC_VERSION = "2.4.1";
export interface SDKRuntimeWrapper {
    spec: "flatagents-runtime";
    spec_version: typeof SPEC_VERSION;
    execution_lock?: ExecutionLock;
    persistence_backend?: PersistenceBackend;
    result_backend?: ResultBackend;
    execution_config?: ExecutionConfig;
    machine_hooks?: MachineHooks;
    hooks_registry?: HooksRegistry;
    llm_backend?: LLMBackend;
    machine_invoker?: MachineInvoker;
    backend_config?: BackendConfig;
    machine_snapshot?: MachineSnapshot;
    snapshot_runtime?: SnapshotRuntime;
    registration_backend?: RegistrationBackend;
    work_backend?: WorkBackend;
    signal_backend?: SignalBackend;
    trigger_backend?: TriggerBackend;
}

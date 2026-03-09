/**
 * FlatAgents Runtime Interface Spec
 * ==================================
 *
 * This file defines the runtime interfaces that SDKs MUST implement
 * to be considered compliant. These are NOT configuration schemas
 * (see flatagent.d.ts and flatmachine.d.ts for those).
 *
 * REQUIRED IMPLEMENTATIONS:
 * -------------------------
 *   - ExecutionLock: NoOpLock (MUST), LocalFileLock (SHOULD)
 *   - PersistenceBackend: MemoryBackend (MUST), LocalFileBackend (SHOULD)
 *   - ResultBackend: InMemoryResultBackend (MUST)
 *   - ExecutionType: Default, Retry, Parallel, MDAPVoting (MUST)
 *   - MachineHooks: Base interface (MUST)
 *   - RegistrationBackend: SQLiteRegistrationBackend (MUST), MemoryRegistrationBackend (SHOULD)
 *   - WorkBackend: SQLiteWorkBackend (MUST), MemoryWorkBackend (SHOULD)
 *   - SignalBackend: MemorySignalBackend (MUST), SQLiteSignalBackend (SHOULD)
 *   - TriggerBackend: NoOpTrigger (MUST), FileTrigger (SHOULD)
 *
 * OPTIONAL IMPLEMENTATIONS:
 * -------------------------
 *   - Distributed backends (Redis, Postgres, DynamoDB, etc.)
 *   - LLMBackend (SDK may use native provider SDKs)
 *
 * EXECUTION LOCKING:
 * ------------------
 * Prevents concurrent execution of the same machine instance.
 *
 * SDKs MUST provide:
 *   - NoOpLock: For when locking is handled externally or disabled
 *
 * SDKs SHOULD provide:
 *   - LocalFileLock: For single-node deployments using fcntl/flock
 *
 * Distributed deployments should implement Redis/Consul/etcd locks.
 *
 * PERSISTENCE BACKEND:
 * --------------------
 * Storage backend for machine checkpoints.
 *
 * SDKs MUST provide:
 *   - MemoryBackend: For testing and ephemeral runs
 *
 * SDKs SHOULD provide:
 *   - LocalFileBackend: For durable local storage with atomic writes
 *
 * RESULT BACKEND:
 * ---------------
 * Inter-machine communication via URI-addressed results.
 *
 * URI format: flatagents://{execution_id}/{path}
 *   - path is typically "result" or "checkpoint"
 *
 * SDKs MUST provide:
 *   - InMemoryResultBackend: For single-process execution
 *
 * EXECUTION TYPES:
 * ----------------
 * Execution strategy for agent calls.
 *
 * SDKs MUST implement all four types:
 *   - default: Single call, no retry
 *   - retry: Configurable backoffs with jitter
 *   - parallel: Run N samples, return all successes
 *   - mdap_voting: Multi-sample with consensus voting
 *
 * MACHINE HOOKS:
 * --------------
 * Extension points for machine execution.
 * All methods are optional and can be sync or async.
 *
 * SDKs MUST provide:
 *   - HooksRegistry: Name-based registry for resolving hooks from config
 *
 * SDKs SHOULD provide:
 *   - WebhookHooks: Send events to HTTP endpoint
 *   - CompositeHooks: Combine multiple hook implementations
 *
 * HOOKS REGISTRY:
 * ---------------
 * Maps hook names (strings) to implementations. Machine configs reference
 * hooks by name; the SDK's HooksRegistry resolves them at runtime.
 *
 * This decouples machine configs from any specific language or file path,
 * enabling the same YAML to work across Python, JavaScript, Rust, etc.
 *
 * SDKs MUST provide:
 *   - HooksRegistry with register(), resolve(), has()
 *
 * Built-in registrations (when available in the SDK):
 *   - "logging": LoggingHooks
 *   - "webhook": WebhookHooks (args: { url, timeout?, api_key? })
 *   - "metrics": MetricsHooks
 *   - "distributed-worker": DistributedWorkerHooks
 *
 * LLM BACKEND (OPTIONAL):
 * -----------------------
 * Abstraction over LLM providers.
 *
 * This interface is OPTIONAL - SDKs may use provider SDKs directly.
 * Useful for:
 *   - Unified retry/monitoring across providers
 *   - Provider-agnostic code
 *   - Testing with mock backends
 *
 * MACHINE INVOKER:
 * ----------------
 * Interface for invoking peer machines.
 * Used internally by FlatMachine for `machine:` and `launch:` states.
 *
 * AGENT RESULT:
 * --------------
 * Universal result contract for agent execution across all backends.
 * All fields are optional and use structured data (no classes) for
 * cross-language and cross-process/network compatibility.
 *
 * REGISTRATION BACKEND:
 * ---------------------
 * Worker lifecycle management for distributed execution.
 *
 * SDKs MUST provide:
 *   - SQLiteRegistrationBackend: For local deployments
 *
 * SDKs SHOULD provide:
 *   - MemoryRegistrationBackend: For testing
 *
 * Implementation notes:
 *   - Time units: Python reference SDK uses seconds for all interval values
 *   - Stale threshold: SDKs SHOULD default to 2× heartbeat_interval if not specified
 *
 * WORK BACKEND:
 * -------------
 * Work distribution via named pools with atomic claim.
 *
 * SDKs MUST provide:
 *   - SQLiteWorkBackend: For local deployments
 *
 * SDKs SHOULD provide:
 *   - MemoryWorkBackend: For testing
 *
 * Implementation notes:
 *   - Atomic claim: SDKs MUST ensure no two workers can claim the same job
 *   - Test requirements: Include concurrent claim race condition tests
 *
 * SIGNAL BACKEND:
 * ---------------
 * Durable signal storage for cross-process machine activation.
 *
 * Signals are named-channel messages that wake checkpointed machines.
 * A machine paused at a `wait_for` state checkpoints with a `waiting_channel`
 * tag and exits (no process running). When a signal arrives on that channel,
 * a dispatcher finds matching checkpoints and resumes them.
 *
 * Signal data becomes the `wait_for` state's output — accessible via
 * output.* in output_to_context templates. No new template syntax needed.
 *
 * Channel semantics:
 *   - Addressed: "approval/task-001" → one waiting machine
 *   - Broadcast: "quota/openai"      → N waiting machines (dispatcher controls limit)
 *
 * SDKs MUST provide:
 *   - MemorySignalBackend: For testing and single-process use
 *
 * SDKs SHOULD provide:
 *   - SQLiteSignalBackend: For durable local use
 *
 * TRIGGER BACKEND:
 * ----------------
 * Process activation when signals or work arrive.
 * The OS-native equivalent of Lambda triggers / DynamoDB Streams.
 *
 * Called after SignalBackend.send() or WorkPool.push() to wake
 * a dispatcher process. The dispatcher then queries for matching
 * checkpoints and resumes machines.
 *
 * Deployment mapping:
 *   - NoOpTrigger:  Consumer already running (polling/in-process)
 *   - FileTrigger:  Touch file → launchd WatchPaths (macOS) / systemd PathChanged (Linux)
 *   - SocketTrigger: UDS notify → in-host low-latency wake (optional)
 *   - DynamoDB:     Implicit via Streams → Lambda (no application code)
 *
 * SDKs MUST provide:
 *   - NoOpTrigger: For in-process and polling consumers
 *
 * SDKs SHOULD provide:
 *   - FileTrigger: For OS-level activation with zero running processes
 *
 * BACKEND CONFIGURATION:
 * ----------------------
 * Backend configuration for machine settings.
 *
 * Example in YAML:
 *   settings:
 *     backends:
 *       persistence: local
 *       locking: none
 *       results: memory
 */

export interface ExecutionLock {
    /**
     * Attempt to acquire exclusive lock for the given key.
     * MUST be non-blocking - returns immediately.
     *
     * @param key - Typically the execution_id
     * @returns true if lock acquired, false if already held by another process
     */
    acquire(key: string): Promise<boolean>;

    /**
     * Release the lock for the given key.
     * Safe to call even if lock not held.
     */
    release(key: string): Promise<void>;
}

export interface PersistenceBackend {
    /**
     * Save a checkpoint snapshot.
     * MUST be atomic - either fully written or not at all.
     *
     * @param key - Checkpoint identifier (e.g., "{execution_id}/step_{step}")
     * @param snapshot - The machine state to persist
     */
    save(key: string, snapshot: MachineSnapshot): Promise<void>;

    /**
     * Load a checkpoint snapshot.
     * @returns The snapshot, or null if not found
     */
    load(key: string): Promise<MachineSnapshot | null>;

    /**
     * Delete a checkpoint.
     * Safe to call if key doesn't exist.
     */
    delete(key: string): Promise<void>;

    /**
     * List all keys matching a prefix.
     * Used to find all checkpoints for an execution.
     *
     * @param prefix - Key prefix to match (e.g., "{execution_id}/")
     * @returns Array of matching keys, sorted lexicographically
     */
    list(prefix: string): Promise<string[]>;

    /**
     * List execution IDs, optionally filtered by latest checkpoint state.
     *
     * @param options.event - Filter by latest checkpoint event (e.g., "machine_end")
     * @param options.waiting_channel - Filter by waiting_channel metadata
     * @returns Array of matching execution IDs
     */
    listExecutionIds?(options?: {
        event?: string;
        waiting_channel?: string;
    }): Promise<string[]>;

    /**
     * Delete all checkpoint data for an execution.
     * Safe to call if execution doesn't exist.
     */
    deleteExecution?(execution_id: string): Promise<void>;
}

export interface ResultBackend {
    /**
     * Write data to a URI.
     * MUST notify any blocked readers.
     */
    write(uri: string, data: any): Promise<void>;

    /**
     * Read data from a URI.
     *
     * @param uri - The flatagents:// URI
     * @param options.block - If true, wait until data is available
     * @param options.timeout - Max ms to wait (undefined = forever)
     * @returns The data, or undefined if not found and block=false
     * @throws TimeoutError if timeout expires while blocking
     */
    read(uri: string, options?: {
        block?: boolean;
        timeout?: number;
    }): Promise<any>;

    /**
     * Check if data exists at a URI without reading it.
     */
    exists(uri: string): Promise<boolean>;

    /**
     * Delete data at a URI.
     * Safe to call if URI doesn't exist.
     */
    delete(uri: string): Promise<void>;
}

export interface AgentResult {
    // Content
    output?: Record<string, any> | null;
    content?: string | null;
    raw?: any;  // In-process only, not serialized across boundaries
    
    // Metrics
    usage?: UsageInfo | null;
    cost?: CostInfo | number | null;  // number for backwards compatibility
    metadata?: Record<string, any> | null;
    
    // Completion status
    /** Known values: "stop", "length", "tool_use", "error", "content_filter", "aborted" */
    finish_reason?: string | null;
    
    // Error info (null/undefined = success)
    error?: AgentError | null;
    
    // Rate limit state (normalized for orchestration)
    rate_limit?: RateLimitState | null;
    
    // Provider-specific data (includes raw_headers when available)
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
    /** 
     * Known values: "rate_limit", "timeout", "server_error", "invalid_request",
     * "auth_error", "content_filter", "context_length", "model_unavailable"
     * Custom codes allowed for extension.
     */
    code?: string;
    
    /** Original error type name (e.g., "RateLimitError", "TimeoutError") */
    type?: string;
    
    /** Human-readable error message */
    message: string;
    
    /** HTTP status code if applicable */
    status_code?: number;
    
    /** Whether retry might succeed */
    retryable?: boolean;
}

export interface RateLimitState {
    /** Is any limit exhausted? */
    limited: boolean;
    
    /** Recommended wait time in seconds */
    retry_after?: number;
    
    /** Per-window breakdown for smart orchestration */
    windows?: RateLimitWindow[];
}

export interface RateLimitWindow {
    /** Identifier: "requests_per_minute", "tokens_per_day", etc. */
    name: string;
    
    /** Known values: "requests", "tokens", "input_tokens", "output_tokens" */
    resource: string;
    
    /** Current remaining in this window */
    remaining?: number;
    
    /** Maximum for this window */
    limit?: number;
    
    /** Seconds until this window resets */
    resets_in?: number;
    
    /** Unix timestamp when this window resets */
    reset_at?: number;
}

export interface ProviderData {
    /** Provider name (e.g., "openai", "anthropic", "cerebras") */
    provider?: string;
    
    /** Model identifier */
    model?: string;
    
    /** Provider's request ID for debugging/support */
    request_id?: string;
    
    /** Raw HTTP headers from response (when backend exposes them) */
    raw_headers?: Record<string, string>;
    
    /** Any other provider-specific data */
    [key: string]: any;
}

export interface AgentExecutor {
    execute(input: Record<string, any>, context?: Record<string, any>): Promise<AgentResult>;
    metadata?: Record<string, any>;
}

export interface ExecutionType {
    /**
     * Execute an agent with this strategy.
     */
    execute(executor: AgentExecutor, input: Record<string, any>, context?: Record<string, any>): Promise<AgentResult>;
}

export interface ExecutionConfig {
    type: "default" | "retry" | "parallel" | "mdap_voting";

    // retry options
    backoffs?: number[];  // seconds between retries
    jitter?: number;      // random factor (0-1)

    // parallel/mdap options
    n_samples?: number;   // number of parallel calls
    k_margin?: number;    // mdap consensus threshold
    max_candidates?: number;
}

export interface MachineHooks {
    /** Called once at machine start. Can modify initial context. */
    onMachineStart?(context: Record<string, any>): Record<string, any> | Promise<Record<string, any>>;

    /** Called once at machine end. Can modify final output. */
    onMachineEnd?(context: Record<string, any>, output: any): any | Promise<any>;

    /** Called before each state execution. Can modify context. */
    onStateEnter?(state: string, context: Record<string, any>): Record<string, any> | Promise<Record<string, any>>;

    /** Called after each state execution. Can modify output. */
    onStateExit?(state: string, context: Record<string, any>, output: any): any | Promise<any>;

    /** Called before transition. Can redirect to different state. */
    onTransition?(from: string, to: string, context: Record<string, any>): string | Promise<string>;

    /** Called on error. Return state name to recover, null to propagate. */
    onError?(state: string, error: Error, context: Record<string, any>): string | null | Promise<string | null>;

    /** Called for custom actions defined in state config. */
    onAction?(action: string, context: Record<string, any>): Record<string, any> | Promise<Record<string, any>>;
}

export interface HooksRegistry {
    /**
     * Register a hooks implementation by name.
     * @param name - Hook name referenced in machine config (e.g., "my-hooks")
     * @param factory - Class constructor or factory function
     */
    register(name: string, factory: HooksFactory): void;

    /**
     * Resolve a HooksRef from machine config into a MachineHooks instance.
     * - String: lookup by name, no args
     * - HooksRefConfig: lookup by name, pass args to factory
     * - Array: resolve each entry, combine with CompositeHooks
     * @throws Error if name is not registered
     */
    resolve(ref: HooksRef): MachineHooks;

    /** Check if a name is registered. */
    has(name: string): boolean;
}

/**
 * Factory for creating MachineHooks instances.
 * Can be a class constructor or a function.
 */
export type HooksFactory =
    | { new (args?: Record<string, any>): MachineHooks }
    | ((args?: Record<string, any>) => MachineHooks);

import { HooksRef, HooksRefConfig } from "./flatmachine";

export interface LLMBackend {
    /** Total cost accumulated across all calls. */
    totalCost: number;

    /** Total API calls made. */
    totalApiCalls: number;

    /** Call LLM and return content string. */
    call(messages: Message[], options?: LLMOptions): Promise<string>;

    /** Call LLM and return raw provider response. */
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
        arguments: string;  // JSON string
    };
}

export interface LLMOptions {
    temperature?: number;
    max_tokens?: number;
    tools?: ToolDefinition[];
    response_format?: { type: "json_object" } | { type: "text" };
}

export interface ToolDefinition {
    type: "function";
    function: {
        name: string;
        description?: string;
        parameters?: Record<string, any>;  // JSON Schema
    };
}

export interface MachineInvoker {
    /**
     * Invoke a machine and wait for result.
     */
    invoke(
        machineName: string,
        input: Record<string, any>,
        options?: { timeout?: number }
    ): Promise<Record<string, any>>;

    /**
     * Launch a machine fire-and-forget style.
     * @returns The execution_id of the launched machine
     */
    launch(
        machineName: string,
        input: Record<string, any>
    ): Promise<string>;
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
    /**
     * Clone a persisted machine state under a new execution ID.
     *
     * Reference implementation (SDK-specific internals may vary):
     * 1) Deep-copy the source snapshot
     * 2) Set execution_id = new_execution_id
     * 3) Set created_at = current UTC ISO timestamp
     * 4) Set parent_execution_id = source.execution_id
     * 5) Drop pending_launches (avoid duplicate child ownership)
     * 6) Persist under new_execution_id via checkpoint manager/backend
     * 7) Return the cloned snapshot
     */
    clone_snapshot(
        snapshot: MachineSnapshot,
        new_execution_id: string,
        persistence: PersistenceBackend
    ): Promise<MachineSnapshot>;
}

export interface LaunchIntent {
    execution_id: string;
    machine: string;
    input: Record<string, any>;
    launched: boolean;
}

export interface RegistrationBackend {
    /**
     * Register a new worker.
     * Creates a new worker record with status "active".
     */
    register(worker: WorkerRegistration): Promise<WorkerRecord>;

    /**
     * Update worker's last_heartbeat timestamp.
     * Can optionally update metadata.
     */
    heartbeat(worker_id: string, metadata?: Record<string, any>): Promise<void>;

    /**
     * Update worker status.
     * Status values (string, not enum for extensibility):
     *   - "active": Worker is running and healthy
     *   - "terminating": Worker received shutdown signal
     *   - "terminated": Worker exited cleanly
     *   - "lost": Worker failed heartbeat, presumed dead
     */
    updateStatus(worker_id: string, status: string): Promise<void>;

    /**
     * Get a worker record by ID.
     * @returns The worker record, or null if not found
     */
    get(worker_id: string): Promise<WorkerRecord | null>;

    /**
     * List workers matching filter criteria.
     */
    list(filter?: WorkerFilter): Promise<WorkerRecord[]>;
}

export interface WorkerRegistration {
    worker_id: string;
    host?: string;
    pid?: number;
    capabilities?: string[];  // e.g., ["gpu", "paper-analysis"]
    pool_id?: string;         // Worker pool grouping
    started_at: string;
}

export interface WorkerRecord extends WorkerRegistration {
    status: string;           // See status values in RegistrationBackend.updateStatus
    last_heartbeat: string;
    current_task_id?: string;
}

export interface WorkerFilter {
    status?: string | string[];
    capability?: string;
    pool_id?: string;
    stale_threshold_seconds?: number;  // Filter workers with old heartbeats
}

export interface WorkBackend {
    /**
     * Get a named work pool.
     * Creates the pool if it doesn't exist.
     */
    pool(name: string): WorkPool;
}

export interface WorkPool {
    /**
     * Add work item to the pool.
     * @param item - The work data (will be JSON serialized)
     * @param options.max_retries - Max retry attempts before poisoning (default: 3)
     * @returns The item ID
     */
    push(item: any, options?: { max_retries?: number }): Promise<string>;

    /**
     * Atomically claim next available item.
     * MUST be atomic - no two workers can claim the same job.
     * @returns The claimed item, or null if pool is empty
     */
    claim(worker_id: string): Promise<WorkItem | null>;

    /**
     * Mark item as complete.
     * Sets status to "done" and stores result.
     */
    complete(item_id: string, result?: any): Promise<void>;

    /**
     * Mark item as failed.
     * Increments attempts. If attempts >= max_retries, marks as "poisoned".
     * Otherwise returns to "pending" status for retry.
     */
    fail(item_id: string, error?: string): Promise<void>;

    /**
     * Get pool depth (unclaimed pending items).
     */
    size(): Promise<number>;

    /**
     * Release all jobs claimed by a worker.
     * Used for stale worker cleanup.
     * @returns Number of jobs released
     */
    releaseByWorker(worker_id: string): Promise<number>;
}

export interface WorkItem {
    id: string;
    data: any;
    claimed_by?: string;
    claimed_at?: string;
    attempts: number;
    max_retries: number;  // default: 3
}

// Job status values (string):
// - "pending": Available for claim
// - "claimed": Currently being processed
// - "done": Successfully completed
// - "poisoned": Failed max_retries times, will not be retried

export interface SignalBackend {
    /**
     * Send a signal to a named channel.
     * @param channel - Channel name (e.g., "approval/task-001", "quota/openai")
     * @param data - Signal payload (JSON-serializable)
     * @returns Signal ID
     */
    send(channel: string, data: any): Promise<string>;

    /**
     * Atomically consume the next signal on a channel.
     * Removes the signal from storage.
     * @returns Signal or null if none pending
     */
    consume(channel: string): Promise<Signal | null>;

    /**
     * Peek at pending signals without consuming.
     * @returns Array of pending signals on this channel
     */
    peek(channel: string): Promise<Signal[]>;

    /**
     * List channels that have pending signals.
     * Used by dispatcher to find actionable channels.
     */
    channels(): Promise<string[]>;
}

export interface Signal {
    id: string;
    channel: string;
    data: any;
    created_at: string;
}

export interface TriggerBackend {
    /**
     * Signal that activity occurred on a channel.
     * Implementation touches a file, writes to a socket, or no-ops.
     *
     * @param channel - Channel name
     */
    notify(channel: string): Promise<void>;
}

export interface BackendConfig {
    /** Checkpoint storage. Default: memory */
    persistence?: "memory" | "local" | "sqlite" | "redis" | "postgres" | "s3" | "dynamodb";

    /** Execution locking. Default: none */
    locking?: "none" | "local" | "sqlite" | "redis" | "consul" | "dynamodb";

    /** Inter-machine results. Default: memory */
    results?: "memory" | "redis" | "dynamodb";

    /** Worker registration. Default: memory */
    registration?: "memory" | "sqlite" | "redis" | "dynamodb";

    /** Work pool. Default: memory */
    work?: "memory" | "sqlite" | "redis" | "dynamodb";

    /** Signal storage. Default: memory */
    signal?: "memory" | "sqlite" | "redis" | "dynamodb";

    /** Trigger activation. Default: none */
    trigger?: "none" | "file" | "socket";

    /** Path for sqlite backends (registration, work, and signals share this) */
    sqlite_path?: string;

    /** Base path for file triggers (default: /tmp/flatmachines) */
    trigger_path?: string;

    /** DynamoDB table name (single-table design) */
    dynamodb_table?: string;

    /** AWS region for DynamoDB */
    aws_region?: string;
}

export const SPEC_VERSION = "2.2.2";

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


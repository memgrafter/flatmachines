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
 *
 * OPTIONAL IMPLEMENTATIONS:
 * -------------------------
 *   - Distributed backends (Redis, Postgres, etc.)
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
 * SDKs SHOULD provide:
 *   - WebhookHooks: Send events to HTTP endpoint
 *   - CompositeHooks: Combine multiple hook implementations
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

export interface ExecutionType {
    /**
     * Execute a function with this strategy.
     *
     * @param fn - The async function to execute (typically agent.call)
     * @returns The result(s) according to strategy
     */
    execute<T>(fn: () => Promise<T>): Promise<T>;
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

    /**
     * Called when an agent requests a tool call during tool_loop execution.
     * Must return the tool result which will be sent back to the agent.
     *
     * @param toolName - Name of the tool to execute
     * @param arguments - Arguments passed to the tool (parsed from JSON)
     * @param context - Current machine context
     * @returns Tool execution result (will be JSON serialized for the agent)
     */
    onToolCall?(toolName: string, arguments: Record<string, any>, context: Record<string, any>): any | Promise<any>;
}

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
    top_p?: number;
    top_k?: number;
    frequency_penalty?: number;
    presence_penalty?: number;
    repetition_penalty?: number;
    seed?: number;
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
    parameters?: Record<string, any>;  // JSON Schema
    strict?: boolean;  // For strict structured outputs
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
}

export interface LaunchIntent {
    execution_id: string;
    machine: string;
    input: Record<string, any>;
    launched: boolean;
}

/**
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
 */
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

/**
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
 */
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

export interface BackendConfig {
    /** Checkpoint storage. Default: memory */
    persistence?: "memory" | "local" | "redis" | "postgres" | "s3";

    /** Execution locking. Default: none */
    locking?: "none" | "local" | "redis" | "consul";

    /** Inter-machine results. Default: memory */
    results?: "memory" | "redis";

    /** Worker registration. Default: memory */
    registration?: "memory" | "sqlite" | "redis";

    /** Work pool. Default: memory */
    work?: "memory" | "sqlite" | "redis";

    /** Path for sqlite backends (registration and work share this) */
    sqlite_path?: string;
}

export const SPEC_VERSION = "0.9.0";

/**
 * Wrapper interface for JSON schema generation.
 * Groups all runtime interfaces that SDKs must implement.
 */
export interface SDKRuntimeWrapper {
    spec: "flatagents-runtime";
    spec_version: typeof SPEC_VERSION;
    execution_lock?: ExecutionLock;
    persistence_backend?: PersistenceBackend;
    result_backend?: ResultBackend;
    execution_config?: ExecutionConfig;
    machine_hooks?: MachineHooks;
    llm_backend?: LLMBackend;
    machine_invoker?: MachineInvoker;
    backend_config?: BackendConfig;
    machine_snapshot?: MachineSnapshot;
    registration_backend?: RegistrationBackend;
    work_backend?: WorkBackend;
}


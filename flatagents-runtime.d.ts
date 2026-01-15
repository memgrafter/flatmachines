/**
 * FlatAgents Runtime Interface Spec
 * 
 * This file defines the runtime interfaces that SDKs MUST implement
 * to be considered compliant. These are NOT configuration schemas
 * (see flatagent.d.ts and flatmachine.d.ts for those).
 * 
 * VERSION: 0.1.0
 * 
 * Required implementations:
 *   - ExecutionLock: NoOpLock (MUST), LocalFileLock (SHOULD)
 *   - PersistenceBackend: MemoryBackend (MUST), LocalFileBackend (SHOULD)
 *   - ResultBackend: InMemoryResultBackend (MUST)
 *   - ExecutionType: Default, Retry, Parallel, MDAPVoting (MUST)
 *   - MachineHooks: Base interface (MUST)
 * 
 * Optional implementations:
 *   - Distributed backends (Redis, Postgres, etc.)
 *   - LLMBackend (SDK may use native provider SDKs)
 */

// =============================================================================
// Execution Locking
// =============================================================================

/**
 * Prevents concurrent execution of the same machine instance.
 * 
 * SDKs MUST provide:
 *   - NoOpLock: For when locking is handled externally or disabled
 * 
 * SDKs SHOULD provide:
 *   - LocalFileLock: For single-node deployments using fcntl/flock
 * 
 * Distributed deployments should implement Redis/Consul/etcd locks.
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

// =============================================================================
// Persistence Backend
// =============================================================================

/**
 * Storage backend for machine checkpoints.
 * 
 * SDKs MUST provide:
 *   - MemoryBackend: For testing and ephemeral runs
 * 
 * SDKs SHOULD provide:
 *   - LocalFileBackend: For durable local storage with atomic writes
 */
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

// =============================================================================
// Result Backend
// =============================================================================

/**
 * Inter-machine communication via URI-addressed results.
 * 
 * URI format: flatagents://{execution_id}/{path}
 *   - path is typically "result" or "checkpoint"
 * 
 * SDKs MUST provide:
 *   - InMemoryResultBackend: For single-process execution
 */
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

// =============================================================================
// Execution Types
// =============================================================================

/**
 * Execution strategy for agent calls.
 * 
 * SDKs MUST implement all four types:
 *   - default: Single call, no retry
 *   - retry: Configurable backoffs with jitter
 *   - parallel: Run N samples, return all successes
 *   - mdap_voting: Multi-sample with consensus voting
 */
export interface ExecutionType {
    /**
     * Execute a function with this strategy.
     * 
     * @param fn - The async function to execute (typically agent.call)
     * @returns The result(s) according to strategy
     */
    execute<T>(fn: () => Promise<T>): Promise<T>;
}

/**
 * Configuration for execution types.
 * Matches flatmachine.d.ts ExecutionConfig.
 */
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

// =============================================================================
// Machine Hooks
// =============================================================================

/**
 * Extension points for machine execution.
 * All methods are optional and can be sync or async.
 * 
 * SDKs SHOULD provide:
 *   - WebhookHooks: Send events to HTTP endpoint
 *   - CompositeHooks: Combine multiple hook implementations
 */
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

// =============================================================================
// LLM Backend (Optional)
// =============================================================================

/**
 * Abstraction over LLM providers.
 * 
 * This interface is OPTIONAL - SDKs may use provider SDKs directly.
 * Useful for:
 *   - Unified retry/monitoring across providers
 *   - Provider-agnostic code
 *   - Testing with mock backends
 */
export interface LLMBackend {
    /** Total cost accumulated across all calls. */
    totalCost: number;

    /** Total API calls made. */
    totalApiCalls: number;

    /**
     * Call LLM and return content string.
     */
    call(messages: Message[], options?: LLMOptions): Promise<string>;

    /**
     * Call LLM and return raw provider response.
     */
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

// =============================================================================
// Machine Invoker (for peer machine calls)
// =============================================================================

/**
 * Interface for invoking peer machines.
 * Used internally by FlatMachine for `machine:` and `launch:` states.
 */
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

// =============================================================================
// Shared Types (re-exported from flatmachine.d.ts)
// =============================================================================

/**
 * Machine checkpoint format.
 * See flatmachine.d.ts for canonical definition.
 */
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

// =============================================================================
// Backend Configuration (proposed addition to settings)
// =============================================================================

/**
 * Backend configuration for machine settings.
 * 
 * Example in YAML:
 *   settings:
 *     backends:
 *       persistence: local
 *       locking: none
 *       results: memory
 */
export interface BackendConfig {
    /** Checkpoint storage. Default: memory */
    persistence?: "memory" | "local" | "redis" | "postgres" | "s3";

    /** Execution locking. Default: none */
    locking?: "none" | "local" | "redis" | "consul";

    /** Inter-machine results. Default: memory */
    results?: "memory" | "redis";
}

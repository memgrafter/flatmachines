/**
 * FlatMachine Configuration Schema
 * ================================
 *
 * A machine defines how agents are connected and executed:
 * states, transitions, conditions, and loops.
 *
 * While flatagents defines WHAT each agent is (model + prompts + output schema),
 * flatmachines defines HOW agents are connected and executed.
 *
 * STRUCTURE:
 * ----------
 * spec           - Fixed string "flatmachine"
 * spec_version   - Semver string
 * data           - The machine configuration
 * metadata       - Extensibility layer
 *
 * DERIVED SCHEMAS:
 * ----------------
 * This file (/flatmachine.d.ts) is the SOURCE OF TRUTH for all FlatMachine schemas.
 * Other schemas (JSON Schema, etc.) are DERIVED from this file using scripts.
 * See: /scripts/generate-spec-assets.ts
 *
 * DATA FIELDS:
 * ------------
 * name               - Machine identifier
 * expression_engine  - "simple" (default) or "cel"
 * context            - Initial context values (Jinja2 templates)
 * agents             - Map of agent name to config file path or inline config
 * machines           - Map of machine name to config file path or inline config
 * states             - Map of state name to state definition
 * settings           - Optional settings (hooks, etc.)
 *
 * STATE FIELDS:
 * -------------
 * type              - "initial" or "final" (optional)
 * agent             - Agent name to execute (from agents map)
 * machine           - Machine name or array for parallel execution (from machines map)
 * execution         - Execution type config: {type: "retry", backoffs: [...], jitter: 0.1}
 * on_error          - Error handling: "error_state" or {default: "...", ErrorType: "..."}
 * action            - Hook action to execute
 * input             - Input mapping (Jinja2 templates)
 * output_to_context - Map agent output to context (Jinja2 templates)
 * output            - Final output (for final states)
 * transitions       - Ordered list of transitions
 * tool_loop         - Enable multi-round tool calling (boolean or ToolLoopConfig)
 * tools             - Tool definitions for this state (OpenAI function format)
 * tool_choice       - Control tool usage: "none", "auto", "required", or specific
 *
 * PARALLEL EXECUTION (v0.4.0):
 * ----------------------------
 * machine           - Can be string[] for parallel machine invocation
 * foreach           - Jinja2 expression yielding array for dynamic parallelism
 * as                - Variable name for current item in foreach (default: "item")
 * key               - Jinja2 expression for result key (optional, results array if omitted)
 * mode              - Completion semantics: "settled" (default) or "any"
 * timeout           - Timeout in seconds (0 = never)
 * launch            - Machine(s) to start fire-and-forget
 * launch_input      - Input for launched machines
 *
 * NOTE: Only `machine` supports parallel invocation (string[]), not `agent`.
 * Machines are self-healing with checkpoint/resume and error handling.
 * Agents are raw LLM calls that can fail without recovery. Wrap agents in
 * machines to get retry logic, checkpointing, and proper failure handling
 * before running them in parallel.
 *
 * RUNTIME MODEL (v0.4.0):
 * -----------------------
 * All machine invocations are launches. Communication via result backend.
 *
 *   machine: child      → launch + blocking read
 *   machine: [a,b,c]    → launch all + wait for all
 *   launch: child       → launch only, no read
 *
 * URI Scheme: flatagents://{execution_id}/[checkpoint|result]
 *
 * Parent generates child's execution_id, passes it to child. Child writes
 * result to its URI. Parent reads from known URI. No direct messaging.
 *
 * Local SDKs may optimize blocking reads as function returns (in-memory backend).
 * This decouples output from read, enabling both local and distributed execution.
 *
 * Launch intents are checkpointed before execution (outbox pattern).
 * On resume, SDK checks if launched machine exists before re-launching.
 *
 * TRANSITION FIELDS:
 * ------------------
 * condition         - Expression to evaluate (optional, default: always true)
 * to                - Target state name
 *
 * EXPRESSION SYNTAX (Simple Mode):
 * --------------------------------
 * Comparisons: ==, !=, <, <=, >, >=
 * Boolean: and, or, not
 * Field access: context.field, input.field, output.field
 * Literals: "string", 42, true, false, null
 *
 * Example: "context.score >= 8 and context.round < 4"
 *
 * EXPRESSION SYNTAX (CEL Mode):
 * -----------------------------
 * All simple syntax, plus:
 * List macros: context.items.all(i, i > 0)
 * String methods: context.name.startsWith("test")
 * Timestamps: context.created > now - duration("24h")
 *
 * EXAMPLE CONFIGURATION:
 * ----------------------
 *
 *   spec: flatmachine
 *   spec_version: "0.7.0"
 *
 *   data:
 *     name: writer-critic-loop
 *
 *     context:
 *       product: "{{ input.product }}"
 *       score: 0
 *       round: 0
 *
 *     agents:
 *       writer: ./writer.yml
 *       critic: ./critic.yml
 *
 *     states:
 *       start:
 *         type: initial
 *         transitions:
 *           - to: write
 *
 *       write:
 *         agent: writer
 *         execution:
 *           type: retry
 *           backoffs: [2, 8, 16, 35]
 *           jitter: 0.1
 *         on_error: error_state
 *         input:
 *           product: "{{ context.product }}"
 *         output_to_context:
 *           tagline: "{{ output.tagline }}"
 *         transitions:
 *           - to: review
 *
 *       review:
 *         agent: critic
 *         input:
 *           tagline: "{{ context.tagline }}"
 *         output_to_context:
 *           score: "{{ output.score }}"
 *           round: "{{ context.round + 1 }}"
 *         transitions:
 *           - condition: "context.score >= 8"
 *             to: done
 *           - to: write
 *
 *       done:
 *         type: final
 *         output:
 *           tagline: "{{ context.tagline }}"
 *
 *   metadata:
 *     description: "Iterative writer-critic loop"
 *
 * PARALLEL EXECUTION EXAMPLE:
 * ---------------------------
 *
 *   states:
 *     parallel_review:
 *       machine: [legal_review, tech_review, finance_review]
 *       input:
 *         document: "{{ context.document }}"
 *       mode: settled
 *       timeout: 120
 *       output_to_context:
 *         reviews: "{{ output }}"
 *       transitions:
 *         - to: synthesize
 *
 * DYNAMIC PARALLELISM EXAMPLE:
 * ----------------------------
 *
 *   states:
 *     process_all:
 *       foreach: "{{ context.documents }}"
 *       as: doc
 *       key: "{{ doc.id }}"
 *       machine: doc_processor
 *       input:
 *         document: "{{ doc }}"
 *       mode: settled
 *       output_to_context:
 *         results: "{{ output }}"
 *       transitions:
 *         - to: aggregate
 *
 * LAUNCH (FIRE-AND-FORGET) EXAMPLE:
 * ---------------------------------
 *
 *   states:
 *     kickoff:
 *       launch: expensive_analysis
 *       launch_input:
 *         document: "{{ context.document }}"
 *         result_address: "results/{{ context.job_id }}"
 *       transitions:
 *         - to: continue_immediately
 *
 * TOOL LOOP EXAMPLE:
 * ------------------
 * Multi-round tool calling allows an agent to call tools repeatedly until
 * it has enough information to produce a final response.
 *
 *   states:
 *     research:
 *       agent: researcher
 *       tool_loop:
 *         max_rounds: 10
 *       tools:
 *         - type: function
 *           function:
 *             name: search_web
 *             description: Search the web for information
 *             parameters:
 *               type: object
 *               properties:
 *                 query: { type: string, description: "Search query" }
 *               required: [query]
 *         - type: function
 *           function:
 *             name: read_url
 *             description: Read content from a URL
 *             parameters:
 *               type: object
 *               properties:
 *                 url: { type: string, description: "URL to read" }
 *               required: [url]
 *       input:
 *         question: "{{ context.question }}"
 *       output_to_context:
 *         answer: "{{ output.answer }}"
 *       transitions:
 *         - to: done
 *
 * The machine will call hooks.on_tool_call(tool_name, arguments) for each
 * tool call. Hooks must implement this method to execute tools and return results.
 *
 * PERSISTENCE (v0.2.0):
 * --------------------
 * MachineSnapshot    - Wire format for checkpoints (execution_id, state, context, step)
 * PersistenceConfig  - Backend config: {enabled: true, backend: "local"|"memory"}
 * checkpoint_on      - Events to checkpoint: ["machine_start", "execute", "machine_end"]
 *
 * MACHINE LAUNCHING:
 * ------------------
 * States can launch peer machines via `machine:` field
 * MachineReference   - {path: "./peer.yml"} or {inline: {...}}
 *
 * URI SCHEME:
 * -----------
 * Format: flatagents://{execution_id}[/{path}]
 *
 * Paths:
 *   /checkpoint     - Machine state for resume
 *   /result         - Final output after completion
 *
 * Examples:
 *   flatagents://550e8400-e29b-41d4-a716-446655440000/checkpoint
 *   flatagents://550e8400-e29b-41d4-a716-446655440000/result
 *
 * Each machine execution has a unique_id. Parent generates child's ID
 * before launching, enabling parent to know where to read results without
 * any child-to-parent messaging.
 *
 * EXECUTION CONFIG:
 * -----------------
 * type           - "default" | "retry" | "parallel" | "mdap_voting"
 * backoffs       - Retry: seconds between retries
 * jitter         - Retry: random factor (0-1)
 * n_samples      - Parallel: number of samples
 * k_margin       - MDAP voting: consensus threshold
 * max_candidates - MDAP voting: max candidates
 *
 * MACHINE INPUT:
 * --------------
 * Per-machine input configuration for parallel execution.
 * Use when different machines need different inputs.
 *
 * LAUNCH INTENT:
 * --------------
 * Launch intent for outbox pattern.
 * Recorded in checkpoint before launching to ensure exactly-once semantics.
 *
 * MACHINE SNAPSHOT:
 * -----------------
 * Wire format for checkpoints.
 * parent_execution_id - Lineage tracking (v0.4.0)
 * pending_launches    - Outbox pattern (v0.4.0)
 */

export const SPEC_VERSION = "0.9.0";

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
  hooks?: HooksConfig;
}

/**
 * Configuration for loading hooks from file or module.
 *
 * File-based (preferred for self-contained skills):
 *   hooks:
 *     file: "./hooks.py"
 *     class: "MyHooks"
 *     args:
 *       working_dir: "."
 *
 * Module-based (for installed packages):
 *   hooks:
 *     module: "mypackage.hooks"
 *     class: "MyHooks"
 *     args:
 *       api_key: "{{ input.api_key }}"
 *
 * Fields:
 *   file   - Path to Python file containing hooks class (relative to machine.yml)
 *   module - Python module path to import
 *   class  - Class name to instantiate (required)
 *   args   - Arguments to pass to hooks constructor
 */
export interface HooksConfig {
  file?: string;
  module?: string;
  class: string;
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
  input?: Record<string, any>;
  output_to_context?: Record<string, any>;
  output?: Record<string, any>;
  transitions?: Transition[];
  tool_loop?: boolean | ToolLoopConfig;
  tools?: ToolDefinition[];
  tool_choice?: ToolChoice;
  sampling?: "single" | "multi";
  foreach?: string;
  as?: string;
  key?: string;
  mode?: "settled" | "any";
  timeout?: number;
  launch?: string | string[];
  launch_input?: Record<string, any>;
}

/**
 * Configuration for multi-round tool calling loops.
 *
 * When tool_loop is enabled on a state with an agent, the machine will:
 * 1. Call the agent with available tools
 * 2. If the agent returns tool calls, execute them
 * 3. Send tool results back to the agent
 * 4. Repeat until agent returns final response (no tool calls) or max_rounds reached
 *
 * Example:
 *   states:
 *     process:
 *       agent: assistant
 *       tool_loop:
 *         max_rounds: 10
 *         tools:
 *           - type: function
 *             function:
 *               name: search
 *               description: Search the knowledge base
 *               parameters:
 *                 type: object
 *                 properties:
 *                   query: { type: string }
 *       input:
 *         question: "{{ context.question }}"
 */
export interface ToolLoopConfig {
  /** Maximum number of tool call rounds (default: 10) */
  max_rounds?: number;
  /** Tool definitions (OpenAI function calling format) */
  tools?: ToolDefinition[];
  /** Control tool usage: "none", "auto", "required", or specific tool */
  tool_choice?: ToolChoice;
  /** Allow parallel tool calls in single response (default: true) */
  parallel_tool_calls?: boolean;
}

export type ToolChoice =
  | "none"
  | "auto"
  | "required"
  | { type: "function"; function: { name: string } };

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

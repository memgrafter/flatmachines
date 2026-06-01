/**
FlatMachine Configuration Schema

A machine defines how agents are connected and executed:
states, transitions, conditions, and loops.

While flatagents defines WHAT each agent is (model + prompts + output schema),
flatmachines defines HOW agents are connected and executed.

STRUCTURE
spec           - Fixed string "flatmachine"
spec_version   - Semver string
data           - The machine configuration
metadata       - Extensibility layer

DERIVED SCHEMAS
This file (/flatmachine.d.ts) is the SOURCE OF TRUTH for all FlatMachine schemas.
Other schemas (JSON Schema, etc.) are DERIVED from this file using scripts.
See /scripts/generate-spec-assets.ts

DATA FIELDS
Core
name               - Machine identifier
expression_engine  - "simple" (default) or "cel"

Context + references
context            - Initial context values (Jinja2 templates)
agents             - Map of agent name to AgentRef (path, inline config, or typed adapter ref)
machines           - Map of machine name to config file path or inline config

Orchestration + runtime config
states             - Map of state name to state definition
settings           - Optional settings
persistence        - Checkpoint backend settings
lifecycle_hooks    - Machine lifecycle hook reference(s) resolved by runtime registry

STATE FIELDS
Lifecycle / control flow
type              - "initial" or "final" (optional)
on_error          - Error handling: "error_state" or {default: "...", ErrorType: "..."}
timeout           - State timeout in seconds (context-dependent)
transitions       - Ordered list of transitions ({ condition?: string, to: string })

Data mapping
input             - Input mapping (Jinja2 templates)
output_to_context - Map output to context (Jinja2 templates)
output            - Final output mapping (typically for final states)

Agent execution
agent             - Agent name to execute (from agents map)
execution         - Execution type config: {type: "retry", backoffs: [...], jitter: 0.1}
sampling          - Sampling hint (single|multi)
tool_loop         - Enable/configure model-driven tool loop

Machine invocation / parallelism
machine           - Machine name or array for parallel execution (from machines map)
foreach           - Jinja2 expression yielding array for dynamic parallelism
as                - Variable name for foreach item (default: "item")
key               - Optional key expression for foreach result mapping
mode              - Completion semantics: "settled" (default) or "any"

State hooks
action            - Hook action to execute
hooks             - State-local hook reference(s) resolved by runtime registry

External signal wait
wait_for          - Channel to wait for external signal (Jinja2 template)

Fire-and-forget launch
launch            - Machine(s) to start without blocking
launch_input      - Input for launched machines

STATE NOTES
- Only `machine` supports array-based parallel invocation (`machine: [a, b, c]`), not `agent`.
- State hooks are local to the state where they are declared.
- `wait_for` checkpoints the machine and exits; it resumes when a matching signal arrives.
- `launch` is fire-and-forget, while `machine` performs launch + blocking read.
- For fault-tolerant parallelism, run work as machines (checkpoint/retry/error handling),
  not raw agent calls.

RUNTIME MODEL
All machine invocations are launches. Communication via result backend.
  machine: child      → launch + blocking read
  machine: [a,b,c]    → launch all + wait for all
  launch: child       → launch only, no read

URI scheme flatagents://{execution_id}/[checkpoint|result]
Parent generates child's execution_id, passes it to child. Child writes
result to its URI. Parent reads from known URI. No direct messaging.

Local SDKs may optimize blocking reads as function returns (in-memory backend).
This decouples output from read, enabling both local and distributed execution.

Launch intents are checkpointed before execution (outbox pattern).
On resume, SDK checks if launched machine exists before re-launching.

EXPRESSION SYNTAX (Simple Mode)
Comparisons: ==, !=, <, <=, >, >=
Boolean: and, or, not
Field access: context.field, input.field, output.field
Literals: "string", 42, true, false, null
Example: "context.score >= 8 and context.round < 4"

EXPRESSION SYNTAX (CEL Mode)
All simple syntax, plus:
List macros: context.items.all(i, i > 0)
String methods: context.name.startsWith("test")
Timestamps: context.created > now - duration("24h")

EXAMPLES
See `sdk/examples/` and `AGENTS.md` for full workflow examples

PERSISTENCE
MachineSnapshot    - Wire format for checkpoints (execution_id, state, context, step)
PersistenceConfig  - Backend config: {enabled: true, backend: "local"|"memory"|"sqlite"}
checkpoint_on      - Events to checkpoint: ["machine_start", "execute", "machine_end"]

MACHINE LAUNCHING
States can launch peer machines via `machine:` field
MachineReference   - {path: "./peer.yml"} or {inline: {...}}

URI SCHEME
Format: flatagents://{execution_id}[/{path}]

Paths
  /checkpoint     - Machine state for resume
  /result         - Final output after completion

Examples
  flatagents://550e8400-e29b-41d4-a716-446655440000/checkpoint
  flatagents://550e8400-e29b-41d4-a716-446655440000/result

Each machine execution has a unique_id. Parent generates child's ID
before launching, enabling parent to know where to read results without
any child-to-parent messaging.

EXECUTION CONFIG
type           - "default" | "retry" | "parallel" | "mdap_voting"
backoffs       - Retry: seconds between retries
jitter         - Retry: random factor (0-1)
n_samples      - Parallel: number of samples
k_margin       - MDAP voting: consensus threshold
max_candidates - MDAP voting: max candidates

MACHINE INPUT
Per-machine input configuration for parallel execution.
Use when different machines need different inputs.

LAUNCH INTENT
Launch intent for outbox pattern.
Recorded in checkpoint before launching to ensure exactly-once semantics.

HOOK REFERENCES
Hooks are referenced by name and resolved via a runtime HooksRegistry.
This keeps machine configs language-agnostic — the same YAML works with
Python, JavaScript, Rust, or any other SDK.

Lifecycle hooks apply to machine-level lifecycle events only:
  lifecycle_hooks: "logging"

State hooks apply only to the declaring state:
  states:
    review:
      hooks: "review-hooks"

With constructor args
  hooks:
    name: "my-hooks"
    args:
      working_dir: "."

Composite (multiple hooks)
  hooks:
    - "logging"
    - name: "my-hooks"
      args: { working_dir: "." }

The same HooksRef shape is used by `lifecycle_hooks` and state `hooks`.
The SDK's HooksRegistry maps names to implementations.
Built-in hooks (e.g., "logging", "webhook") are pre-registered.
Custom hooks are registered by the runner before machine execution.

MACHINE SNAPSHOT
Wire format for checkpoints.
context.machine    - Runtime-owned metadata (execution_id, step, state, cost/calls)
                     Rebuilt from live machine state on each step/resume.
parent_execution_id - Lineage tracking
pending_launches    - Outbox pattern
waiting_channel     - Signal channel this machine is blocked on (v1.2.0)
config_hash         - Content-addressed machine config key for cross-SDK resume (v2.1.0)
*/

export const SPEC_VERSION = "4.2.0";

export interface MachineWrapper {
  spec: "flatmachine";
  spec_version: string;
  data: MachineData;
  metadata?: Record<string, any>;
}

/** Runtime-owned metadata injected at context.machine */
export interface MachineRuntimeMetadata {
  execution_id: string;
  machine_name: string;
  parent_execution_id?: string;
  spec_version: string;
  step: number;
  current_state: string;
  total_api_calls: number;
  total_cost: number;
  depth?: number;
}

export interface MachineData {
  name?: string;
  expression_engine?: "simple" | "cel";
  /**
   * Initial user context. Runtime reserves `context.machine` and overwrites
   * it each step/resume with MachineRuntimeMetadata.
   */
  context?: Record<string, any> & { machine?: MachineRuntimeMetadata };
  agents?: Record<string, AgentRef>;
  machines?: Record<string, string | MachineWrapper>;
  states: Record<string, StateDefinition>;
  settings?: MachineSettings;
  persistence?: PersistenceConfig;
  lifecycle_hooks?: HooksRef;
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
  max_depth?: number;
  [key: string]: any;
}

export interface StateDefinition {
  // Lifecycle / control flow
  on_error?: string | Record<string, string>;
  timeout?: number;
  transitions?: Transition[];
  type?: "initial" | "final";

  // Data mapping
  input?: Record<string, any>;
  output?: Record<string, any>;
  output_to_context?: Record<string, any>;

  // Agent execution
  agent?: string;
  execution?: ExecutionConfig;
  sampling?: "single" | "multi";
  tool_loop?: boolean | ToolLoopStateConfig;

  // Machine invocation / parallelism
  as?: string;
  foreach?: string;
  key?: string;
  machine?: string | string[] | MachineInput[];
  mode?: "settled" | "any";

  // State action
  action?: string;

  // State hooks
  hooks?: HooksRef;

  // External signal wait
  wait_for?: string;

  // Fire-and-forget launch
  launch?: string | string[];
  launch_input?: Record<string, any>;
}

export interface ToolLoopStateConfig {
  max_tool_calls?: number;  // default: 0 (unlimited)
  max_turns?: number;       // default: 0 (unlimited); counts LLM calls, not tool calls
  allowed_tools?: string[]; // allowlist
  denied_tools?: string[];  // denylist (wins)
  tool_timeout?: number;    // seconds, default: 0 (unlimited)
  total_timeout?: number;   // seconds, default: 0 (unlimited)
  max_cost?: number;        // dollars, default: 0 (unlimited)
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
  context: Record<string, any> & { machine?: MachineRuntimeMetadata };
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
  config_hash?: string;
  depth?: number;
}

export interface PersistenceConfig {
  enabled: boolean;
  backend: "local" | "sqlite" | "memory";
  /** Database file path for sqlite backend. Defaults to "flatmachines.sqlite". */
  db_path?: string;
  checkpoint_on?: string[];
  [key: string]: any;
}

export interface MachineReference {
  path?: string;
  inline?: MachineWrapper;
}

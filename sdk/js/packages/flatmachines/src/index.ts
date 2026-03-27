// ─────────────────────────────────────────────────────────────────────────────
// Re-export everything from @memgrafter/flatagents for convenience
// ─────────────────────────────────────────────────────────────────────────────

export * from '@memgrafter/flatagents';

// ─────────────────────────────────────────────────────────────────────────────
// Core
// ─────────────────────────────────────────────────────────────────────────────

export { FlatMachine, ExtendedMachineOptions, WaitingForSignal } from './flatmachine';

// ─────────────────────────────────────────────────────────────────────────────
// Adapters
// ─────────────────────────────────────────────────────────────────────────────

export { FlatAgentAdapter, FlatAgentExecutor } from './adapters/flatagent_adapter';
export { ClaudeCodeAdapter, ClaudeCodeExecutor, throttle_from_config } from './adapters/claude_code_adapter';
export { CodexCliAdapter, CodexCliExecutor } from './adapters/codex_cli_adapter';

// ─────────────────────────────────────────────────────────────────────────────
// Execution
// ─────────────────────────────────────────────────────────────────────────────

export {
  DefaultExecution,
  RetryExecution,
  ParallelExecution,
  MDAPVotingExecution,
  getExecutionType
} from './execution';

// ─────────────────────────────────────────────────────────────────────────────
// Hooks
// ─────────────────────────────────────────────────────────────────────────────

export {
  WebhookHooks,
  CompositeHooks,
  LoggingHooks,
  HooksRegistry
} from './hooks';

// ─────────────────────────────────────────────────────────────────────────────
// Persistence
// ─────────────────────────────────────────────────────────────────────────────

export {
  MemoryBackend,
  LocalFileBackend,
  CheckpointManager,
  cloneSnapshot,
} from './persistence';

export {
  SQLiteCheckpointBackend,
  SQLiteConfigStore,
  MemoryConfigStore,
  LocalFileConfigStore,
  configHash,
} from './persistence_sqlite';

export type { ConfigStore } from './persistence_sqlite';

// ─────────────────────────────────────────────────────────────────────────────
// Results
// ─────────────────────────────────────────────────────────────────────────────

export { inMemoryResultBackend } from './results';

// ─────────────────────────────────────────────────────────────────────────────
// Expression
// ─────────────────────────────────────────────────────────────────────────────

export { evaluate } from './expression';
export { evaluateCel } from './expression_cel';

// Decomposed machine helpers (extracted from FlatMachine for testability)
export {
  evaluateExpr,
  renderValue,
  resolveBarePath,
  resolvePath,
  renderGuardrail,
} from './machine_context';

export {
  makeResultUri,
  buildCheckpointSnapshot,
  injectMachineMetadata,
  buildAssistantMessage,
  extractCost,
  normalizeMachineResult,
  firstCompleted,
  withTimeout,
  awaitWithMode,
} from './machine_lifecycle';

// ─────────────────────────────────────────────────────────────────────────────
// Locking
// ─────────────────────────────────────────────────────────────────────────────

export { NoOpLock, LocalFileLock } from './locking';
export { SQLiteLeaseLock } from './locking_sqlite';

// ─────────────────────────────────────────────────────────────────────────────
// Signals & Triggers
// ─────────────────────────────────────────────────────────────────────────────

export {
  MemorySignalBackend,
  SQLiteSignalBackend,
  NoOpTrigger,
  FileTrigger,
  SocketTrigger,
  createSignalBackend,
  createTriggerBackend,
  sendAndNotify,
} from './signals';

export type { Signal, SignalBackend, TriggerBackend } from './signals';

// ─────────────────────────────────────────────────────────────────────────────
// Dispatcher
// ─────────────────────────────────────────────────────────────────────────────

export { SignalDispatcher } from './dispatcher';
export type { MachineResumer } from './dispatcher';

export { run_once, run_listen, _build_parser, _async_main } from './dispatch_signals';

// ─────────────────────────────────────────────────────────────────────────────
// Resume
// ─────────────────────────────────────────────────────────────────────────────

export { ConfigStoreResumer, ConfigStoreResumer as ConfigFileResumer } from './resume';
export type { ConfigStoreResumerOptions, ReferenceResolver } from './resume';

// ─────────────────────────────────────────────────────────────────────────────
// Actions & Invokers
// ─────────────────────────────────────────────────────────────────────────────

export { HookAction, InlineInvoker, SubprocessInvoker, QueueInvoker } from './actions';
export type { Action, MachineInvoker } from './actions';

/**
 * Launch a machine as a fire-and-forget subprocess.
 * Convenience wrapper around SubprocessInvoker.
 */
export async function launch_machine(
  config: Record<string, any>,
  input: Record<string, any>,
  opts?: { workingDir?: string; executionId?: string },
): Promise<void> {
  const { SubprocessInvoker: Invoker } = await import('./actions');
  const invoker = new Invoker({ workingDir: opts?.workingDir });
  const { randomUUID } = await import('node:crypto');
  await invoker.launch({}, config, input, opts?.executionId ?? randomUUID());
}

// ─────────────────────────────────────────────────────────────────────────────
// Validation
// ─────────────────────────────────────────────────────────────────────────────

export { validateFlatMachineConfig } from './validation';
// Re-export the ValidationResult type (also available from @memgrafter/flatagents)
export type { ValidationResult } from './validation';

// ─────────────────────────────────────────────────────────────────────────────
// Distributed Workers
// ─────────────────────────────────────────────────────────────────────────────

export {
  MemoryRegistrationBackend,
  SQLiteRegistrationBackend,
  createRegistrationBackend,
} from './distributed';

export type {
  WorkerRegistration,
  WorkerRecord,
  WorkerFilter,
  RegistrationBackend,
} from './distributed';

export {
  MemoryWorkPool,
  MemoryWorkBackend,
  SQLiteWorkPool,
  SQLiteWorkBackend,
  createWorkBackend,
} from './work';

export { WorkPool, WorkBackend, WorkItem } from './distributed';

export { DistributedWorkerHooks } from './distributed_hooks';

// ─────────────────────────────────────────────────────────────────────────────
// Machine Types
// ─────────────────────────────────────────────────────────────────────────────

export type {
  MachineConfig,
  State,
  MachineSnapshot,
  ExecutionConfig,
  ExecutionType,
  ExecutionLock,
  MachineHooks,
  PersistenceBackend,
  ResultBackend,
  MachineOptions,
  BackendConfig,
  HooksRef,
  HooksRefConfig,
  HooksFactory,
  LaunchIntent,
} from './types';

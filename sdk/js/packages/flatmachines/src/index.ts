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
export { ClaudeCodeAdapter, ClaudeCodeExecutor } from './adapters/claude_code_adapter';

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

export { run_once, run_listen } from './dispatch_signals';

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

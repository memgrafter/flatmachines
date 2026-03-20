// ─────────────────────────────────────────────────────────────────────────────
// Core
// ─────────────────────────────────────────────────────────────────────────────

export { FlatAgent, AgentOptions } from './flatagent';
export { FlatMachine, ExtendedMachineOptions } from './flatmachine';
export { ProfileManager, resolveModelConfig } from './profiles';

// ─────────────────────────────────────────────────────────────────────────────
// Agent Response (Phase 1.1)
// ─────────────────────────────────────────────────────────────────────────────

export {
  FinishReason,
  CostInfo as AgentCostInfo,
  UsageInfo as AgentUsageInfo,
  RateLimitInfo as AgentRateLimitInfo,
  ErrorInfo as AgentErrorInfo,
  AgentToolCall,
  AgentResponse,
  agentResponseSuccess,
  isAgentResponseSuccess,
  normalizeHeaders,
  extractRateLimitInfo,
  isRateLimited,
  getRetryDelay,
  extractStatusCode,
  isRetryableError,
} from './agent_response';

export type {
  CostInfo,
  UsageInfo,
  RateLimitInfo,
  ErrorInfo,
} from './agent_response';

// ─────────────────────────────────────────────────────────────────────────────
// Extractors (Phase 1.3)
// ─────────────────────────────────────────────────────────────────────────────

export {
  FreeExtractor,
  FreeThinkingExtractor,
  StructuredExtractor,
  ToolsExtractor,
  RegexExtractor,
} from './extractors';

export type { Extractor } from './extractors';

// ─────────────────────────────────────────────────────────────────────────────
// Tools (Phase 1.2)
// ─────────────────────────────────────────────────────────────────────────────

export {
  SimpleToolProvider,
  toolResult,
} from './tools';

export type {
  ToolResult,
  ToolProvider,
  Tool,
} from './tools';

// ─────────────────────────────────────────────────────────────────────────────
// Tool Loop (Phase 1.2)
// ─────────────────────────────────────────────────────────────────────────────

export {
  ToolLoopAgent,
  StopReason,
} from './tool_loop';

export type {
  Guardrails,
  AggregateUsage,
  ToolLoopResult,
  SteeringProvider,
  SteeringCallback,
  ToolLoopAgentLLM,
  ToolLoopAgentOptions,
} from './tool_loop';

// ─────────────────────────────────────────────────────────────────────────────
// Agent Adapter Registry (Phase 2.1)
// ─────────────────────────────────────────────────────────────────────────────

export {
  AgentAdapterRegistry,
  normalizeAgentRef,
  coerceAgentResult,
  agentResultSuccess,
  agentResultOutputPayload,
  buildRateLimitWindows,
  buildRateLimitState,
  DEFAULT_AGENT_TYPE,
} from './agents';

export type {
  AgentResult,
  AgentExecutor,
  AgentRef,
  AgentAdapter,
  AgentAdapterContext,
  AgentErrorDict,
  RateLimitState,
  RateLimitWindow,
  ProviderData,
  UsageInfoDict,
  CostInfoDict,
} from './agents';

// ─────────────────────────────────────────────────────────────────────────────
// FlatAgent Adapter (Phase 2.2)
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
// Persistence (Phase 2.4 + 3.6)
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
// MCP
// ─────────────────────────────────────────────────────────────────────────────

export { MCPToolProvider } from './mcp';

// ─────────────────────────────────────────────────────────────────────────────
// Expression
// ─────────────────────────────────────────────────────────────────────────────

export { evaluate } from './expression';
export { evaluateCel } from './expression_cel';

// ─────────────────────────────────────────────────────────────────────────────
// Templating
// ─────────────────────────────────────────────────────────────────────────────

export { setTemplateAllowlist } from './template_allowlist';

// ─────────────────────────────────────────────────────────────────────────────
// Locking (Phase 3.8)
// ─────────────────────────────────────────────────────────────────────────────

export { NoOpLock, LocalFileLock } from './locking';
export { SQLiteLeaseLock } from './locking_sqlite';

// ─────────────────────────────────────────────────────────────────────────────
// LLM
// ─────────────────────────────────────────────────────────────────────────────

export { VercelAIBackend, MockLLMBackend } from './llm';
export type { LLMBackend, LLMBackendConfig, LLMOptions, Message, ToolCall, ToolDefinition, MockResponse } from './llm';

// ─────────────────────────────────────────────────────────────────────────────
// Codex Backend (Phase 6 — providers)
// ─────────────────────────────────────────────────────────────────────────────

export {
  CodexClient,
  CodexClientError,
  CodexHTTPError,
  CodexAuthError,
  PiAuthStore,
  resolveAuthFile,
  loadCodexCredential,
  refreshCodexCredential,
  isExpired,
  decodeJwtPayload,
  extractAccountIdFromAccessToken,
} from './providers';

export type {
  CodexOAuthCredential,
  CodexUsage,
  CodexToolCall,
  CodexResult,
} from './providers';

// ─────────────────────────────────────────────────────────────────────────────
// Signals & Triggers (Phase 3.2 + 3.3)
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
// Dispatcher (Phase 3.4)
// ─────────────────────────────────────────────────────────────────────────────

export { SignalDispatcher } from './dispatcher';
export type { MachineResumer } from './dispatcher';

// ─────────────────────────────────────────────────────────────────────────────
// Resume (Phase 3.5)
// ─────────────────────────────────────────────────────────────────────────────

export { ConfigStoreResumer } from './resume';
export type { ConfigStoreResumerOptions, ReferenceResolver } from './resume';

// ─────────────────────────────────────────────────────────────────────────────
// Actions & Invokers (Phase 3.7)
// ─────────────────────────────────────────────────────────────────────────────

export { HookAction, InlineInvoker, SubprocessInvoker, QueueInvoker } from './actions';
export type { Action, MachineInvoker } from './actions';

// ─────────────────────────────────────────────────────────────────────────────
// Monitoring (Phase 4.1)
// ─────────────────────────────────────────────────────────────────────────────

export { setupLogging, getLogger, AgentMonitor, trackOperation, LogLevel } from './monitoring';
export type { Logger } from './monitoring';

// ─────────────────────────────────────────────────────────────────────────────
// Validation (Phase 4.2)
// ─────────────────────────────────────────────────────────────────────────────

export { validateFlatAgentConfig, validateFlatMachineConfig } from './validation';
export type { ValidationResult } from './validation';

// ─────────────────────────────────────────────────────────────────────────────
// Distributed Workers (Phase 5)
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

export type { WorkItem, WorkPool, WorkBackend } from './work';

export { DistributedWorkerHooks } from './distributed_hooks';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

export type {
  AgentConfig,
  MachineConfig,
  State,
  MachineSnapshot,
  MCPServer,
  ToolFilter,
  ExecutionConfig,
  ExecutionType,
  ExecutionLock,
  MachineHooks,
  PersistenceBackend,
  ResultBackend,
  MachineOptions,
  BackendConfig,
  ModelConfig,
  ModelProfileConfig,
  ProfiledModelConfig,
  ProfilesConfig,
  HooksRef,
  HooksRefConfig,
  HooksFactory,
  LaunchIntent,
} from './types';

export type { TemplateAllowlist } from './template_allowlist';

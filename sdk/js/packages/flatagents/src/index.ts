// ─────────────────────────────────────────────────────────────────────────────
// Core
// ─────────────────────────────────────────────────────────────────────────────

export { FlatAgent, AgentOptions } from './flatagent';
export { ProfileManager, resolveModelConfig } from './profiles';

// ─────────────────────────────────────────────────────────────────────────────
// Agent Response
// ─────────────────────────────────────────────────────────────────────────────

export {
  FinishReason,
  CostInfo,
  CostInfo as AgentCostInfo,
  UsageInfo,
  UsageInfo as AgentUsageInfo,
  RateLimitInfo,
  RateLimitInfo as AgentRateLimitInfo,
  ErrorInfo,
  ErrorInfo as AgentErrorInfo,
  AgentToolCall,
  ToolCall,
  AgentResponse,
  agentResponseSuccess,
  isAgentResponseSuccess,
  normalizeHeaders,
  extractRateLimitInfo,
  extractHeadersFromResponse,
  extractHeadersFromError,
  isRateLimited,
  getRetryDelay,
  extractStatusCode,
  isRetryableError,
} from './agent_response';

// ─────────────────────────────────────────────────────────────────────────────
// Extractors
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
// Tools
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
// Tool Loop
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
// Agent Adapter Registry
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
// Monitoring
// ─────────────────────────────────────────────────────────────────────────────

export { setupLogging, getLogger, AgentMonitor, trackOperation, LogLevel } from './monitoring';
export type { Logger } from './monitoring';

// ─────────────────────────────────────────────────────────────────────────────
// Provider-specific rate limits
// ─────────────────────────────────────────────────────────────────────────────

export {
  CerebrasRateLimits,
  extract_cerebras_rate_limits,
  AnthropicRateLimits,
  extract_anthropic_rate_limits,
  OpenAIRateLimits,
  extract_openai_rate_limits,
  parseDurationToSeconds,
} from './monitoring_providers';

// ─────────────────────────────────────────────────────────────────────────────
// Snake-case aliases for Python parity
// ─────────────────────────────────────────────────────────────────────────────

export {
  extractHeadersFromResponse as extract_headers_from_response,
  extractHeadersFromError as extract_headers_from_error,
} from './agent_response';

// ─────────────────────────────────────────────────────────────────────────────
// Validation
// ─────────────────────────────────────────────────────────────────────────────

export { validateFlatAgentConfig } from './validation';
export type { ValidationResult } from './validation';

// ─────────────────────────────────────────────────────────────────────────────
// Templating
// ─────────────────────────────────────────────────────────────────────────────

export { renderTemplate } from './templating';
export { setTemplateAllowlist } from './template_allowlist';
export type { TemplateAllowlist } from './template_allowlist';

// ─────────────────────────────────────────────────────────────────────────────
// LLM
// ─────────────────────────────────────────────────────────────────────────────

export { VercelAIBackend, MockLLMBackend } from './llm';
export type { LLMBackend, LLMBackendConfig, LLMOptions, Message, ToolCall as LLMToolCall, ToolDefinition, MockResponse } from './llm';

// ─────────────────────────────────────────────────────────────────────────────
// MCP
// ─────────────────────────────────────────────────────────────────────────────

export { MCPToolProvider } from './mcp';

// ─────────────────────────────────────────────────────────────────────────────
// Codex Backend (providers)
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
  refreshOpenaiCodexToken,
  TOKEN_URL,
  OPENAI_CODEX_CLIENT_ID,
} from './providers';

export type {
  CodexOAuthCredential,
  CodexUsage,
  CodexToolCall as CodexToolCallType,
  CodexResult,
} from './providers';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

export type {
  AgentConfig,
  ModelConfig,
  ModelProfileConfig,
  ProfiledModelConfig,
  ProfilesConfig,
  MCPServer,
  ToolFilter,
} from './types';

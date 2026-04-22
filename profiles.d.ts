/**
 * FlatAgent Profiles Schema
 * ========================
 *
 * Profiles hold reusable execution configuration so FlatAgents can stay
 * focused on prompts.
 *
 * A profile fully determines how an agent is executed:
 * - which runtime is used
 * - which model is used (for the built-in `llm` runtime or runtimes that need a model name)
 * - which operational/runtime settings are applied
 *
 * FlatAgent files should usually specify only `data.profile` plus prompts.
 *
 * This file is the source of truth for profile schemas.
 * Generated schema assets are derived from this file.
 */

export const SPEC_VERSION = "4.0.0";

export interface ProfilesWrapper {
  spec: "flatprofiles";
  spec_version: string;
  data: ProfilesData;
  metadata?: Record<string, any>;
}

export interface ProfilesData {
  /** Unified execution profile namespace. */
  profiles: Record<string, ExecutionProfileConfig>;
  /** Fallback profile when an agent omits `data.profile`. */
  default?: string;
  /** Global override profile applied ahead of any agent-selected profile. */
  override?: string;
}

export interface OAuthConfig {
  provider?: "openai-codex" | string;
  auth_file?: string;
  refresh?: boolean;
  originator?: string;
  timeout_seconds?: number;
  max_retries?: number;
  token_url?: string;
  client_id?: string;
}

/**
 * Shared model vocabulary for profiles that resolve through the built-in `llm`
 * runtime.
 */
export interface ModelProfileConfig {
  name: string;
  provider?: string;
  temperature?: number;
  max_tokens?: number;
  top_p?: number;
  top_k?: number;
  frequency_penalty?: number;
  presence_penalty?: number;
  seed?: number;
  base_url?: string;
  stream?: boolean;
  backend?: "litellm" | "aisuite" | "codex" | "copilot";
  api?: string;
  oauth?: OAuthConfig;
}

/**
 * Unified execution profile space.
 */
export type ExecutionProfileConfig =
  | LLMExecutionProfileConfig
  | ClaudeCodeExecutionProfileConfig
  | CodexCliExecutionProfileConfig
  | SmolagentsExecutionProfileConfig
  | PiAgentExecutionProfileConfig;

/**
 * Built-in FlatAgent LLM runtime profile.
 */
export interface LLMExecutionProfileConfig {
  type: "llm";
  model: ModelProfileConfig;
}

/**
 * Claude Code CLI runtime profile.
 */
export interface ClaudeCodeExecutionProfileConfig {
  type: "claude-code";
  model?: string;
  effort?: "low" | "medium" | "high" | "max";
  permission_mode?: "default" | "acceptEdits" | "bypassPermissions" | "dontAsk" | "plan" | "auto";
  dangerously_skip_permissions?: boolean;
  tools?: string[];
  max_budget_usd?: number;
  add_dirs?: string[];
  claude_bin?: string;
  working_dir?: string;
  timeout?: number;
  max_continuations?: number;
  exit_sentinel?: string;
  continuation_prompt?: string;
  mcp_config?: string;
  rate_limit_delay?: number;
  rate_limit_jitter?: number;
}

/**
 * Codex CLI runtime profile.
 */
export interface CodexCliExecutionProfileConfig {
  type: "codex-cli";
  model?: string;
  reasoning_effort?: "none" | "minimal" | "low" | "medium" | "high" | "xhigh";
  sandbox?: "read-only" | "workspace-write" | "danger-full-access";
  approval_policy?: "untrusted" | "on-request" | "never";
  dangerously_bypass_approvals_and_sandbox?: boolean;
  add_dirs?: string[];
  codex_bin?: string;
  working_dir?: string;
  timeout?: number;
  skip_git_repo_check?: boolean;
  ephemeral?: boolean;
  search?: boolean;
  config_overrides?: Record<string, string | number | boolean>;
  feature_enable?: string[];
  feature_disable?: string[];
  rate_limit_delay?: number;
  rate_limit_jitter?: number;
  use_app_server?: boolean;
  session_source?: string;
}

/**
 * smolagents runtime profile.
 */
export interface SmolagentsExecutionProfileConfig {
  type: "smolagents";
  ref: string;
  config?: Record<string, any>;
}

/**
 * pi-agent bridge runtime profile.
 */
export interface PiAgentExecutionProfileConfig {
  type: "pi-agent";
  ref: string;
  runner?: string;
  node?: string;
  cwd?: string;
  env?: Record<string, string>;
  timeout?: number;
  agent_config?: Record<string, any>;
}

export type FlatprofilesConfig = ProfilesWrapper;

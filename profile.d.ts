/**
 * Profile Configuration Schema
 * ============================
 *
 * Profile is the pure execution contract for prompt execution.
 *
 * It defines:
 * - which runtime executes the prompt
 * - which model is used when applicable
 * - runtime-specific operational settings
 * - execution semantics such as session / continuation behavior when supported
 *
 * It does not define prompt text or output schema.
 */

export const SPEC_VERSION = "4.0.0";

export interface ProfileWrapper {
  spec: "flatprofile";
  spec_version: string;
  data: ProfileData;
  metadata?: Record<string, any>;
}

/**
 * Profile inline-or-ref value.
 * - string: path/ref to a profile file
 * - object: inline profile config
 */
export type ProfileRef = string | ProfileData | ProfileWrapper;

export type ProfileData =
  | LLMProfile
  | ClaudeCodeProfile
  | CodexCliProfile
  | SmolagentsProfile
  | PiAgentProfile;

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

export interface ModelConfig {
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

/** Built-in API/LLM execution profile. */
export interface LLMProfile {
  type: "llm";
  model: ModelConfig;
}

/** Claude Code CLI execution profile. */
export interface ClaudeCodeProfile {
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

/** Codex CLI execution profile. */
export interface CodexCliProfile {
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

/** smolagents execution profile. */
export interface SmolagentsProfile {
  type: "smolagents";
  ref: string;
  config?: Record<string, any>;
}

/** pi-agent bridge execution profile. */
export interface PiAgentProfile {
  type: "pi-agent";
  ref: string;
  runner?: string;
  node?: string;
  cwd?: string;
  env?: Record<string, string>;
  timeout?: number;
  agent_config?: Record<string, any>;
}

export type FlatprofileConfig = ProfileWrapper;

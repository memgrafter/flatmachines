/**
 * Structured agent response types — Phase 1.1
 *
 * Ports Python SDK's AgentResponse, UsageInfo, CostInfo, RateLimitInfo,
 * ErrorInfo, FinishReason, and ToolCall from baseagent.py.
 */

// ─────────────────────────────────────────────────────────────────────────────
// Enums
// ─────────────────────────────────────────────────────────────────────────────

export enum FinishReason {
  STOP = 'stop',
  LENGTH = 'length',
  TOOL_USE = 'tool_use',
  ERROR = 'error',
  ABORTED = 'aborted',
  CONTENT_FILTER = 'content_filter',
}

// ─────────────────────────────────────────────────────────────────────────────
// Data types
// ─────────────────────────────────────────────────────────────────────────────

export interface CostInfo {
  input: number;
  output: number;
  cache_read: number;
  cache_write: number;
  total: number;
}

export interface UsageInfo {
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  cache_read_tokens: number;
  cache_write_tokens: number;
  cost?: CostInfo;
}

export interface RateLimitInfo {
  remaining_requests?: number;
  remaining_tokens?: number;
  limit_requests?: number;
  limit_tokens?: number;
  reset_at?: number;
  retry_after?: number;
  raw_headers: Record<string, string>;
}

export interface ErrorInfo {
  error_type: string;
  message: string;
  status_code?: number;
  retryable: boolean;
}

export interface AgentToolCall {
  id: string;
  server: string;
  tool: string;
  arguments: Record<string, any>;
}

// ─────────────────────────────────────────────────────────────────────────────
// AgentResponse
// ─────────────────────────────────────────────────────────────────────────────

export interface AgentResponse {
  content?: string;
  output?: Record<string, any>;
  tool_calls?: AgentToolCall[];
  raw_response?: any;
  usage?: UsageInfo;
  rate_limit?: RateLimitInfo;
  finish_reason?: FinishReason;
  error?: ErrorInfo;
  rendered_user_prompt?: string;
}

export function agentResponseSuccess(fields: Omit<AgentResponse, 'error'>): AgentResponse {
  return { ...fields };
}

export function isAgentResponseSuccess(r: AgentResponse): boolean {
  return r.error == null;
}

// ─────────────────────────────────────────────────────────────────────────────
// Header extraction utilities
// ─────────────────────────────────────────────────────────────────────────────

export function normalizeHeaders(raw: any): Record<string, string> {
  if (raw == null) return {};
  const result: Record<string, string> = {};
  if (typeof raw === 'object' && !Array.isArray(raw)) {
    for (const [k, v] of Object.entries(raw)) {
      if (k == null) continue;
      const key = String(k).toLowerCase();
      if (Array.isArray(v)) {
        result[key] = v.map(String).join(',');
      } else {
        result[key] = String(v);
      }
    }
  }
  return result;
}

function parseIntHeader(headers: Record<string, string>, ...keys: string[]): number | undefined {
  for (const key of keys) {
    const val = headers[key] ?? headers[key.toLowerCase()];
    if (val != null) {
      const n = parseInt(val, 10);
      if (!isNaN(n)) return n;
    }
  }
  return undefined;
}

function parseResetTimestamp(headers: Record<string, string>, ...keys: string[]): number | undefined {
  for (const key of keys) {
    const val = headers[key] ?? headers[key.toLowerCase()];
    if (val == null) continue;
    const trimmed = val.trim();

    // Try numeric (unix timestamp or relative seconds)
    const numStr = trimmed.replace(/s$/, '');
    const num = parseFloat(numStr);
    if (!isNaN(num)) {
      // Unix timestamp (after year 2000)
      if (num > 946684800) {
        return num > 946684800000 ? num / 1000 : num;
      }
      // Relative seconds
      return Date.now() / 1000 + num;
    }

    // Try ISO 8601
    const d = new Date(trimmed);
    if (!isNaN(d.getTime())) {
      return d.getTime() / 1000;
    }
  }
  return undefined;
}

export function extractRateLimitInfo(headers: Record<string, string>): RateLimitInfo {
  const remaining_requests = parseIntHeader(
    headers,
    'x-ratelimit-remaining-requests',
    'ratelimit-remaining',
    'anthropic-ratelimit-requests-remaining',
  );
  const remaining_tokens = parseIntHeader(
    headers,
    'x-ratelimit-remaining-tokens',
    'anthropic-ratelimit-tokens-remaining',
  );
  const limit_requests = parseIntHeader(
    headers,
    'x-ratelimit-limit-requests',
    'ratelimit-limit',
    'anthropic-ratelimit-requests-limit',
  );
  const limit_tokens = parseIntHeader(
    headers,
    'x-ratelimit-limit-tokens',
    'anthropic-ratelimit-tokens-limit',
  );
  const reset_at = parseResetTimestamp(
    headers,
    'x-ratelimit-reset-requests',
    'x-ratelimit-reset-tokens',
    'x-ratelimit-reset',
    'anthropic-ratelimit-requests-reset',
    'anthropic-ratelimit-tokens-reset',
  );
  const retry_after = parseIntHeader(headers, 'retry-after');

  return {
    remaining_requests,
    remaining_tokens,
    limit_requests,
    limit_tokens,
    reset_at,
    retry_after,
    raw_headers: headers,
  };
}

export function isRateLimited(info: RateLimitInfo): boolean {
  return info.remaining_requests === 0 || info.remaining_tokens === 0;
}

export function getRetryDelay(info: RateLimitInfo): number | undefined {
  if (info.retry_after != null) return info.retry_after;
  if (info.reset_at != null) {
    return Math.max(0, Math.round(info.reset_at - Date.now() / 1000));
  }
  return undefined;
}

// ─────────────────────────────────────────────────────────────────────────────
// Error classification utilities
// ─────────────────────────────────────────────────────────────────────────────

export function extractStatusCode(error: any): number | undefined {
  for (const attr of ['status_code', 'status', 'http_status', 'statusCode']) {
    const code = error?.[attr];
    if (code != null) {
      const n = parseInt(String(code), 10);
      if (!isNaN(n)) return n;
    }
  }
  const response = error?.response;
  if (response != null) {
    for (const attr of ['status_code', 'status', 'http_status', 'statusCode']) {
      const code = response[attr];
      if (code != null) {
        const n = parseInt(String(code), 10);
        if (!isNaN(n)) return n;
      }
    }
  }
  const match = String(error?.message ?? error ?? '').match(/\b([4-5]\d{2})\b/);
  if (match) return parseInt(match[1]!, 10);
  return undefined;
}

export function isRetryableError(error: any, statusCode?: number): boolean {
  if (statusCode === 429) return true;
  if (statusCode != null && statusCode >= 500 && statusCode < 600) return true;
  const typeName = error?.constructor?.name ?? error?.name ?? '';
  if (/RateLimit|Timeout/i.test(typeName)) return true;
  const msg = String(error?.message ?? error ?? '').toLowerCase();
  return ['rate limit', 'too many requests', 'timeout', 'temporarily'].some(s => msg.includes(s));
}

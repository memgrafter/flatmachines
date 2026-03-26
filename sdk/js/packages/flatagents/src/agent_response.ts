/**
 * Structured agent response types.
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
// Data classes
// ─────────────────────────────────────────────────────────────────────────────

export class CostInfo {
  input: number;
  output: number;
  cache_read: number;
  cache_write: number;
  total: number;

  constructor(opts?: Partial<CostInfo>) {
    this.input = opts?.input ?? 0;
    this.output = opts?.output ?? 0;
    this.cache_read = opts?.cache_read ?? 0;
    this.cache_write = opts?.cache_write ?? 0;
    this.total = opts?.total ?? 0;
  }

  toJSON() {
    return {
      input: this.input,
      output: this.output,
      cache_read: this.cache_read,
      cache_write: this.cache_write,
      total: this.total,
    };
  }
}

export class UsageInfo {
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  cache_read_tokens: number;
  cache_write_tokens: number;
  cost: CostInfo | null;

  constructor(opts?: Partial<Omit<UsageInfo, 'estimated_cost'>>) {
    this.input_tokens = opts?.input_tokens ?? 0;
    this.output_tokens = opts?.output_tokens ?? 0;
    this.total_tokens = opts?.total_tokens ?? 0;
    this.cache_read_tokens = opts?.cache_read_tokens ?? 0;
    this.cache_write_tokens = opts?.cache_write_tokens ?? 0;
    this.cost = opts?.cost ?? null;
  }

  get estimated_cost(): number {
    return this.cost?.total ?? 0;
  }

  toJSON() {
    return {
      input_tokens: this.input_tokens,
      output_tokens: this.output_tokens,
      total_tokens: this.total_tokens,
      cache_read_tokens: this.cache_read_tokens,
      cache_write_tokens: this.cache_write_tokens,
      cost: this.cost,
    };
  }
}

export class RateLimitInfo {
  remaining_requests: number | null;
  remaining_tokens: number | null;
  limit_requests: number | null;
  limit_tokens: number | null;
  reset_at: number | null;
  retry_after: number | null;
  raw_headers: Record<string, string>;

  constructor(opts?: Partial<RateLimitInfo>) {
    this.remaining_requests = opts?.remaining_requests ?? null;
    this.remaining_tokens = opts?.remaining_tokens ?? null;
    this.limit_requests = opts?.limit_requests ?? null;
    this.limit_tokens = opts?.limit_tokens ?? null;
    this.reset_at = opts?.reset_at ?? null;
    this.retry_after = opts?.retry_after ?? null;
    this.raw_headers = opts?.raw_headers ?? {};
  }

  is_limited(): boolean {
    return this.remaining_requests === 0 || this.remaining_tokens === 0;
  }

  get_retry_delay(): number | null {
    if (this.retry_after != null) return this.retry_after;
    if (this.reset_at != null) {
      return Math.max(0, Math.round(this.reset_at - Date.now() / 1000));
    }
    return null;
  }

  toJSON() {
    return {
      remaining_requests: this.remaining_requests,
      remaining_tokens: this.remaining_tokens,
      limit_requests: this.limit_requests,
      limit_tokens: this.limit_tokens,
      reset_at: this.reset_at,
      retry_after: this.retry_after,
      raw_headers: this.raw_headers,
    };
  }
}

export class ErrorInfo {
  error_type: string;
  message: string;
  status_code: number | null;
  retryable: boolean;

  constructor(opts: { error_type: string; message: string; status_code?: number | null; retryable?: boolean }) {
    this.error_type = opts.error_type;
    this.message = opts.message;
    this.status_code = opts.status_code ?? null;
    this.retryable = opts.retryable ?? false;
  }

  toJSON() {
    return {
      error_type: this.error_type,
      message: this.message,
      status_code: this.status_code,
      retryable: this.retryable,
    };
  }
}

export class AgentToolCall {
  id: string;
  server: string;
  tool: string;
  arguments: Record<string, any>;

  constructor(opts?: Partial<AgentToolCall>) {
    this.id = opts?.id ?? '';
    this.server = opts?.server ?? '';
    this.tool = opts?.tool ?? '';
    this.arguments = opts?.arguments ?? {};
  }

  toJSON() {
    return {
      id: this.id,
      server: this.server,
      tool: this.tool,
      arguments: this.arguments,
    };
  }
}

// Alias for tests that import as ToolCall
export { AgentToolCall as ToolCall };

// ─────────────────────────────────────────────────────────────────────────────
// AgentResponse
// ─────────────────────────────────────────────────────────────────────────────

export class AgentResponse {
  content: string | null;
  output: Record<string, any> | null;
  tool_calls: AgentToolCall[] | null;
  raw_response: any | null;
  usage: UsageInfo | null;
  rate_limit: RateLimitInfo | null;
  finish_reason: FinishReason | null;
  error: ErrorInfo | null;
  rendered_user_prompt?: string;

  constructor(opts?: Partial<{
    content: string | null;
    output: Record<string, any> | null;
    tool_calls: AgentToolCall[] | null;
    raw_response: any | null;
    usage: UsageInfo | null;
    rate_limit: RateLimitInfo | null;
    finish_reason: FinishReason | null;
    error: ErrorInfo | null;
    rendered_user_prompt: string;
  }>) {
    this.content = opts?.content ?? null;
    this.output = opts?.output ?? null;
    this.tool_calls = opts?.tool_calls ?? null;
    this.raw_response = opts?.raw_response ?? null;
    this.usage = opts?.usage ?? null;
    this.rate_limit = opts?.rate_limit ?? null;
    this.finish_reason = opts?.finish_reason ?? null;
    this.error = opts?.error ?? null;
    if (opts?.rendered_user_prompt !== undefined) {
      this.rendered_user_prompt = opts.rendered_user_prompt;
    }
  }

  get success(): boolean {
    return this.error == null;
  }

  toJSON() {
    return {
      content: this.content,
      output: this.output,
      tool_calls: this.tool_calls,
      raw_response: this.raw_response,
      usage: this.usage,
      rate_limit: this.rate_limit,
      finish_reason: this.finish_reason,
      error: this.error,
      rendered_user_prompt: this.rendered_user_prompt,
    };
  }
}

export function agentResponseSuccess(fields: Partial<AgentResponse>): AgentResponse {
  return new AgentResponse(fields);
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

  // Handle iterable-of-pairs (tuple input, Map, etc.)
  if (Array.isArray(raw)) {
    for (const item of raw) {
      if (Array.isArray(item) && item.length >= 2) {
        const key = String(item[0]).toLowerCase();
        result[key] = String(item[1]);
      }
    }
    return result;
  }

  // Handle httpx-style objects with items() method
  if (typeof raw === 'object' && typeof raw.items === 'function') {
    const items = raw.items();
    if (Array.isArray(items)) {
      for (const [k, v] of items) {
        result[String(k).toLowerCase()] = String(v);
      }
    }
    return result;
  }

  if (typeof raw === 'object' && !Array.isArray(raw)) {
    for (const [k, v] of Object.entries(raw)) {
      if (k == null || k === 'null') continue;
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
    if (val != null && val !== '') {
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

/**
 * Extract rate limit info from headers.
 * Returns a plain object (not a RateLimitInfo class) where missing fields are undefined.
 * This matches the Python behavior where extractRateLimitInfo returns a dict-like object.
 */
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

  return new RateLimitInfo({
    remaining_requests: remaining_requests ?? null,
    remaining_tokens: remaining_tokens ?? null,
    limit_requests: limit_requests ?? null,
    limit_tokens: limit_tokens ?? null,
    reset_at: reset_at ?? null,
    retry_after: retry_after ?? null,
    raw_headers: headers,
  });
}

export function isRateLimited(info: RateLimitInfo): boolean {
  return info.remaining_requests === 0 || info.remaining_tokens === 0;
}

export function getRetryDelay(info: RateLimitInfo): number | null {
  if (info.retry_after != null) return info.retry_after;
  if (info.reset_at != null) {
    return Math.max(0, Math.round(info.reset_at - Date.now() / 1000));
  }
  return null;
}

// ─────────────────────────────────────────────────────────────────────────────
// Response/Error header extraction utilities
// ─────────────────────────────────────────────────────────────────────────────

export function extractHeadersFromResponse(rawResponse: any): Record<string, string> {
  if (!rawResponse) return {};
  const result: Record<string, string> = {};
  // litellm response headers
  if (rawResponse._response_headers) {
    Object.assign(result, normalizeHeaders(rawResponse._response_headers));
  }
  // headers attr directly
  if (rawResponse.headers) {
    Object.assign(result, normalizeHeaders(rawResponse.headers));
  }
  // litellm hidden params
  if (rawResponse._hidden_params?.additional_headers) {
    Object.assign(result, normalizeHeaders(rawResponse._hidden_params.additional_headers));
  }
  return result;
}

export function extractHeadersFromError(error: any): Record<string, string> {
  if (!error) return {};
  const result: Record<string, string> = {};
  // Direct headers on error
  if (error.headers) {
    Object.assign(result, normalizeHeaders(error.headers));
  }
  // Response object on error
  if (error.response) {
    if (error.response.headers) {
      Object.assign(result, normalizeHeaders(error.response.headers));
    }
    // dict-style response
    if (typeof error.response === 'object' && !error.response.headers) {
      for (const [k, v] of Object.entries(error.response)) {
        if (typeof k === 'string' && k.toLowerCase().includes('ratelimit')) {
          result[k.toLowerCase()] = String(v);
        }
      }
    }
  }
  return result;
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
/**
 * Provider-specific rate limit classes.
 */

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────

function parseIntOrNull(headers: Record<string, string>, key: string): number | null {
  const v = headers[key];
  if (v == null || v === '') return null;
  const n = parseInt(v, 10);
  return isNaN(n) ? null : n;
}

/**
 * Parse OpenAI-style duration strings like "6m30s", "1h", "500ms", "45s"
 * Returns seconds (integer, >= 1 for sub-second).
 */
export function parseDurationToSeconds(dur: string): number | null {
  if (!dur) return null;
  let total = 0;
  let matched = false;

  const hMatch = dur.match(/(\d+)h/);
  if (hMatch) { total += parseInt(hMatch[1]!, 10) * 3600; matched = true; }

  const mMatch = dur.match(/(\d+)m(?!s)/);
  if (mMatch) { total += parseInt(mMatch[1]!, 10) * 60; matched = true; }

  const sMatch = dur.match(/(\d+)s/);
  if (sMatch) { total += parseInt(sMatch[1]!, 10); matched = true; }

  const msMatch = dur.match(/(\d+)ms/);
  if (msMatch) { total += Math.max(1, Math.ceil(parseInt(msMatch[1]!, 10) / 1000)); matched = true; }

  return matched ? total : null;
}

// ─────────────────────────────────────────────────────────────────────────────
// Cerebras
// ─────────────────────────────────────────────────────────────────────────────

export class CerebrasRateLimits {
  remaining_requests_minute: number | null;
  remaining_requests_hour: number | null;
  remaining_requests_day: number | null;
  remaining_tokens_minute: number | null;
  remaining_tokens_hour: number | null;
  remaining_tokens_day: number | null;
  limit_requests_minute: number | null;
  limit_requests_hour: number | null;
  limit_requests_day: number | null;
  limit_tokens_minute: number | null;
  limit_tokens_hour: number | null;
  limit_tokens_day: number | null;

  constructor(opts?: Partial<CerebrasRateLimits>) {
    this.remaining_requests_minute = opts?.remaining_requests_minute ?? null;
    this.remaining_requests_hour = opts?.remaining_requests_hour ?? null;
    this.remaining_requests_day = opts?.remaining_requests_day ?? null;
    this.remaining_tokens_minute = opts?.remaining_tokens_minute ?? null;
    this.remaining_tokens_hour = opts?.remaining_tokens_hour ?? null;
    this.remaining_tokens_day = opts?.remaining_tokens_day ?? null;
    this.limit_requests_minute = opts?.limit_requests_minute ?? null;
    this.limit_requests_hour = opts?.limit_requests_hour ?? null;
    this.limit_requests_day = opts?.limit_requests_day ?? null;
    this.limit_tokens_minute = opts?.limit_tokens_minute ?? null;
    this.limit_tokens_hour = opts?.limit_tokens_hour ?? null;
    this.limit_tokens_day = opts?.limit_tokens_day ?? null;
  }

  is_limited(): boolean {
    const fields = [
      this.remaining_requests_minute,
      this.remaining_requests_hour,
      this.remaining_requests_day,
      this.remaining_tokens_minute,
      this.remaining_tokens_hour,
      this.remaining_tokens_day,
    ];
    return fields.some(f => f === 0);
  }

  get_most_restrictive_bucket(): 'minute' | 'hour' | 'day' | null {
    const buckets: Array<['minute' | 'hour' | 'day', (number | null)[]]> = [
      ['minute', [this.remaining_requests_minute, this.remaining_tokens_minute]],
      ['hour', [this.remaining_requests_hour, this.remaining_tokens_hour]],
      ['day', [this.remaining_requests_day, this.remaining_tokens_day]],
    ];
    for (const [name, values] of buckets) {
      if (values.some(v => v === 0)) return name;
    }
    return null;
  }

  get_suggested_wait_seconds(): number | null {
    const bucket = this.get_most_restrictive_bucket();
    if (!bucket) return null;
    const waits = { minute: 60, hour: 3600, day: 86400 };
    return waits[bucket];
  }
}

export function extract_cerebras_rate_limits(headers: Record<string, string>): CerebrasRateLimits {
  return new CerebrasRateLimits({
    remaining_requests_minute: parseIntOrNull(headers, 'x-ratelimit-remaining-requests-minute'),
    remaining_requests_hour: parseIntOrNull(headers, 'x-ratelimit-remaining-requests-hour'),
    remaining_requests_day: parseIntOrNull(headers, 'x-ratelimit-remaining-requests-day'),
    remaining_tokens_minute: parseIntOrNull(headers, 'x-ratelimit-remaining-tokens-minute'),
    remaining_tokens_hour: parseIntOrNull(headers, 'x-ratelimit-remaining-tokens-hour'),
    remaining_tokens_day: parseIntOrNull(headers, 'x-ratelimit-remaining-tokens-day'),
    limit_requests_minute: parseIntOrNull(headers, 'x-ratelimit-limit-requests-minute'),
    limit_requests_hour: parseIntOrNull(headers, 'x-ratelimit-limit-requests-hour'),
    limit_requests_day: parseIntOrNull(headers, 'x-ratelimit-limit-requests-day'),
    limit_tokens_minute: parseIntOrNull(headers, 'x-ratelimit-limit-tokens-minute'),
    limit_tokens_hour: parseIntOrNull(headers, 'x-ratelimit-limit-tokens-hour'),
    limit_tokens_day: parseIntOrNull(headers, 'x-ratelimit-limit-tokens-day'),
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// Anthropic
// ─────────────────────────────────────────────────────────────────────────────

export class AnthropicRateLimits {
  requests_remaining: number | null;
  requests_limit: number | null;
  requests_reset: Date | null;
  tokens_remaining: number | null;
  tokens_limit: number | null;
  tokens_reset: Date | null;
  input_tokens_remaining: number | null;
  input_tokens_limit: number | null;
  output_tokens_remaining: number | null;
  output_tokens_limit: number | null;

  constructor(opts?: Partial<AnthropicRateLimits>) {
    this.requests_remaining = opts?.requests_remaining ?? null;
    this.requests_limit = opts?.requests_limit ?? null;
    this.requests_reset = opts?.requests_reset ?? null;
    this.tokens_remaining = opts?.tokens_remaining ?? null;
    this.tokens_limit = opts?.tokens_limit ?? null;
    this.tokens_reset = opts?.tokens_reset ?? null;
    this.input_tokens_remaining = opts?.input_tokens_remaining ?? null;
    this.input_tokens_limit = opts?.input_tokens_limit ?? null;
    this.output_tokens_remaining = opts?.output_tokens_remaining ?? null;
    this.output_tokens_limit = opts?.output_tokens_limit ?? null;
  }

  is_limited(): boolean {
    return [
      this.requests_remaining,
      this.tokens_remaining,
      this.input_tokens_remaining,
      this.output_tokens_remaining,
    ].some(f => f === 0);
  }

  get_next_reset(): Date | null {
    const resets = [this.requests_reset, this.tokens_reset].filter(Boolean) as Date[];
    if (resets.length === 0) return null;
    return resets.reduce((a, b) => a < b ? a : b);
  }
}

function parseTimestamp(val: string | undefined): Date | null {
  if (!val) return null;
  const d = new Date(val);
  return isNaN(d.getTime()) ? null : d;
}

export function extract_anthropic_rate_limits(headers: Record<string, string>): AnthropicRateLimits {
  return new AnthropicRateLimits({
    requests_remaining: parseIntOrNull(headers, 'anthropic-ratelimit-requests-remaining'),
    requests_limit: parseIntOrNull(headers, 'anthropic-ratelimit-requests-limit'),
    requests_reset: parseTimestamp(headers['anthropic-ratelimit-requests-reset']),
    tokens_remaining: parseIntOrNull(headers, 'anthropic-ratelimit-tokens-remaining'),
    tokens_limit: parseIntOrNull(headers, 'anthropic-ratelimit-tokens-limit'),
    tokens_reset: parseTimestamp(headers['anthropic-ratelimit-tokens-reset']),
    input_tokens_remaining: parseIntOrNull(headers, 'anthropic-ratelimit-input-tokens-remaining'),
    input_tokens_limit: parseIntOrNull(headers, 'anthropic-ratelimit-input-tokens-limit'),
    output_tokens_remaining: parseIntOrNull(headers, 'anthropic-ratelimit-output-tokens-remaining'),
    output_tokens_limit: parseIntOrNull(headers, 'anthropic-ratelimit-output-tokens-limit'),
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// OpenAI
// ─────────────────────────────────────────────────────────────────────────────

export class OpenAIRateLimits {
  remaining_requests: number | null;
  remaining_tokens: number | null;
  limit_requests: number | null;
  limit_tokens: number | null;
  reset_requests: string | null;
  reset_tokens: string | null;
  reset_requests_seconds: number | null;
  reset_tokens_seconds: number | null;

  constructor(opts?: Partial<OpenAIRateLimits>) {
    this.remaining_requests = opts?.remaining_requests ?? null;
    this.remaining_tokens = opts?.remaining_tokens ?? null;
    this.limit_requests = opts?.limit_requests ?? null;
    this.limit_tokens = opts?.limit_tokens ?? null;
    this.reset_requests = opts?.reset_requests ?? null;
    this.reset_tokens = opts?.reset_tokens ?? null;
    this.reset_requests_seconds = opts?.reset_requests_seconds ?? null;
    this.reset_tokens_seconds = opts?.reset_tokens_seconds ?? null;
  }

  is_limited(): boolean {
    return this.remaining_requests === 0 || this.remaining_tokens === 0;
  }

  get_seconds_until_reset(): number | null {
    const vals = [this.reset_requests_seconds, this.reset_tokens_seconds].filter(v => v != null) as number[];
    return vals.length > 0 ? Math.min(...vals) : null;
  }
}

export function extract_openai_rate_limits(headers: Record<string, string>): OpenAIRateLimits {
  const reset_requests_raw = headers['x-ratelimit-reset-requests'] ?? null;
  const reset_tokens_raw = headers['x-ratelimit-reset-tokens'] ?? null;

  return new OpenAIRateLimits({
    remaining_requests: parseIntOrNull(headers, 'x-ratelimit-remaining-requests'),
    remaining_tokens: parseIntOrNull(headers, 'x-ratelimit-remaining-tokens'),
    limit_requests: parseIntOrNull(headers, 'x-ratelimit-limit-requests'),
    limit_tokens: parseIntOrNull(headers, 'x-ratelimit-limit-tokens'),
    reset_requests: reset_requests_raw,
    reset_tokens: reset_tokens_raw,
    reset_requests_seconds: reset_requests_raw ? parseDurationToSeconds(reset_requests_raw) : null,
    reset_tokens_seconds: reset_tokens_raw ? parseDurationToSeconds(reset_tokens_raw) : null,
  });
}
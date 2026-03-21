/**
 * Agent executor interfaces and adapter registry.
 *
 * Ports Python SDK's agents.py (AgentExecutor, AgentResult, AgentRef,
 * AgentAdapterRegistry, normalize_agent_ref, coerce_agent_result,
 * build_rate_limit_windows, build_rate_limit_state).
 */

// Built-in adapter factories (set by adapter modules on import)
const _builtinFactories: Array<() => AgentAdapter> = [];

// ─────────────────────────────────────────────────────────────────────────────
// Agent Result Types (see flatagents-runtime.d.ts for canonical spec)
// ─────────────────────────────────────────────────────────────────────────────

export type UsageInfoDict = Record<string, any>;
export type CostInfoDict = Record<string, number>;
export type AgentErrorDict = Record<string, any>;
export type RateLimitWindow = Record<string, any>;
export type RateLimitState = Record<string, any>;
export type ProviderData = Record<string, any>;

export interface AgentResult {
  output?: Record<string, any> | null;
  content?: string | null;
  raw?: any;
  usage?: UsageInfoDict | null;
  cost?: CostInfoDict | number | null;
  metadata?: Record<string, any> | null;
  finish_reason?: string | null;
  error?: AgentErrorDict | null;
  rate_limit?: RateLimitState | null;
  provider_data?: ProviderData | null;
  tool_calls?: Array<Record<string, any>> | null;
  rendered_user_prompt?: string | null;
}

export function agentResultSuccess(r: AgentResult): boolean {
  return r.error == null;
}

export function agentResultOutputPayload(r: AgentResult): Record<string, any> {
  if (r.output != null) return r.output;
  if (r.content != null) return { content: r.content };
  return {};
}

// ─────────────────────────────────────────────────────────────────────────────
// AgentExecutor protocol
// ─────────────────────────────────────────────────────────────────────────────

export interface AgentExecutor {
  execute(
    inputData: Record<string, any>,
    context?: Record<string, any>,
  ): Promise<AgentResult>;

  execute_with_tools?(
    inputData: Record<string, any>,
    tools: Array<Record<string, any>>,
    messages?: Array<Record<string, any>> | null,
    context?: Record<string, any>,
  ): Promise<AgentResult>;

  readonly metadata?: Record<string, any>;
}

// ─────────────────────────────────────────────────────────────────────────────
// AgentRef
// ─────────────────────────────────────────────────────────────────────────────

export interface AgentRef {
  type: string;
  ref?: string;
  config?: Record<string, any>;
}

export const DEFAULT_AGENT_TYPE = 'flatagent';

export function normalizeAgentRef(rawRef: any): AgentRef {
  if (typeof rawRef === 'string') {
    return { type: DEFAULT_AGENT_TYPE, ref: rawRef };
  }
  if (rawRef && typeof rawRef === 'object') {
    if ('type' in rawRef) {
      return { type: rawRef.type, ref: rawRef.ref, config: rawRef.config };
    }
    if (rawRef.spec === 'flatagent') {
      return { type: DEFAULT_AGENT_TYPE, config: rawRef };
    }
  }
  throw new Error('Invalid agent reference. Expected string path or {type, ref/config}.');
}

export function coerceAgentResult(value: any): AgentResult {
  if (value && typeof value === 'object' && ('output' in value || 'content' in value || 'error' in value || 'finish_reason' in value || 'usage' in value)) {
    return value as AgentResult;
  }
  if (value && typeof value === 'object') {
    return { output: value, raw: value };
  }
  if (value == null) {
    return {};
  }
  return { content: String(value), raw: value };
}

// ─────────────────────────────────────────────────────────────────────────────
// Adapter context and interface
// ─────────────────────────────────────────────────────────────────────────────

export interface AgentAdapterContext {
  config_dir: string;
  settings: Record<string, any>;
  machine_name: string;
  profiles_file?: string;
  profiles_dict?: Record<string, any>;
}

export interface AgentAdapter {
  readonly type_name: string;
  create_executor(opts: {
    agent_name: string;
    agent_ref: AgentRef;
    context: AgentAdapterContext;
  }): AgentExecutor;
}

// ─────────────────────────────────────────────────────────────────────────────
// Registry
// ─────────────────────────────────────────────────────────────────────────────

export class AgentAdapterRegistry {
  private _adapters = new Map<string, AgentAdapter>();

  constructor(adapters?: Iterable<AgentAdapter>) {
    // Register built-in adapters (loaded lazily to handle both ESM and CJS)
    this._registerBuiltins();
    if (adapters) {
      for (const adapter of adapters) this.register(adapter);
    }
  }

  private _registerBuiltins(): void {
    for (const factory of _builtinFactories) {
      try { this.register(factory()); } catch {}
    }
  }

  static registerBuiltinFactory(factory: () => AgentAdapter): void {
    _builtinFactories.push(factory);
  }

  register(adapter: AgentAdapter): void {
    this._adapters.set(adapter.type_name, adapter);
  }

  get(typeName: string): AgentAdapter {
    const adapter = this._adapters.get(typeName);
    if (!adapter) throw new Error(`No agent adapter registered for type '${typeName}'`);
    return adapter;
  }

  createExecutor(opts: {
    agent_name: string;
    agent_ref: AgentRef;
    context: AgentAdapterContext;
  }): AgentExecutor {
    const adapter = this.get(opts.agent_ref.type);
    return adapter.create_executor(opts);
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Rate Limit Window Builders
// ─────────────────────────────────────────────────────────────────────────────

function _parseIntHeader(headers: Record<string, string>, key: string): number | undefined {
  const val = headers[key] ?? headers[key.toLowerCase()];
  if (val != null) {
    const n = parseInt(val, 10);
    if (!isNaN(n)) return n;
  }
  return undefined;
}

function _parseDurationString(val: string): number | undefined {
  const s = val.trim();
  if (!s) return undefined;
  let totalSeconds = 0;
  let currentNum = '';
  let i = 0;
  while (i < s.length) {
    const char = s[i]!;
    if (/[\d.]/.test(char)) { currentNum += char; i++; continue; }
    if ('hms'.includes(char) && currentNum) {
      const num = parseFloat(currentNum);
      if (char === 'h') totalSeconds += num * 3600;
      else if (char === 'm') {
        if (i + 1 < s.length && s[i + 1] === 's') { totalSeconds += num / 1000; i++; }
        else totalSeconds += num * 60;
      } else if (char === 's') totalSeconds += num;
      currentNum = '';
    }
    i++;
  }
  if (currentNum) {
    const n = parseFloat(currentNum);
    if (!isNaN(n)) totalSeconds += n;
  }
  return totalSeconds > 0 ? Math.ceil(totalSeconds) : undefined;
}

function _parseIsoTimestamp(val: string): number | undefined {
  const d = new Date(val.trim());
  return isNaN(d.getTime()) ? undefined : d.getTime() / 1000;
}

export function buildRateLimitWindows(rawHeaders: Record<string, string>): RateLimitWindow[] {
  const windows: RateLimitWindow[] = [];

  // Cerebras time-bucketed limits
  for (const bucket of ['minute', 'hour', 'day']) {
    for (const resource of ['requests', 'tokens']) {
      const remaining = _parseIntHeader(rawHeaders, `x-ratelimit-remaining-${resource}-${bucket}`);
      const limit = _parseIntHeader(rawHeaders, `x-ratelimit-limit-${resource}-${bucket}`);
      if (remaining != null || limit != null) {
        const window: RateLimitWindow = { name: `${resource}_per_${bucket}`, resource };
        if (remaining != null) window.remaining = remaining;
        if (limit != null) window.limit = limit;
        if (bucket === 'minute') window.resets_in = 60;
        else if (bucket === 'hour') window.resets_in = 3600;
        else window.resets_in = 86400;
        windows.push(window);
      }
    }
  }

  // OpenAI-style
  for (const resource of ['requests', 'tokens']) {
    const remaining = _parseIntHeader(rawHeaders, `x-ratelimit-remaining-${resource}`);
    const limit = _parseIntHeader(rawHeaders, `x-ratelimit-limit-${resource}`);
    const resetStr = rawHeaders[`x-ratelimit-reset-${resource}`];
    if (remaining != null || limit != null) {
      const existing = windows.filter(w => w.resource === resource);
      if (!existing.length) {
        const window: RateLimitWindow = { name: resource, resource };
        if (remaining != null) window.remaining = remaining;
        if (limit != null) window.limit = limit;
        if (resetStr) {
          const resetsIn = _parseDurationString(resetStr);
          if (resetsIn != null) window.resets_in = resetsIn;
        }
        windows.push(window);
      }
    }
  }

  // Anthropic-style
  for (const resource of ['requests', 'tokens']) {
    const remaining = _parseIntHeader(rawHeaders, `anthropic-ratelimit-${resource}-remaining`);
    const limit = _parseIntHeader(rawHeaders, `anthropic-ratelimit-${resource}-limit`);
    const resetStr = rawHeaders[`anthropic-ratelimit-${resource}-reset`];
    if (remaining != null || limit != null) {
      const window: RateLimitWindow = { name: resource, resource };
      if (remaining != null) window.remaining = remaining;
      if (limit != null) window.limit = limit;
      if (resetStr) {
        const resetAt = _parseIsoTimestamp(resetStr);
        if (resetAt != null) window.reset_at = resetAt;
      }
      windows.push(window);
    }
  }

  return windows;
}

export function buildRateLimitState(
  rawHeaders: Record<string, string>,
  retryAfter?: number,
): RateLimitState {
  const windows = buildRateLimitWindows(rawHeaders);
  const limited = windows.some(w => w.remaining === 0);
  if (retryAfter == null) {
    retryAfter = _parseIntHeader(rawHeaders, 'retry-after');
  }
  const state: RateLimitState = { limited };
  if (retryAfter != null) state.retry_after = retryAfter;
  if (windows.length) state.windows = windows;
  return state;
}
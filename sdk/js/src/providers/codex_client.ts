/**
 * Codex SSE client — ports Python SDK's openai_codex_client.py
 *
 * Transport: SSE only. Retries on 429/500/502/503/504 with exponential backoff.
 */

import { createHash } from 'node:crypto';
import { platform, release, arch } from 'os';
import { CodexResult, CodexToolCall, CodexUsage } from './codex_types';
import {
  CodexAuthError,
  DEFAULT_PROVIDER,
  TOKEN_URL,
  OPENAI_CODEX_CLIENT_ID,
  PiAuthStore,
  isExpired,
  loadCodexCredential,
  refreshCodexCredential,
  resolveAuthFile,
} from './codex_auth';

const DEFAULT_BASE_URL = 'https://chatgpt.com/backend-api';
const RETRYABLE_STATUS_CODES = new Set([429, 500, 502, 503, 504]);

export class CodexClientError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'CodexClientError';
  }
}

export class CodexHTTPError extends CodexClientError {
  statusCode: number;
  body: string;
  headers: Record<string, string>;

  constructor(statusCode: number, body: string, message?: string, headers?: Record<string, string>) {
    super(message ?? `Codex request failed with status ${statusCode}`);
    this.name = 'CodexHTTPError';
    this.statusCode = statusCode;
    this.body = body;
    this.headers = headers ?? {};
  }
}

interface CodexClientConfig {
  baseUrl: string;
  originator: string;
  timeoutSeconds: number;
  maxRetries: number;
  refreshEnabled: boolean;
  provider: string;
  authFile: string;
  tokenUrl: string;
  clientId: string;
}

function firstNotNull<T>(...values: (T | undefined | null)[]): T | undefined {
  for (const v of values) {
    if (v != null) return v;
  }
  return undefined;
}

export class CodexClient {
  private config: CodexClientConfig;
  private modelConfig: Record<string, any>;
  private authStore: PiAuthStore;

  constructor(modelConfig: Record<string, any>, opts?: { configDir?: string }) {
    const oauthCfg = typeof modelConfig.oauth === 'object' && modelConfig.oauth ? modelConfig.oauth : {};
    const authCfg = typeof modelConfig.auth === 'object' && modelConfig.auth ? modelConfig.auth : {};

    const prov = String(
      firstNotNull(oauthCfg.provider, authCfg.provider, modelConfig.provider) ?? DEFAULT_PROVIDER
    );
    const refreshValue = firstNotNull(oauthCfg.refresh, modelConfig.codex_refresh) ?? true;

    this.config = {
      baseUrl: String(firstNotNull(modelConfig.base_url) ?? DEFAULT_BASE_URL),
      originator: String(firstNotNull(oauthCfg.originator, modelConfig.codex_originator) ?? 'pi'),
      timeoutSeconds: Number(firstNotNull(oauthCfg.timeout_seconds, modelConfig.codex_timeout_seconds) ?? 120),
      maxRetries: Number(firstNotNull(oauthCfg.max_retries, modelConfig.codex_max_retries) ?? 3),
      refreshEnabled: Boolean(refreshValue),
      provider: prov,
      authFile: resolveAuthFile({ modelConfig, configDir: opts?.configDir }),
      tokenUrl: String(firstNotNull(oauthCfg.token_url, modelConfig.codex_token_url) ?? TOKEN_URL),
      clientId: String(firstNotNull(oauthCfg.client_id, modelConfig.codex_client_id) ?? OPENAI_CODEX_CLIENT_ID),
    };

    this.modelConfig = modelConfig;
    this.authStore = new PiAuthStore(this.config.authFile);
  }

  async call(params: Record<string, any>): Promise<CodexResult> {
    let credential = loadCodexCredential(this.authStore, this.config.provider);

    // Pre-request refresh if expired
    if (this.config.refreshEnabled && isExpired(credential.expires, 0)) {
      try {
        credential = await refreshCodexCredential(this.authStore, this.config.provider, {
          timeoutSeconds: Math.min(this.config.timeoutSeconds, 30),
          tokenUrl: this.config.tokenUrl,
          clientId: this.config.clientId,
        });
      } catch (refreshErr) {
        const latest = loadCodexCredential(this.authStore, this.config.provider);
        if (!isExpired(latest.expires, 0)) {
          credential = latest;
        } else {
          throw refreshErr;
        }
      }
    }

    const sessionId = this.resolveSessionId(params);
    const body = this.buildRequestBody(params, sessionId);
    const headers = this.buildHeaders(credential.access, credential.account_id ?? '', sessionId, params);
    const requestBaseUrl = String(params.base_url || this.config.baseUrl);

    try {
      const { payload, responseHeaders, statusCode, retriesUsed } =
        await this.postWithRetries(body, headers, requestBaseUrl);
      const result = this.parseSseToResult(payload);
      result.response_headers = responseHeaders;
      result.response_status_code = statusCode;
      result.request_meta = {
        method: 'POST',
        url: this.resolveCodexUrl(requestBaseUrl),
        headers: this.redactHeaders(headers),
        retries_used: retriesUsed,
      };
      return result;
    } catch (firstError: any) {
      const shouldRefresh =
        this.config.refreshEnabled &&
        firstError instanceof CodexHTTPError &&
        (firstError.statusCode === 401 || firstError.statusCode === 403) &&
        credential.refresh;
      if (!shouldRefresh) throw firstError;

      const refreshed = await refreshCodexCredential(this.authStore, this.config.provider, {
        timeoutSeconds: Math.min(this.config.timeoutSeconds, 30),
        tokenUrl: this.config.tokenUrl,
        clientId: this.config.clientId,
      });
      const retryHeaders = this.buildHeaders(refreshed.access, refreshed.account_id ?? '', sessionId, params);
      const { payload, responseHeaders, statusCode, retriesUsed } =
        await this.postWithRetries(body, retryHeaders, requestBaseUrl);
      const result = this.parseSseToResult(payload);
      result.response_headers = responseHeaders;
      result.response_status_code = statusCode;
      result.request_meta = {
        method: 'POST',
        url: this.resolveCodexUrl(requestBaseUrl),
        headers: this.redactHeaders(retryHeaders),
        retries_used: retriesUsed,
      };
      return result;
    }
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Request building
  // ─────────────────────────────────────────────────────────────────────────

  private resolveSessionId(params: Record<string, any>): string | undefined {
    const sid = params.session_id ?? params.sessionId ?? this.modelConfig.codex_session_id;
    return sid ? String(sid) : undefined;
  }

  private buildRequestBody(params: Record<string, any>, sessionId?: string): Record<string, any> {
    const messages = (params.messages ?? []) as Array<Record<string, any>>;
    const { instructions, inputItems } = this.convertMessages(messages);

    const body: Record<string, any> = {
      model: this.normalizeModelName(String(params.model ?? '')),
      store: false,
      stream: true,
      instructions,
      input: inputItems,
      text: { verbosity: this.resolveTextVerbosity(params) },
      include: ['reasoning.encrypted_content'],
      tool_choice: 'auto',
      parallel_tool_calls: true,
    };

    if (sessionId) body.prompt_cache_key = sessionId;
    if (params.temperature != null) body.temperature = params.temperature;
    if (params.tools) body.tools = this.normalizeTools(params.tools);

    const reasoning = this.resolveReasoning(params);
    if (reasoning) body.reasoning = reasoning;

    const serviceTier = params.service_tier ?? this.modelConfig.service_tier;
    if (serviceTier) body.service_tier = serviceTier;

    return body;
  }

  private buildHeaders(
    accessToken: string,
    accountId: string,
    sessionId: string | undefined,
    params: Record<string, any>,
  ): Record<string, string> {
    if (!accountId) throw new CodexAuthError('Missing chatgpt account id. Re-run codex login.');

    const headers: Record<string, string> = {
      Authorization: `Bearer ${accessToken}`,
      'chatgpt-account-id': accountId,
      'OpenAI-Beta': 'responses=experimental',
      originator: this.config.originator,
      'User-Agent': `flatagents (${platform().toLowerCase()} ${release()}; ${arch()})`,
      accept: 'text/event-stream',
      'content-type': 'application/json',
    };

    if (sessionId) headers.session_id = sessionId;

    const cfgHeaders = this.modelConfig.headers;
    if (cfgHeaders && typeof cfgHeaders === 'object') {
      for (const [k, v] of Object.entries(cfgHeaders)) headers[String(k)] = String(v);
    }
    const paramHeaders = params.headers;
    if (paramHeaders && typeof paramHeaders === 'object') {
      for (const [k, v] of Object.entries(paramHeaders)) headers[String(k)] = String(v);
    }

    return headers;
  }

  private redactHeaders(headers: Record<string, string>): Record<string, string> {
    const redacted: Record<string, string> = {};
    for (const [k, v] of Object.entries(headers)) {
      redacted[k] = k.toLowerCase() === 'authorization' ? 'Bearer ***' : v;
    }
    return redacted;
  }

  // ─────────────────────────────────────────────────────────────────────────
  // HTTP transport with retries
  // ─────────────────────────────────────────────────────────────────────────

  private async postWithRetries(
    body: Record<string, any>,
    headers: Record<string, string>,
    baseUrl: string,
  ): Promise<{ payload: string; responseHeaders: Record<string, string>; statusCode: number; retriesUsed: number }> {
    const baseDelay = 1;
    const url = this.resolveCodexUrl(baseUrl);

    for (let attempt = 0; attempt <= this.config.maxRetries; attempt++) {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), this.config.timeoutSeconds * 1000);

      try {
        const response = await fetch(url, {
          method: 'POST',
          headers,
          body: JSON.stringify(body),
          signal: controller.signal,
        });

        const text = await response.text();
        const normHeaders: Record<string, string> = {};
        response.headers.forEach((v, k) => { normHeaders[k.toLowerCase()] = v; });

        if (response.status < 400) {
          return { payload: text, responseHeaders: normHeaders, statusCode: response.status, retriesUsed: attempt };
        }

        if (RETRYABLE_STATUS_CODES.has(response.status) && attempt < this.config.maxRetries) {
          await new Promise(r => setTimeout(r, baseDelay * (2 ** attempt) * 1000));
          continue;
        }

        const parsed = this.parseErrorResponse(response.status, text);
        throw new CodexHTTPError(response.status, text, parsed, normHeaders);
      } catch (err: any) {
        if (err instanceof CodexHTTPError) throw err;
        if (attempt >= this.config.maxRetries) {
          throw new CodexClientError(`Network error while calling Codex: ${err?.message ?? err}`);
        }
        await new Promise(r => setTimeout(r, baseDelay * (2 ** attempt) * 1000));
      } finally {
        clearTimeout(timer);
      }
    }

    throw new CodexClientError('Codex request failed after retries');
  }

  // ─────────────────────────────────────────────────────────────────────────
  // SSE parsing
  // ─────────────────────────────────────────────────────────────────────────

  private parseSseToResult(payload: string): CodexResult {
    const events = this.parseSseEvents(payload);

    const result: CodexResult = {
      content: '',
      tool_calls: [],
      usage: { input_tokens: 0, output_tokens: 0, total_tokens: 0, cached_tokens: 0 },
      raw_events: events,
      response_headers: {},
      request_meta: {},
    };

    const textParts: string[] = [];
    const toolArgsByCall: Record<string, string> = {};

    for (const event of events) {
      const type = event.type;

      if (type === 'error') {
        throw new CodexClientError(event.message ?? event.code ?? 'Codex error event received');
      }
      if (type === 'response.failed') {
        const errMsg = event.response?.error?.message;
        throw new CodexClientError(errMsg ?? 'Codex response failed');
      }
      if (type === 'response.output_text.delta') {
        if (typeof event.delta === 'string') textParts.push(event.delta);
      }
      if (type === 'response.function_call_arguments.delta') {
        const callId = String(event.call_id ?? event.item_id ?? 'call');
        toolArgsByCall[callId] = (toolArgsByCall[callId] ?? '') + String(event.delta ?? '');
      }
      if (type === 'response.output_item.done') {
        const item = typeof event.item === 'object' && event.item ? event.item : {};
        if (item.type === 'message' && !textParts.length) {
          for (const ci of item.content ?? []) {
            if (ci?.type === 'output_text' && typeof ci.text === 'string') textParts.push(ci.text);
          }
        }
        if (item.type === 'function_call') {
          const rawCallId = String(item.call_id ?? item.id ?? 'call');
          const callId = this.fitCallId(rawCallId);
          let argsJson = item.arguments;
          if (typeof argsJson !== 'string') argsJson = toolArgsByCall[rawCallId] ?? '{}';
          if (!argsJson) argsJson = '{}';
          result.tool_calls.push({ id: callId, name: String(item.name ?? 'unknown_tool'), arguments_json: argsJson });
        }
      }
      if (type === 'response.completed' || type === 'response.done') {
        const resp = typeof event.response === 'object' && event.response ? event.response : {};
        result.status = resp.status ? String(resp.status) : undefined;
        const u = typeof resp.usage === 'object' && resp.usage ? resp.usage : {};
        const inp = Number(u.input_tokens ?? 0);
        const out = Number(u.output_tokens ?? 0);
        result.usage = {
          input_tokens: inp,
          output_tokens: out,
          total_tokens: Number(u.total_tokens ?? inp + out),
          cached_tokens: Number(
            typeof u.input_tokens_details === 'object' ? u.input_tokens_details?.cached_tokens ?? 0 : 0
          ),
        };
      }
    }

    result.content = textParts.join('');
    result.finish_reason = this.mapFinishReason(result);
    return result;
  }

  private mapFinishReason(result: CodexResult): string {
    if (result.tool_calls.length) return 'tool_calls';
    if (result.status === 'incomplete') return 'length';
    return 'stop';
  }

  private parseSseEvents(payload: string): Array<Record<string, any>> {
    const events: Array<Record<string, any>> = [];
    const blocks = payload.replace(/\r\n/g, '\n').split('\n\n');

    for (const block of blocks) {
      const lines = block.split('\n').filter(l => l.startsWith('data:'));
      if (!lines.length) continue;
      const data = lines.map(l => l.slice(5).trim()).join('\n').trim();
      if (!data || data === '[DONE]') continue;
      try {
        const parsed = JSON.parse(data);
        if (typeof parsed === 'object' && parsed) events.push(parsed);
      } catch { /* skip */ }
    }
    return events;
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Message conversion
  // ─────────────────────────────────────────────────────────────────────────

  private convertMessages(messages: Array<Record<string, any>>): { instructions: string; inputItems: Array<Record<string, any>> } {
    const instructionParts: string[] = [];
    const inputItems: Array<Record<string, any>> = [];

    for (const msg of messages) {
      const role = msg.role;
      const contentText = this.coerceText(msg.content);

      if (role === 'system') {
        if (contentText) instructionParts.push(contentText);
        continue;
      }

      if (role === 'user' || role === 'assistant') {
        const typeName = role === 'user' ? 'input_text' : 'output_text';
        inputItems.push({ role, content: [{ type: typeName, text: contentText }] });

        if (role === 'assistant' && Array.isArray(msg.tool_calls)) {
          for (const tc of msg.tool_calls) {
            if (!tc || typeof tc !== 'object') continue;
            const fn = tc.function;
            if (!fn || typeof fn !== 'object') continue;
            const callId = this.fitCallId(String(tc.id ?? 'call'));
            inputItems.push({
              type: 'function_call',
              call_id: callId,
              name: String(fn.name ?? 'unknown_tool'),
              arguments: String(fn.arguments ?? '{}'),
            });
          }
        }
        continue;
      }

      if (role === 'tool') {
        const callId = this.fitCallId(String(msg.tool_call_id ?? 'call'));
        inputItems.push({ type: 'function_call_output', call_id: callId, output: contentText });
      }
    }

    return { instructions: instructionParts.filter(Boolean).join('\n\n'), inputItems };
  }

  private coerceText(content: any): string {
    if (content == null) return '';
    if (typeof content === 'string') return content;
    if (Array.isArray(content)) {
      return content.map(item => {
        if (typeof item === 'string') return item;
        if (item?.text) return String(item.text);
        return '';
      }).filter(Boolean).join('\n');
    }
    return String(content);
  }

  private fitCallId(callId: string): string {
    const normalized = callId || 'call';
    if (normalized.length <= 64) return normalized;
    const digest = createHash('sha256').update(normalized).digest('hex').slice(0, 16);
    return `${normalized.slice(0, 47)}_${digest}`;
  }

  private normalizeTools(tools: any): Array<Record<string, any>> {
    if (!Array.isArray(tools)) return [];
    return tools.map(t => {
      if (!t || typeof t !== 'object') return t;
      if (t.type !== 'function') return t;
      const fn = t.function;
      if (!fn || typeof fn !== 'object') return t;
      return {
        type: 'function',
        name: String(fn.name ?? ''),
        description: String(fn.description ?? ''),
        parameters: fn.parameters ?? { type: 'object', properties: {} },
      };
    }).filter(Boolean);
  }

  private resolveReasoning(params: Record<string, any>): Record<string, any> | undefined {
    const obj = typeof params.reasoning === 'object' ? params.reasoning : {};
    const effort = obj?.effort ?? params.reasoning_effort ?? this.modelConfig.codex_reasoning_effort;
    const summary = obj?.summary ?? params.reasoning_summary ?? this.modelConfig.codex_reasoning_summary;
    if (effort == null && summary == null) return undefined;
    const result: Record<string, any> = {};
    if (effort != null) result.effort = effort;
    if (summary != null) result.summary = summary;
    return result;
  }

  private resolveTextVerbosity(params: Record<string, any>): string {
    const obj = typeof params.text === 'object' ? params.text : {};
    return String(obj?.verbosity ?? params.verbosity ?? this.modelConfig.codex_text_verbosity ?? 'medium');
  }

  private normalizeModelName(model: string): string {
    return model.includes('/') ? model.split('/', 2)[1]! : model;
  }

  private resolveCodexUrl(baseUrl: string): string {
    const norm = baseUrl.replace(/\/+$/, '');
    if (norm.endsWith('/codex/responses')) return norm;
    if (norm.endsWith('/codex')) return `${norm}/responses`;
    return `${norm}/codex/responses`;
  }

  private parseErrorResponse(statusCode: number, text: string): string {
    let message = text || `Codex request failed (${statusCode})`;
    try {
      const parsed = JSON.parse(text);
      const err = parsed?.error ?? {};
      const code = String(err.code ?? err.type ?? '');
      const errMessage = err.message;

      if (/usage_limit_reached|usage_not_included|rate_limit_exceeded/.test(code)) {
        const plan = String(err.plan_type ?? '').toLowerCase();
        return `You have hit your ChatGPT usage limit${plan ? ` (${plan} plan)` : ''}.`;
      }
      if (statusCode === 429) return 'Rate limited by Codex. Please retry shortly.';
      if (statusCode === 401 || statusCode === 403) return 'Codex authentication failed. Run codex login again.';
      if (typeof errMessage === 'string' && errMessage) message = errMessage;
    } catch { /* use raw text */ }
    return message;
  }
}

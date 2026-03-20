/**
 * Claude Code CLI adapter for FlatMachines.
 *
 * Drives the Claude Code CLI (`claude -p`) as a subprocess, streaming NDJSON
 * events and mapping the result to AgentResult. Claude Code owns its own
 * tool loop — this adapter does NOT implement execute_with_tools().
 *
 * Ports Python SDK's adapters/claude_code.py.
 */

import { spawn, ChildProcess } from 'child_process';
import { resolve as resolvePath, isAbsolute } from 'path';
import { randomUUID } from 'node:crypto';
import { readFileSync, existsSync } from 'fs';
import * as yaml from 'yaml';
import {
  AgentAdapter,
  AgentAdapterContext,
  AgentExecutor,
  AgentRef,
  AgentResult,
} from '../agents';

// ─────────────────────────────────────────────────────────────────────────────
// Defaults
// ─────────────────────────────────────────────────────────────────────────────

const DEFAULT_MODEL = 'opus';
const DEFAULT_EFFORT = 'high';
const DEFAULT_EXIT_SENTINEL = '<<AGENT_EXIT>>';
const DEFAULT_CONTINUATION_PROMPT = 'Continue working. When fully done, emit <<AGENT_EXIT>> on its own line.';
const DEFAULT_MAX_CONTINUATIONS = 100;
const DEFAULT_RATE_LIMIT_DELAY = 3000; // ms
const DEFAULT_RATE_LIMIT_JITTER = 4000; // ms
const SIGTERM_GRACE_MS = 5000;

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────

function mapStopReason(stopReason?: string): string | undefined {
  if (!stopReason) return undefined;
  const mapping: Record<string, string> = {
    end_turn: 'stop',
    max_tokens: 'length',
    stop_sequence: 'stop',
  };
  return mapping[stopReason] ?? stopReason;
}

// ─────────────────────────────────────────────────────────────────────────────
// Stream collector
// ─────────────────────────────────────────────────────────────────────────────

class StreamCollector {
  events: Array<Record<string, any>> = [];
  resultEvent: Record<string, any> | null = null;
  sessionId?: string;
  orderedToolCalls: Array<Record<string, any>> = [];
  orderedToolResults: Array<Record<string, any>> = [];
  structuredOutput: Record<string, any> | null = null;
  rateLimitEvents: Array<Record<string, any>> = [];
  private pendingTools = new Map<string, Record<string, any>>();

  ingest(event: Record<string, any>): void {
    const type = event.type;

    if (type === 'system') {
      if (event.session_id) this.sessionId = event.session_id;
      this.events.push(event);
    } else if (type === 'assistant') {
      if (event.session_id) this.sessionId = event.session_id;
      const message = event.message ?? {};
      for (const block of message.content ?? []) {
        if (block?.type === 'tool_use') {
          const toolId = block.id ?? '';
          const toolName = block.name ?? '';
          const toolInput = block.input ?? {};
          this.pendingTools.set(toolId, { name: toolName, input: toolInput });
          this.orderedToolCalls.push({ id: toolId, name: toolName, arguments: toolInput });
          if (toolName === 'StructuredOutput') this.structuredOutput = toolInput;
        }
      }
      this.events.push(event);
    } else if (type === 'user') {
      const message = event.message ?? {};
      for (const block of message.content ?? []) {
        if (block?.type === 'tool_result') {
          const toolId = block.tool_use_id ?? '';
          const pending = this.pendingTools.get(toolId) ?? {};
          this.orderedToolResults.push({
            tool_call_id: toolId,
            name: pending.name ?? '',
            arguments: pending.input ?? {},
            content: block.content ?? '',
            is_error: block.is_error ?? false,
          });
        }
      }
      this.events.push(event);
    } else if (type === 'result') {
      this.resultEvent = event;
      if (event.session_id) this.sessionId = event.session_id;
      this.events.push(event);
    } else if (type === 'rate_limit_event') {
      const rlInfo = event.rate_limit_info ?? {};
      this.rateLimitEvents.push(rlInfo);
      this.events.push(event);
    } else {
      this.events.push(event);
    }
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Call throttle
// ─────────────────────────────────────────────────────────────────────────────

class CallThrottle {
  private delay: number;
  private jitter: number;
  private lastCall = 0;
  private lock = Promise.resolve();

  constructor(delay: number, jitter: number) {
    this.delay = delay;
    this.jitter = jitter;
  }

  async wait(): Promise<number> {
    return new Promise<number>((resolve) => {
      this.lock = this.lock.then(async () => {
        const now = Date.now();
        const jitterMs = Math.random() * 2 * this.jitter;
        const next = this.lastCall + this.delay + jitterMs;
        const waitMs = Math.max(0, next - now);
        if (waitMs > 0) await new Promise(r => setTimeout(r, waitMs));
        this.lastCall = Date.now();
        resolve(waitMs);
      });
    });
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Executor
// ─────────────────────────────────────────────────────────────────────────────

export class ClaudeCodeExecutor implements AgentExecutor {
  private config: Record<string, any>;
  private configDir: string;
  private settings: Record<string, any>;
  private merged: Record<string, any>;
  private throttle: CallThrottle;
  private proc: ChildProcess | null = null;

  constructor(config: Record<string, any>, configDir: string, settings: Record<string, any>) {
    this.config = config;
    this.configDir = configDir;
    this.settings = settings;
    this.merged = { ...settings, ...config };
    this.throttle = new CallThrottle(
      Number(this.merged.rate_limit_delay ?? DEFAULT_RATE_LIMIT_DELAY),
      Number(this.merged.rate_limit_jitter ?? DEFAULT_RATE_LIMIT_JITTER),
    );
  }

  get metadata(): Record<string, any> { return {}; }

  async execute(inputData: Record<string, any>, context?: Record<string, any>): Promise<AgentResult> {
    const task = inputData.task ?? inputData.prompt ?? '';
    if (!task) {
      return {
        error: { code: 'invalid_request', type: 'ValueError', message: 'claude-code adapter requires input.task or input.prompt', retryable: false },
        finish_reason: 'error',
      };
    }

    const resumeSession = inputData.resume_session;
    let sessionId = resumeSession ? String(resumeSession) : randomUUID();
    let resume = !!resumeSession;

    const cfg = this.merged;
    const maxContinuations = Number(cfg.max_continuations ?? DEFAULT_MAX_CONTINUATIONS);
    const exitSentinel = String(cfg.exit_sentinel ?? DEFAULT_EXIT_SENTINEL);
    const continuationPrompt = String(cfg.continuation_prompt ?? DEFAULT_CONTINUATION_PROMPT);

    let totalCost = 0;
    let totalInput = 0;
    let totalOutput = 0;
    let totalCacheRead = 0;
    let totalCacheWrite = 0;
    let allEvents: Array<Record<string, any>> = [];
    let lastResult: AgentResult | null = null;
    let currentTask = task;
    let attempt = 0;

    while (true) {
      const result = await this.invokeOnce(currentTask, sessionId, resume, context);
      attempt++;

      if (result.usage) {
        totalInput += (result.usage as any).input_tokens ?? 0;
        totalOutput += (result.usage as any).output_tokens ?? 0;
        totalCacheRead += (result.usage as any).cache_read_tokens ?? 0;
        totalCacheWrite += (result.usage as any).cache_write_tokens ?? 0;
      }
      if (result.cost != null) {
        totalCost += typeof result.cost === 'number' ? result.cost : (result.cost as any).total ?? 0;
      }
      if (result.metadata?.stream_events) allEvents.push(...result.metadata.stream_events);

      lastResult = result;
      if (result.error) break;

      const resultText = result.content ?? '';
      if (resultText.includes(exitSentinel)) break;
      if (result.finish_reason === 'stop' && result.metadata?.num_turns <= 1) break;
      if (maxContinuations === 0) break;
      if (maxContinuations > 0 && attempt > maxContinuations) break;

      currentTask = continuationPrompt;
      resume = true;
    }

    if (!lastResult) {
      return { error: { code: 'server_error', type: 'ClaudeCodeError', message: 'No result', retryable: false }, finish_reason: 'error' };
    }

    return {
      output: lastResult.output,
      content: lastResult.content,
      raw: lastResult.raw,
      usage: { input_tokens: totalInput, output_tokens: totalOutput, cache_read_tokens: totalCacheRead, cache_write_tokens: totalCacheWrite, api_calls: attempt },
      cost: totalCost > 0 ? totalCost : lastResult.cost,
      finish_reason: lastResult.finish_reason,
      error: lastResult.error,
      tool_calls: lastResult.tool_calls,
      metadata: { ...lastResult.metadata, stream_events: allEvents, continuation_attempts: attempt },
      provider_data: lastResult.provider_data,
    };
  }

  async execute_with_tools(): Promise<AgentResult> {
    throw new Error('Claude Code CLI adapter does not support machine-driven tool loops.');
  }

  async cancel(): Promise<boolean> {
    if (!this.proc) return false;
    this.proc.kill('SIGTERM');
    const proc = this.proc;
    return new Promise((resolve) => {
      const timer = setTimeout(() => { try { proc.kill('SIGKILL'); } catch {} }, SIGTERM_GRACE_MS);
      proc.once('exit', () => { clearTimeout(timer); resolve(true); });
    });
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Single invocation
  // ─────────────────────────────────────────────────────────────────────────

  private async invokeOnce(
    task: string,
    sessionId: string,
    resume: boolean,
    context?: Record<string, any>,
  ): Promise<AgentResult> {
    await this.throttle.wait();

    const cfg = this.merged;
    const args = this.buildArgs(task, sessionId, resume);

    let workingDir = cfg.working_dir;
    if (workingDir) {
      workingDir = resolvePath(String(workingDir));
    } else {
      workingDir = this.configDir;
    }

    const timeout = Number(cfg.timeout ?? 0) * 1000;
    const collector = new StreamCollector();

    return new Promise<AgentResult>((resolveResult) => {
      const bin = args[0]!;
      const proc = spawn(bin, args.slice(1), {
        cwd: workingDir,
        stdio: ['ignore', 'pipe', 'pipe'],
        env: process.env,
      });
      this.proc = proc;

      const stderrChunks: Buffer[] = [];
      let buffer = '';
      let timedOut = false;

      let timer: ReturnType<typeof setTimeout> | undefined;
      if (timeout > 0) {
        timer = setTimeout(() => {
          timedOut = true;
          try { proc.kill('SIGTERM'); } catch {}
          setTimeout(() => { try { proc.kill('SIGKILL'); } catch {} }, SIGTERM_GRACE_MS);
        }, timeout);
      }

      proc.stdout!.on('data', (chunk: Buffer) => {
        buffer += chunk.toString('utf-8');
        const lines = buffer.split('\n');
        buffer = lines.pop()!;
        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed) continue;
          try { collector.ingest(JSON.parse(trimmed)); } catch { /* skip */ }
        }
      });

      proc.stderr!.on('data', (chunk: Buffer) => stderrChunks.push(chunk));

      proc.once('exit', (code) => {
        if (timer) clearTimeout(timer);
        this.proc = null;

        // Flush remaining buffer
        if (buffer.trim()) {
          try { collector.ingest(JSON.parse(buffer.trim())); } catch { /* skip */ }
        }

        const stderrText = Buffer.concat(stderrChunks).toString('utf-8');

        if (timedOut) {
          resolveResult({
            error: { code: 'timeout', type: 'TimeoutError', message: `Claude Code timed out after ${timeout / 1000}s`, retryable: true },
            finish_reason: 'error',
            metadata: { session_id: collector.sessionId ?? sessionId, stream_events: collector.events, stderr: stderrText },
          });
          return;
        }

        if (code !== 0 && !collector.resultEvent) {
          resolveResult({
            error: { code: 'server_error', type: 'ClaudeCodeProcessError', message: `claude exited with code ${code}\nstderr: ${stderrText}`, retryable: false },
            finish_reason: 'error',
            metadata: { session_id: collector.sessionId ?? sessionId, stream_events: collector.events, stderr: stderrText },
          });
          return;
        }

        if (!collector.resultEvent) {
          resolveResult({
            error: { code: 'server_error', type: 'ClaudeCodeError', message: `No result event received\nstderr: ${stderrText}`, retryable: false },
            finish_reason: 'error',
            metadata: { session_id: collector.sessionId ?? sessionId, stream_events: collector.events, stderr: stderrText },
          });
          return;
        }

        resolveResult(this.buildResult(collector, sessionId, stderrText));
      });

      proc.once('error', (err) => {
        if (timer) clearTimeout(timer);
        this.proc = null;
        resolveResult({
          error: { code: 'server_error', type: 'ClaudeCodeSpawnError', message: err.message, retryable: false },
          finish_reason: 'error',
        });
      });
    });
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Arg builder
  // ─────────────────────────────────────────────────────────────────────────

  private buildArgs(task: string, sessionId: string, resume: boolean): string[] {
    const cfg = this.merged;
    const claudeBin = String(cfg.claude_bin ?? 'claude');
    const args = [claudeBin, '-p', task, '--output-format', 'stream-json', '--verbose'];

    if (resume) {
      args.push('--resume', sessionId);
    } else {
      args.push('--session-id', sessionId);
    }

    args.push('--model', String(cfg.model ?? DEFAULT_MODEL));

    if (cfg.permission_mode) args.push('--permission-mode', String(cfg.permission_mode));
    if (cfg.dangerously_skip_permissions) args.push('--dangerously-skip-permissions');

    if (cfg.add_dirs && Array.isArray(cfg.add_dirs)) {
      for (const d of cfg.add_dirs) args.push('--add-dir', String(d));
    }

    if (cfg.system_prompt) args.push('--system-prompt', String(cfg.system_prompt));
    else if (cfg.append_system_prompt) args.push('--append-system-prompt', String(cfg.append_system_prompt));

    if (cfg.tools && Array.isArray(cfg.tools)) args.push('--tools', ...cfg.tools.map(String));
    if (cfg.mcp_config) args.push('--mcp-config', String(cfg.mcp_config));

    const maxBudget = Number(cfg.max_budget_usd ?? 0);
    if (maxBudget > 0) args.push('--max-budget-usd', String(maxBudget));

    args.push('--effort', String(cfg.effort ?? DEFAULT_EFFORT));

    return args;
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Result builder
  // ─────────────────────────────────────────────────────────────────────────

  private buildResult(collector: StreamCollector, sessionId: string, stderrText: string): AgentResult {
    const event = collector.resultEvent!;
    const resolvedSession = collector.sessionId ?? event.session_id ?? sessionId;

    const usageRaw = event.usage ?? {};
    const usage = {
      input_tokens: usageRaw.input_tokens ?? 0,
      output_tokens: usageRaw.output_tokens ?? 0,
      cache_read_tokens: usageRaw.cache_read_input_tokens ?? 0,
      cache_write_tokens: usageRaw.cache_creation_input_tokens ?? 0,
    };

    let error = null;
    if (event.is_error) {
      error = {
        code: 'server_error',
        type: 'ClaudeCodeError',
        message: `${event.result ?? 'Unknown error'}${stderrText ? `\nstderr: ${stderrText}` : ''}`,
        retryable: false,
      };
    }

    let output: Record<string, any>;
    if (collector.structuredOutput) {
      output = { ...collector.structuredOutput, session_id: resolvedSession, _raw_result: event.result };
    } else {
      output = { result: event.result, session_id: resolvedSession };
    }

    // Rate limit
    let rateLimit = null;
    if (collector.rateLimitEvents.length) {
      const info = collector.rateLimitEvents[collector.rateLimitEvents.length - 1]!;
      const windows: Array<Record<string, any>> = [];
      for (const res of ['requests', 'tokens'] as const) {
        const rem = info[`${res}_remaining`];
        const lim = info[`${res}_limit`];
        if (rem != null || lim != null) {
          const w: Record<string, any> = { name: res, resource: res };
          if (rem != null) w.remaining = rem;
          if (lim != null) w.limit = lim;
          windows.push(w);
        }
      }
      rateLimit = {
        limited: windows.some(w => w.remaining === 0),
        retry_after: info.retry_after_seconds,
        windows,
      };
    }

    return {
      output,
      content: event.result ?? null,
      raw: event,
      usage,
      cost: event.total_cost_usd ?? null,
      finish_reason: mapStopReason(event.stop_reason) ?? null,
      error,
      rate_limit: rateLimit,
      tool_calls: collector.orderedToolCalls.length ? collector.orderedToolCalls : null,
      metadata: {
        num_turns: event.num_turns,
        duration_ms: event.duration_ms,
        duration_api_ms: event.duration_api_ms,
        session_id: resolvedSession,
        stream_events: collector.events,
        stderr: stderrText,
        tool_results: collector.orderedToolResults.length ? collector.orderedToolResults : null,
      },
      provider_data: event.modelUsage ?? null,
    };
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Adapter
// ─────────────────────────────────────────────────────────────────────────────

export class ClaudeCodeAdapter implements AgentAdapter {
  readonly type_name = 'claude-code';

  create_executor(opts: {
    agent_name: string;
    agent_ref: AgentRef;
    context: AgentAdapterContext;
  }): AgentExecutor {
    let config = opts.agent_ref.config ?? {};

    if (!Object.keys(config).length && opts.agent_ref.ref) {
      const loaded = this.loadRef(opts.agent_ref.ref, opts.context.config_dir);
      if (loaded) config = loaded;
    }

    const settings = (opts.context.settings as any)?.agent_runners?.claude_code ?? {};

    return new ClaudeCodeExecutor(config, opts.context.config_dir, settings);
  }

  private loadRef(ref: string, configDir: string): Record<string, any> | null {
    const path = isAbsolute(ref) ? ref : resolvePath(configDir, ref);
    if (!existsSync(path)) return null;
    const raw = readFileSync(path, 'utf-8');
    if (path.endsWith('.json')) return JSON.parse(raw);
    return yaml.parse(raw);
  }
}

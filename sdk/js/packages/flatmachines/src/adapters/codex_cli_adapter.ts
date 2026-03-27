/**
 * Codex CLI adapter for FlatMachines.
 *
 * Uses `codex exec --json` subprocess transport (including resume via
 * `codex exec resume`). Codex owns its tool loop, so execute_with_tools()
 * is intentionally unsupported.
 */

import { spawn, ChildProcess } from 'child_process';
import { resolve as resolvePath, isAbsolute } from 'path';
import { readFileSync, existsSync } from 'fs';
import * as yaml from 'yaml';
import {
  AgentAdapter,
  AgentAdapterContext,
  AgentAdapterRegistry,
  AgentExecutor,
  AgentRef,
  AgentResult,
} from '@memgrafter/flatagents';

const DEFAULT_MODEL = 'gpt-5.3-codex';
const DEFAULT_REASONING_EFFORT = 'high';
const DEFAULT_SANDBOX = 'workspace-write';
const DEFAULT_APPROVAL = 'never';
const SIGTERM_GRACE_MS = 5000;

type JsonDict = Record<string, any>;

class ExecStreamCollector {
  events: JsonDict[] = [];
  threadId?: string;
  items: JsonDict[] = [];
  usage?: JsonDict;
  error?: JsonDict;
  finalMessage?: string;

  ingest(event: JsonDict): void {
    const eventType = event.type;
    this.events.push(event);

    if (eventType === 'thread.started' && typeof event.thread_id === 'string') {
      this.threadId = event.thread_id;
      return;
    }

    if (eventType === 'item.completed') {
      const item = (event.item ?? {}) as JsonDict;
      this.items.push(item);
      const itemType = item.type;
      if ((itemType === 'agent_message' || itemType === 'agentMessage') && typeof item.text === 'string') {
        this.finalMessage = item.text;
      }
      return;
    }

    if (eventType === 'turn.completed') {
      const usage = event.usage;
      if (usage && typeof usage === 'object') this.usage = usage as JsonDict;
      return;
    }

    if (eventType === 'turn.failed') {
      const err = event.error;
      this.error = err && typeof err === 'object' ? (err as JsonDict) : { message: String(err ?? 'Unknown error') };
      return;
    }

    if (eventType === 'error') {
      this.error = { message: event.message ?? 'Unknown error' };
    }
  }
}

function usageInt(usage: JsonDict, keys: string[]): number {
  for (const key of keys) {
    const value = usage[key];
    if (typeof value === 'number' && Number.isFinite(value)) return value;
  }
  return 0;
}

export class CodexCliExecutor implements AgentExecutor {
  private readonly config: JsonDict;
  private readonly configDir: string;
  private readonly settings: JsonDict;
  private readonly merged: JsonDict;
  private proc: ChildProcess | null = null;

  constructor(config: JsonDict, configDir: string, settings: JsonDict) {
    this.config = config;
    this.configDir = configDir;
    this.settings = settings;
    this.merged = { ...settings, ...config };
  }

  get metadata(): JsonDict {
    return {};
  }

  async execute(inputData: JsonDict, context?: JsonDict): Promise<AgentResult> {
    const taskRaw = inputData.task ?? inputData.prompt ?? '';
    const task = String(taskRaw ?? '').trim();
    if (!task) {
      return {
        error: {
          code: 'invalid_request',
          type: 'ValueError',
          message: 'codex-cli adapter requires input.task or input.prompt',
          retryable: false,
        },
        finish_reason: 'error',
      };
    }

    const resumeSession = inputData.resume_session != null ? String(inputData.resume_session) : undefined;
    const args = this.buildExecArgs(task, resumeSession);
    const timeoutMs = Math.max(0, Number(this.merged.timeout ?? 0)) * 1000;
    const workingDir = this.resolveWorkingDir(context);
    const collector = new ExecStreamCollector();

    return new Promise<AgentResult>((resolveResult) => {
      const bin = args[0] ?? 'codex';
      const child = spawn(bin, args.slice(1), {
        cwd: workingDir,
        stdio: ['ignore', 'pipe', 'pipe'],
        env: process.env,
      });
      this.proc = child;

      const stderrChunks: Buffer[] = [];
      let stdoutBuffer = '';
      let timedOut = false;

      let timer: ReturnType<typeof setTimeout> | undefined;
      if (timeoutMs > 0) {
        timer = setTimeout(() => {
          timedOut = true;
          try { child.kill('SIGTERM'); } catch { /* ignore */ }
          setTimeout(() => {
            try { child.kill('SIGKILL'); } catch { /* ignore */ }
          }, SIGTERM_GRACE_MS);
        }, timeoutMs);
      }

      child.stdout?.on('data', (chunk: Buffer) => {
        stdoutBuffer += chunk.toString('utf-8');
        const lines = stdoutBuffer.split('\n');
        stdoutBuffer = lines.pop() ?? '';
        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed) continue;
          try {
            collector.ingest(JSON.parse(trimmed) as JsonDict);
          } catch {
            // ignore non-JSONL noise
          }
        }
      });

      child.stderr?.on('data', (chunk: Buffer) => {
        stderrChunks.push(chunk);
      });

      child.once('error', (err) => {
        if (timer) clearTimeout(timer);
        this.proc = null;
        resolveResult({
          error: {
            code: 'server_error',
            type: 'CodexCliSpawnError',
            message: err.message,
            retryable: false,
          },
          finish_reason: 'error',
        });
      });

      child.once('exit', (code) => {
        if (timer) clearTimeout(timer);
        this.proc = null;

        if (stdoutBuffer.trim()) {
          try {
            collector.ingest(JSON.parse(stdoutBuffer.trim()) as JsonDict);
          } catch {
            // ignore tail parse failures
          }
        }

        const stderrText = Buffer.concat(stderrChunks).toString('utf-8');

        if (timedOut) {
          resolveResult({
            error: {
              code: 'timeout',
              type: 'TimeoutError',
              message: `codex timed out after ${timeoutMs / 1000}s`,
              retryable: true,
            },
            finish_reason: 'error',
            metadata: {
              thread_id: collector.threadId ?? resumeSession,
              stream_events: collector.events,
              stderr: stderrText,
            },
          });
          return;
        }

        const result = this.buildResultFromExec(collector, code, stderrText);
        if (!result.output) result.output = {};
        if (resumeSession && result.output.thread_id == null) {
          result.output.thread_id = resumeSession;
        }
        resolveResult(result);
      });
    });
  }

  async execute_with_tools(): Promise<AgentResult> {
    throw new Error('Codex CLI adapter does not support machine-driven tool loops. Remove tool_loop from the state config.');
  }

  async cancel(): Promise<boolean> {
    if (!this.proc) return false;
    const proc = this.proc;
    try {
      proc.kill('SIGTERM');
    } catch {
      return false;
    }
    return new Promise<boolean>((resolve) => {
      const timer = setTimeout(() => {
        try { proc.kill('SIGKILL'); } catch { /* ignore */ }
      }, SIGTERM_GRACE_MS);
      proc.once('exit', () => {
        clearTimeout(timer);
        resolve(true);
      });
    });
  }

  private resolveWorkingDir(context?: JsonDict): string {
    const cfgDir = this.configDir;
    const value = this.merged.working_dir;
    if (typeof value !== 'string' || !value.trim()) return cfgDir;

    const rendered = value.replace(/\{\{\s*context\.([\w_]+)\s*\}\}/g, (_m, key) => {
      const v = context?.[String(key)];
      return v == null ? '' : String(v);
    });

    if (!rendered.trim()) return cfgDir;
    return isAbsolute(rendered) ? rendered : resolvePath(cfgDir, rendered);
  }

  private buildExecArgs(task: string, resumeSession?: string): string[] {
    const cfg = this.merged;
    const codexBin = String(cfg.codex_bin ?? 'codex');
    const model = String(cfg.model ?? DEFAULT_MODEL);
    const sandbox = String(cfg.sandbox ?? DEFAULT_SANDBOX);
    const approval = String(cfg.approval_policy ?? DEFAULT_APPROVAL);
    const isResume = !!resumeSession;

    const args = isResume
      ? [codexBin, 'exec', 'resume', '--json', '--model', model]
      : [codexBin, 'exec', '--json', '--model', model];

    if (cfg.dangerously_bypass_approvals_and_sandbox) {
      args.push('--dangerously-bypass-approvals-and-sandbox');
    } else if (isResume) {
      args.push('--full-auto');
    } else {
      args.push('--sandbox', sandbox);
      if (approval === 'never' || approval === 'on-request' || approval === 'untrusted') {
        args.push('--full-auto');
      }
    }

    const effort = String(cfg.reasoning_effort ?? DEFAULT_REASONING_EFFORT);
    if (effort) {
      args.push('-c', `reasoning_effort="${effort}"`);
    }

    if (cfg.output_schema != null) {
      args.push('--output-schema', String(cfg.output_schema));
    }

    const addDirs = Array.isArray(cfg.add_dirs) ? cfg.add_dirs : [];
    for (const dir of addDirs) {
      args.push('--add-dir', String(dir));
    }

    if (cfg.skip_git_repo_check) args.push('--skip-git-repo-check');
    if (cfg.ephemeral) args.push('--ephemeral');
    if (cfg.search) args.push('-c', 'search=true');

    const overrides = cfg.config_overrides;
    if (overrides && typeof overrides === 'object') {
      for (const [key, value] of Object.entries(overrides)) {
        args.push('-c', `${key}=${value}`);
      }
    }

    const featureEnable = Array.isArray(cfg.feature_enable) ? cfg.feature_enable : [];
    for (const feat of featureEnable) args.push('--enable', String(feat));

    const featureDisable = Array.isArray(cfg.feature_disable) ? cfg.feature_disable : [];
    for (const feat of featureDisable) args.push('--disable', String(feat));

    if (resumeSession) args.push(resumeSession, task);
    else args.push(task);

    return args;
  }

  private buildResultFromExec(
    collector: ExecStreamCollector,
    returnCode: number | null,
    stderrText: string,
  ): AgentResult {
    if (collector.error) {
      const errMsg = String(collector.error.message ?? 'Unknown error');
      const message = stderrText ? `${errMsg}\nstderr: ${stderrText}` : errMsg;
      return {
        error: {
          code: 'server_error',
          type: 'CodexCliError',
          message,
          retryable: false,
        },
        finish_reason: 'error',
        content: collector.finalMessage,
        metadata: {
          thread_id: collector.threadId,
          stream_events: collector.events,
          items: collector.items,
          stderr: stderrText,
        },
      };
    }

    if (returnCode != null && returnCode !== 0 && collector.finalMessage == null) {
      return {
        error: {
          code: 'server_error',
          type: 'CodexCliProcessError',
          message: `codex exited with code ${returnCode}\nstderr: ${stderrText}`,
          retryable: returnCode === 137 || returnCode === 143,
        },
        finish_reason: 'error',
        metadata: {
          thread_id: collector.threadId,
          stream_events: collector.events,
          stderr: stderrText,
        },
      };
    }

    let usage: JsonDict | undefined;
    if (collector.usage) {
      usage = {
        input_tokens: usageInt(collector.usage, ['input_tokens', 'inputTokens']),
        output_tokens: usageInt(collector.usage, ['output_tokens', 'outputTokens']),
        cached_input_tokens: usageInt(collector.usage, ['cached_input_tokens', 'cachedInputTokens']),
      };
    }

    return {
      output: {
        result: collector.finalMessage,
        thread_id: collector.threadId,
      },
      content: collector.finalMessage,
      usage,
      finish_reason: 'stop',
      metadata: {
        thread_id: collector.threadId,
        stream_events: collector.events,
        items: collector.items,
        stderr: stderrText,
      },
    };
  }
}

export class CodexCliAdapter implements AgentAdapter {
  readonly type_name = 'codex-cli';

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

    const settings = (opts.context.settings as any)?.agent_runners?.codex_cli ?? {};
    return new CodexCliExecutor(config, opts.context.config_dir, settings);
  }

  private loadRef(ref: string, configDir: string): JsonDict | null {
    const path = isAbsolute(ref) ? ref : resolvePath(configDir, ref);
    if (!existsSync(path)) return null;
    const raw = readFileSync(path, 'utf-8');
    if (path.endsWith('.json')) return JSON.parse(raw) as JsonDict;
    return yaml.parse(raw) as JsonDict;
  }
}

AgentAdapterRegistry.registerBuiltinFactory(() => new CodexCliAdapter());

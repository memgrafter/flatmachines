/**
 * Session holdback pattern for Claude Code CLI adapter.
 */

import { randomUUID } from 'node:crypto';
import { ClaudeCodeExecutor } from './claude_code_adapter';

export class ForkResult {
  session_id: string;
  task: string;
  result: any;
  cache_read_tokens: number;
  cache_write_tokens: number;

  constructor(opts: { session_id: string; task: string; result: any; cache_read_tokens: number; cache_write_tokens: number }) {
    this.session_id = opts.session_id;
    this.task = opts.task;
    this.result = opts.result;
    this.cache_read_tokens = opts.cache_read_tokens;
    this.cache_write_tokens = opts.cache_write_tokens;
  }
}

export class SessionHoldback {
  public executor: ClaudeCodeExecutor;
  public session_id: string | null;
  public _seeded: boolean = false;
  public _fork_count: number = 0;
  public _total_cost: number = 0;

  constructor(executor: ClaudeCodeExecutor, sessionId?: string) {
    this.executor = executor;
    this.session_id = sessionId ?? null;
  }

  async seed(task: string, context?: Record<string, any>): Promise<any> {
    if (this.session_id == null) {
      this.session_id = randomUUID();
    }

    const invoker = (this.executor as any)._invoke_once ?? (this.executor as any).invokeOnce;
    if (!invoker) throw new Error('Executor missing _invoke_once method');

    let result: any;
    try {
      result = await invoker.call(this.executor, {
        task,
        session_id: this.session_id,
        resume: false,
        context,
      });
    } catch (e) {
      this._seeded = true;
      throw e;
    }

    this._seeded = true;
    this._accumulate_cost(result);
    return result;
  }

  async adopt(sessionId: string): Promise<void> {
    this.session_id = sessionId;
    this._seeded = true;
  }

  async fork(task: string, context?: Record<string, any>): Promise<ForkResult> {
    if (!this._seeded) {
      throw new Error('Holdback not seeded — call seed() or adopt() first');
    }

    const invoker = (this.executor as any)._invoke_once ?? (this.executor as any).invokeOnce;
    if (!invoker) throw new Error('Executor missing _invoke_once method');

    const result = await invoker.call(this.executor, {
      task,
      session_id: this.session_id,
      resume: true,
      context,
      fork_session: true,
    });

    this._fork_count += 1;
    this._accumulate_cost(result);

    const usage = result?.usage ?? {};
    const forkSession = result?.metadata?.session_id ?? result?.session_id ?? '?';

    return new ForkResult({
      session_id: forkSession,
      task,
      result,
      cache_read_tokens: usage.cache_read_tokens ?? 0,
      cache_write_tokens: usage.cache_write_tokens ?? 0,
    });
  }

  async fork_n(
    tasks: string[],
    context?: Record<string, any>,
    maxConcurrent?: number,
  ): Promise<ForkResult[]> {
    if (!this._seeded) {
      throw new Error('Holdback not seeded — call seed() or adopt() first');
    }

    const concurrency = maxConcurrent && maxConcurrent > 0 ? maxConcurrent : tasks.length;
    const results: ForkResult[] = new Array(tasks.length);
    let active = 0;
    let nextIndex = 0;
    const queue: Array<() => void> = [];

    const forkOne = async (index: number): Promise<void> => {
      try {
        results[index] = await this.fork(tasks[index]!, context);
      } catch (e: any) {
        results[index] = new ForkResult({
          session_id: '',
          task: tasks[index]!,
          result: {
            error: {
              code: 'server_error',
              type: e?.name ?? 'Error',
              message: e?.message ?? String(e),
              retryable: false,
            },
            finish_reason: 'error',
          },
          cache_read_tokens: 0,
          cache_write_tokens: 0,
        });
      }
    };

    // Simple semaphore-based concurrent execution
    const promises: Promise<void>[] = [];
    for (let i = 0; i < tasks.length; i++) {
      if (concurrency >= tasks.length) {
        promises.push(forkOne(i));
      } else {
        // Use a semaphore pattern
        promises.push((async () => {
          while (active >= concurrency) {
            await new Promise<void>(resolve => queue.push(resolve));
          }
          active++;
          try {
            await forkOne(i);
          } finally {
            active--;
            if (queue.length) queue.shift()!();
          }
        })());
      }
    }

    await Promise.all(promises);
    return results;
  }

  async warm(context?: Record<string, any>): Promise<any> {
    if (!this._seeded) {
      throw new Error('Holdback not seeded — call seed() or adopt() first');
    }

    const invoker = (this.executor as any)._invoke_once ?? (this.executor as any).invokeOnce;
    if (!invoker) throw new Error('Executor missing _invoke_once method');

    const result = await invoker.call(this.executor, {
      task: 'test',
      session_id: this.session_id,
      resume: true,
      context,
      fork_session: true,
    });

    this._accumulate_cost(result);
    return result;
  }

  get stats(): Record<string, any> {
    return {
      session_id: this.session_id,
      seeded: this._seeded,
      fork_count: this._fork_count,
      total_cost: this._total_cost,
    };
  }

  private _accumulate_cost(result: any): void {
    if (result?.cost != null) {
      if (typeof result.cost === 'number') {
        this._total_cost += result.cost;
      } else if (typeof result.cost === 'object' && result.cost.total != null) {
        this._total_cost += Number(result.cost.total);
      }
    }
  }
}
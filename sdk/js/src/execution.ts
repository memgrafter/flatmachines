import { ExecutionConfig, ExecutionType } from './types';

export class DefaultExecution implements ExecutionType {
  async execute<T>(fn: () => Promise<T>): Promise<T> {
    return fn();
  }
}

export class RetryExecution implements ExecutionType {
  constructor(private backoffs = [2, 8, 16, 35], private jitter = 0.1) {}

  async execute<T>(fn: () => Promise<T>): Promise<T> {
    let lastError: Error | undefined;
    for (let i = 0; i <= this.backoffs.length; i++) {
      try {
        return await fn();
      } catch (err) {
        lastError = err as Error;
        if (i < this.backoffs.length) {
          const delay = this.backoffs[i] * (1 + this.jitter * (Math.random() * 2 - 1));
          await new Promise(r => setTimeout(r, delay * 1000));
        }
      }
    }
    throw lastError;
  }
}

export class ParallelExecution implements ExecutionType {
  constructor(private nSamples = 3) {}

  async execute<T>(fn: () => Promise<T>): Promise<any> {
    const tasks = Array.from({ length: this.nSamples }, () => fn());
    const results = await Promise.allSettled(tasks);
    const valid = results
      .filter((r) => r.status === "fulfilled")
      .map((r) => (r as PromiseFulfilledResult<T>).value);
    if (!valid.length) {
      throw new Error("Parallel execution produced no successful results");
    }
    return { results: valid, count: valid.length };
  }
}

export class MDAPVotingExecution implements ExecutionType {
  constructor(private kMargin = 3, private maxCandidates = 10) {}

  async execute<T>(fn: () => Promise<T>): Promise<T> {
    const votes = new Map<string, { value: T; count: number }>();
    let samples = 0;

    while (samples < this.maxCandidates) {
      const value = await fn();
      const key = JSON.stringify(value ?? null);
      const entry = votes.get(key) ?? { value, count: 0 };
      entry.count += 1;
      votes.set(key, entry);
      samples += 1;

      const sorted = [...votes.values()].sort((a, b) => b.count - a.count);
      const leader = sorted[0];
      const runnerUp = sorted[1];
      if (leader && leader.count - (runnerUp?.count ?? 0) >= this.kMargin) {
        return leader.value;
      }
    }

    const winner = [...votes.values()].sort((a, b) => b.count - a.count)[0];
    return winner?.value as T;
  }
}

export function getExecutionType(config?: ExecutionConfig): ExecutionType {
  if (config?.type === "retry") return new RetryExecution(config.backoffs, config.jitter);
  if (config?.type === "parallel") return new ParallelExecution(config.n_samples ?? 3);
  if (config?.type === "mdap_voting") return new MDAPVotingExecution(config.k_margin ?? 3, config.max_candidates ?? 10);
  return new DefaultExecution();
}

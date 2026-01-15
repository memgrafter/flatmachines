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

export function getExecutionType(config?: ExecutionConfig): ExecutionType {
  if (config?.type === "retry") return new RetryExecution(config.backoffs, config.jitter);
  return new DefaultExecution();
}
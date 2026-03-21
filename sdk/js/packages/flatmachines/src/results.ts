import type { ResultBackend } from './types';

class TimeoutError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "TimeoutError";
  }
}

type Waiter = {
  resolve: (value: any) => void;
  reject: (error: Error) => void;
  timeoutId?: ReturnType<typeof setTimeout>;
};

const store = new Map<string, any>();
const waiters = new Map<string, Set<Waiter>>();

const addWaiter = (uri: string, waiter: Waiter) => {
  const current = waiters.get(uri) ?? new Set<Waiter>();
  current.add(waiter);
  waiters.set(uri, current);
};

const removeWaiter = (uri: string, waiter: Waiter) => {
  const current = waiters.get(uri);
  if (!current) return;
  current.delete(waiter);
  if (current.size === 0) waiters.delete(uri);
};

const notifyWaiters = (uri: string, data: any) => {
  const current = waiters.get(uri);
  if (!current) return;
  for (const waiter of current) {
    if (waiter.timeoutId) clearTimeout(waiter.timeoutId);
    waiter.resolve(data);
  }
  waiters.delete(uri);
};

export const inMemoryResultBackend: ResultBackend = {
  async write(uri, data) {
    store.set(uri, data);
    notifyWaiters(uri, data);
  },

  async read(uri, opts) {
    if (!opts?.block) {
      return store.get(uri);
    }
    if (store.has(uri)) {
      return store.get(uri);
    }
    return new Promise((resolve, reject) => {
      const waiter: Waiter = { resolve, reject };
      addWaiter(uri, waiter);
      if (opts.timeout !== undefined) {
        waiter.timeoutId = setTimeout(() => {
          removeWaiter(uri, waiter);
          reject(new TimeoutError(`Timed out waiting for ${uri}`));
        }, opts.timeout);
      }
    });
  },

  async exists(uri) {
    return store.has(uri);
  },

  async delete(uri) {
    store.delete(uri);
  },
};
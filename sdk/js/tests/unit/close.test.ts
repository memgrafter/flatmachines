import { describe, expect, test, vi } from 'vitest';
import { FlatMachine, MemoryBackend, MemoryConfigStore, MemorySignalBackend } from '@memgrafter/flatmachines';

const minimalConfig = {
  spec: 'flatmachine' as const,
  spec_version: '1.0.0',
  data: {
    name: 'close-test',
    states: {
      start: { type: 'initial' as const, transitions: [{ to: 'done' }] },
      done: { type: 'final' as const, output: {} },
    },
  },
};

describe('FlatMachine.close()', () => {
  test('close() is callable', () => {
    const machine = new FlatMachine({ config: minimalConfig });
    expect(typeof machine.close).toBe('function');
    machine.close();
  });

  test('close() is safe to call multiple times', () => {
    const machine = new FlatMachine({ config: minimalConfig });
    machine.close();
    machine.close(); // should not throw
  });

  test('Symbol.dispose is defined', () => {
    const machine = new FlatMachine({ config: minimalConfig });
    expect(typeof machine[Symbol.dispose]).toBe('function');
    machine[Symbol.dispose]();
  });

  test('close() calls close on persistence backend', () => {
    const backend = new MemoryBackend();
    (backend as any).close = vi.fn();

    const machine = new FlatMachine({
      config: {
        ...minimalConfig,
        data: { ...minimalConfig.data, persistence: { enabled: true, backend: 'memory' } },
      },
      persistence: backend,
    });

    machine.close();
    expect((backend as any).close).toHaveBeenCalled();
  });

  test('close() calls close on signal backend', () => {
    const signalBackend = new MemorySignalBackend();
    (signalBackend as any).close = vi.fn();

    const machine = new FlatMachine({
      config: minimalConfig,
      signalBackend,
    } as any);

    machine.close();
    expect((signalBackend as any).close).toHaveBeenCalled();
  });

  test('close() calls close on config store', () => {
    const configStore = new MemoryConfigStore();
    (configStore as any).close = vi.fn();

    const machine = new FlatMachine({
      config: minimalConfig,
      configStore,
    } as any);

    machine.close();
    expect((configStore as any).close).toHaveBeenCalled();
  });

  test('close() does not throw when backends lack close()', () => {
    const machine = new FlatMachine({ config: minimalConfig });
    // MemoryBackend, default signal, no config store — none have close()
    expect(() => machine.close()).not.toThrow();
  });
});

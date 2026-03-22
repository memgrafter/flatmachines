/**
 * Runtime Spec Compliance Tests
 *
 * Verifies that all implementations conform to the interfaces
 * defined in flatagents-runtime.d.ts.
 *
 * These tests focus on interface compliance (method signatures).
 */

import { describe, it, expect, beforeEach } from 'vitest';
import {
  NoOpLock,
  LocalFileLock,
  MemoryBackend,
  LocalFileBackend,
  inMemoryResultBackend,
  DefaultExecution,
  RetryExecution,
  ParallelExecution,
  MDAPVotingExecution,
} from '@memgrafter/flatmachines';
import { VercelAIBackend, MockLLMBackend } from '@memgrafter/flatagents';
import type {
  ExecutionLock,
  PersistenceBackend,
  ResultBackend,
  ExecutionType,
  MachineSnapshot,
} from '@memgrafter/flatagents';
import type { LLMBackend } from '@memgrafter/flatagents';

describe('Runtime Spec Compliance', () => {
  describe('ExecutionLock Interface', () => {
    const locks: { name: string; create: () => ExecutionLock }[] = [
      { name: 'NoOpLock', create: () => new NoOpLock() },
      { name: 'LocalFileLock', create: () => new LocalFileLock('/tmp/test-locks-compliance') },
    ];

    for (const { name, create } of locks) {
      describe(name, () => {
        let lock: ExecutionLock;

        beforeEach(() => {
          lock = create();
        });

        it('has acquire method that returns Promise<boolean>', async () => {
          expect(typeof lock.acquire).toBe('function');
          const result = lock.acquire('test-key');
          expect(result).toBeInstanceOf(Promise);
          const value = await result;
          expect(typeof value).toBe('boolean');
        });

        it('has release method that returns Promise<void>', async () => {
          expect(typeof lock.release).toBe('function');
          const result = lock.release('test-key');
          expect(result).toBeInstanceOf(Promise);
          const value = await result;
          expect(value).toBeUndefined();
        });
      });
    }

    describe('NoOpLock behavior', () => {
      it('always acquires the lock', async () => {
        const lock = new NoOpLock();
        expect(await lock.acquire('key1')).toBe(true);
        expect(await lock.acquire('key1')).toBe(true); // Reentrant
        expect(await lock.acquire('key2')).toBe(true);
      });

      it('release does not throw', async () => {
        const lock = new NoOpLock();
        await expect(lock.release('any-key')).resolves.toBeUndefined();
      });
    });
  });

  describe('PersistenceBackend Interface', () => {
    const backends: { name: string; create: () => PersistenceBackend }[] = [
      { name: 'MemoryBackend', create: () => new MemoryBackend() },
      { name: 'LocalFileBackend', create: () => new LocalFileBackend('/tmp/test-checkpoints-compliance') },
    ];

    for (const { name, create } of backends) {
      describe(name, () => {
        let backend: PersistenceBackend;

        beforeEach(() => {
          backend = create();
        });

        it('has save method that returns Promise<void>', async () => {
          expect(typeof backend.save).toBe('function');
          const snapshot: MachineSnapshot = {
            execution_id: 'test-id',
            machine_name: 'test',
            spec_version: '0.4.0',
            current_state: 'test',
            context: {},
            step: 1,
            created_at: new Date().toISOString(),
          };
          const result = backend.save('key', snapshot);
          expect(result).toBeInstanceOf(Promise);
          await expect(result).resolves.toBeUndefined();
        });

        it('has load method that returns Promise<MachineSnapshot | null>', async () => {
          expect(typeof backend.load).toBe('function');
          const result = backend.load('nonexistent');
          expect(result).toBeInstanceOf(Promise);
          const value = await result;
          expect(value === null || typeof value === 'object').toBe(true);
        });

        it('has delete method that returns Promise<void>', async () => {
          expect(typeof backend.delete).toBe('function');
          const result = backend.delete('key');
          expect(result).toBeInstanceOf(Promise);
          await expect(result).resolves.toBeUndefined();
        });

        it('has list method that returns Promise<string[]>', async () => {
          expect(typeof backend.list).toBe('function');
          const result = backend.list('prefix');
          expect(result).toBeInstanceOf(Promise);
          const value = await result;
          expect(Array.isArray(value)).toBe(true);
        });
      });
    }
  });

  describe('ResultBackend Interface', () => {
    let backend: ResultBackend;

    beforeEach(() => {
      backend = inMemoryResultBackend;
    });

    it('has write method that returns Promise<void>', async () => {
      expect(typeof backend.write).toBe('function');
      const result = backend.write('test-uri', { data: 'test' });
      expect(result).toBeInstanceOf(Promise);
      await expect(result).resolves.toBeUndefined();
    });

    it('has read method that returns Promise<any>', async () => {
      expect(typeof backend.read).toBe('function');
      await backend.write('read-test', { value: 42 });
      const result = backend.read('read-test');
      expect(result).toBeInstanceOf(Promise);
    });

    it('has exists method that returns Promise<boolean>', async () => {
      expect(typeof backend.exists).toBe('function');
      const result = backend.exists('test-uri');
      expect(result).toBeInstanceOf(Promise);
      const value = await result;
      expect(typeof value).toBe('boolean');
    });

    it('has delete method that returns Promise<void>', async () => {
      expect(typeof backend.delete).toBe('function');
      const result = backend.delete('test-uri');
      expect(result).toBeInstanceOf(Promise);
      await expect(result).resolves.toBeUndefined();
    });
  });

  describe('ExecutionType Interface', () => {
    const executionTypes: { name: string; create: () => ExecutionType }[] = [
      { name: 'DefaultExecution', create: () => new DefaultExecution() },
      { name: 'RetryExecution', create: () => new RetryExecution([0.01, 0.01], 0) },
      { name: 'ParallelExecution', create: () => new ParallelExecution(2) },
      { name: 'MDAPVotingExecution', create: () => new MDAPVotingExecution(1, 3) },
    ];

    for (const { name, create } of executionTypes) {
      describe(name, () => {
        let execution: ExecutionType;

        beforeEach(() => {
          execution = create();
        });

        it('has execute method that returns Promise<T>', async () => {
          expect(typeof execution.execute).toBe('function');
          const result = execution.execute(async () => 'test-result');
          expect(result).toBeInstanceOf(Promise);
          const value = await result;
          // For some execution types, result may be wrapped
          expect(value !== undefined).toBe(true);
        });
      });
    }

    describe('DefaultExecution behavior', () => {
      it('calls function exactly once', async () => {
        const exec = new DefaultExecution();
        let calls = 0;
        await exec.execute(async () => { calls++; return 'done'; });
        expect(calls).toBe(1);
      });
    });
  });

  describe('LLMBackend Interface', () => {
    const backends: { name: string; create: () => LLMBackend }[] = [
      { name: 'MockLLMBackend', create: () => new MockLLMBackend() },
      // Note: VercelAIBackend requires real API credentials, skip in compliance tests
    ];

    for (const { name, create } of backends) {
      describe(name, () => {
        let backend: LLMBackend;

        beforeEach(() => {
          backend = create();
        });

        it('has totalCost property (number)', () => {
          expect(typeof backend.totalCost).toBe('number');
        });

        it('has totalApiCalls property (number)', () => {
          expect(typeof backend.totalApiCalls).toBe('number');
        });

        it('has call method that returns Promise<string>', async () => {
          expect(typeof backend.call).toBe('function');
          const result = backend.call([{ role: 'user', content: 'test' }]);
          expect(result).toBeInstanceOf(Promise);
          const value = await result;
          expect(typeof value).toBe('string');
        });

        it('has callRaw method that returns Promise<any>', async () => {
          expect(typeof backend.callRaw).toBe('function');
          const result = backend.callRaw([{ role: 'user', content: 'test' }]);
          expect(result).toBeInstanceOf(Promise);
        });
      });
    }

    describe('MockLLMBackend behavior', () => {
      it('returns configured responses', async () => {
        const backend = new MockLLMBackend([
          { content: '{"answer": "first"}' },
          { content: '{"answer": "second"}' },
        ]);

        expect(await backend.call([])).toBe('{"answer": "first"}');
        expect(await backend.call([])).toBe('{"answer": "second"}');
      });

      it('tracks API calls', async () => {
        const backend = new MockLLMBackend();
        expect(backend.totalApiCalls).toBe(0);

        await backend.call([]);
        expect(backend.totalApiCalls).toBe(1);

        await backend.call([]);
        expect(backend.totalApiCalls).toBe(2);
      });

      it('can be reset', async () => {
        const backend = new MockLLMBackend([
          { content: 'first' },
          { content: 'second' },
        ]);

        await backend.call([]);
        await backend.call([]);
        expect(backend.totalApiCalls).toBe(2);

        backend.reset();
        expect(backend.totalApiCalls).toBe(0);

        // Responses restart from beginning
        expect(await backend.call([])).toBe('first');
      });
    });
  });

  describe('VercelAIBackend Interface (structure only)', () => {
    // We can't test actual calls without API keys, but we can verify the class exists
    // and has the expected structure

    it('VercelAIBackend class exists', () => {
      expect(VercelAIBackend).toBeDefined();
      expect(typeof VercelAIBackend).toBe('function'); // Constructor
    });

    it('has correct prototype methods', () => {
      expect(typeof VercelAIBackend.prototype.call).toBe('function');
      expect(typeof VercelAIBackend.prototype.callRaw).toBe('function');
    });
  });
});

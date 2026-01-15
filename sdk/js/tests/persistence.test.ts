// persistence.test.ts
// Comprehensive unit tests for persistence functionality

import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { MemoryBackend, LocalFileBackend, CheckpointManager } from '../src/persistence';
import { MachineSnapshot } from '../src/types';

describe('MemoryBackend', () => {
  let backend: MemoryBackend;
  
  beforeEach(() => {
    backend = new MemoryBackend();
  });

  describe('Basic Operations', () => {
    it('should store and retrieve snapshots', async () => {
      const snapshot: MachineSnapshot = {
        executionId: 'test-123',
        machineName: 'test-machine',
        currentState: 'test-state',
        context: { 
          value: 42,
          nested: { data: 'test', count: 5 },
          array: [1, 2, 3]
        },
        step: 1,
        createdAt: '2023-01-01T00:00:00Z'
      };

      await backend.save('test-key', snapshot);
      const retrieved = await backend.load('test-key');
      expect(retrieved).toEqual(snapshot);
    });

    it('should return null for non-existent keys', async () => {
      const retrieved = await backend.load('non-existent-key');
      expect(retrieved).toBeNull();
    });

    it('should overwrite existing snapshots', async () => {
      const key = 'test-key';
      const originalSnapshot: MachineSnapshot = {
        executionId: 'test-123',
        machineName: 'test-machine',
        currentState: 'original-state',
        context: { value: 1 },
        step: 1,
        createdAt: '2023-01-01T00:00:00Z'
      };

      const updatedSnapshot: MachineSnapshot = {
        executionId: 'test-123',
        machineName: 'test-machine',
        currentState: 'updated-state',
        context: { value: 2 },
        step: 2,
        createdAt: '2023-01-01T00:00:00Z'
      };

      await backend.save(key, originalSnapshot);
      await backend.save(key, updatedSnapshot);
      
      const retrieved = await backend.load(key);
      expect(retrieved).toEqual(updatedSnapshot);
    });
  });

  describe('Listing and Prefix Operations', () => {
    it('should list snapshots by prefix', async () => {
      const snapshot: MachineSnapshot = {
        executionId: 'test-123',
        machineName: 'test-machine',
        currentState: 'test-state',
        context: { value: 42 },
        step: 1,
        createdAt: '2023-01-01T00:00:00Z'
      };

      await backend.save('execution-1/step_000001', snapshot);
      await backend.save('execution-1/step_000002', { ...snapshot, step: 2 });
      await backend.save('execution-2/step_000001', snapshot);
      await backend.save('execution-2/step_000002', { ...snapshot, step: 2 });
      await backend.save('other/item', snapshot);
      
      const exec1Keys = await backend.list('execution-1');
      const exec2Keys = await backend.list('execution-2');
      const allKeys = await backend.list('');
      
      expect(exec1Keys).toHaveLength(2);
      expect(exec1Keys).toContain('execution-1/step_000001');
      expect(exec1Keys).toContain('execution-1/step_000002');
      
      expect(exec2Keys).toHaveLength(2);
      expect(exec2Keys).toContain('execution-2/step_000001');
      expect(exec2Keys).toContain('execution-2/step_000002');
      
      expect(allKeys).toHaveLength(5);
    });

    it('should return empty array for non-existent prefixes', async () => {
      const keys = await backend.list('non-existent-prefix');
      expect(keys).toEqual([]);
    });

    it('should handle nested prefixes correctly', async () => {
      const snapshot: MachineSnapshot = {
        executionId: 'test-123',
        machineName: 'test-machine',
        currentState: 'test-state',
        context: { value: 42 },
        step: 1,
        createdAt: '2023-01-01T00:00:00Z'
      };

      await backend.save('a/b/c/d/item1', snapshot);
      await backend.save('a/b/c/e/item2', snapshot);
      await backend.save('a/b/f/item3', snapshot);
      
      const abcKeys = await backend.list('a/b/c');
      const abKeys = await backend.list('a/b');
      
      expect(abcKeys).toHaveLength(2);
      expect(abKeys).toHaveLength(3);
    });
  });

  describe('Deletion Operations', () => {
    it('should delete existing keys', async () => {
      const key = 'test-key';
      const snapshot: MachineSnapshot = {
        executionId: 'test-123',
        machineName: 'test-machine',
        currentState: 'test-state',
        context: { value: 42 },
        step: 1,
        createdAt: '2023-01-01T00:00:00Z'
      };

      await backend.save(key, snapshot);
      expect(await backend.load(key)).toEqual(snapshot);
      
      await backend.delete(key);
      expect(await backend.load(key)).toBeNull();
    });

    it('should handle deletion of non-existent keys gracefully', async () => {
      await expect(backend.delete('non-existent-key')).resolves.toBeUndefined();
    });
  });

  describe('Complex Data Handling', () => {
    it('should handle large context data', async () => {
      const largeArray = Array.from({ length: 1000 }, (_, i) => ({
        id: i,
        data: `item-${i}`.repeat(10),
        timestamp: Date.now() + i
      }));
      
      const snapshot: MachineSnapshot = {
        executionId: 'large-data-test',
        machineName: 'test-machine',
        currentState: 'processing-large-data',
        context: {
          largeArray,
          summary: {
            totalItems: largeArray.length,
            processed: 500,
            remaining: 500
          }
        },
        step: 1,
        createdAt: '2023-01-01T00:00:00Z'
      };

      await backend.save('large-data', snapshot);
      const retrieved = await backend.load('large-data');
      expect(retrieved).toEqual(snapshot);
      expect(retrieved?.context.largeArray).toHaveLength(1000);
    });

    it('should handle special characters in keys', async () => {
      const snapshot: MachineSnapshot = {
        executionId: 'test-123',
        machineName: 'test-machine',
        currentState: 'test-state',
        context: { value: 42 },
        step: 1,
        createdAt: '2023-01-01T00:00:00Z'
      };

      const specialKeys = [
        'test/checkpoint/with/slashes',
        'test-checkpoint.with.dots',
        'test_checkpoint_with_underscores',
        'test-checkpoint-with-dashes',
        'test.checkpoint?with=query&params=values',
        'test-checkpoint#with-hash',
        'test-checkpoint with spaces',
        '测试字符', // Chinese characters
        '🚀rocket-key'
      ];
      
      for (const key of specialKeys) {
        await backend.save(key, snapshot);
        const retrieved = await backend.load(key);
        expect(retrieved).toEqual(snapshot);
      }
      
      // Verify all keys are in the list
      const allKeys = await backend.list('');
      for (const key of specialKeys) {
        expect(allKeys).toContain(key);
      }
    });

    it('should handle unicode and special characters in data', async () => {
      const snapshot: MachineSnapshot = {
        executionId: 'unicode-test',
        machineName: 'test-machine',
        currentState: 'unicode-state',
        context: {
          specialChars: '🚀 💻 💾',
          unicode: 'Hello 世界 🌍',
          emojis: ['😀', '😎', '🤖', '🔧'],
          mathSymbols: '∑∏∫∆∇∂',
          currency: '€$¥£₹₽'
        },
        step: 1,
        createdAt: '2023-01-01T00:00:00Z'
      };

      await backend.save('unicode-data', snapshot);
      const retrieved = await backend.load('unicode-data');
      expect(retrieved).toEqual(snapshot);
    });
  });

  describe('Concurrent Operations', () => {
    it('should handle concurrent save operations', async () => {
      const concurrentSaves = 50;
      const baseSnapshot: MachineSnapshot = {
        executionId: 'concurrent-test',
        machineName: 'test-machine',
        currentState: 'test-state',
        context: { value: 42 },
        step: 1,
        createdAt: '2023-01-01T00:00:00Z'
      };

      const savePromises = Array.from({ length: concurrentSaves }, (_, i) =>
        backend.save(`concurrent-${i}`, { ...baseSnapshot, step: i + 1 })
      );

      await Promise.all(savePromises);

      // Verify all saves completed
      const allKeys = await backend.list('concurrent');
      expect(allKeys).toHaveLength(concurrentSaves);

      // Verify data integrity
      for (let i = 0; i < concurrentSaves; i++) {
        const retrieved = await backend.load(`concurrent-${i}`);
        expect(retrieved?.step).toBe(i + 1);
      }
    });

    it('should handle concurrent read and write operations', async () => {
      const snapshot: MachineSnapshot = {
        executionId: 'concurrent-rw-test',
        machineName: 'test-machine',
        currentState: 'test-state',
        context: { counter: 0 },
        step: 1,
        createdAt: '2023-01-01T00:00:00Z'
      };

      // Initialize
      await backend.save('rw-test', snapshot);

      // Test concurrent operations - split into separate arrays
      const readPromises: Promise<MachineSnapshot | null>[] = [];
      const writePromises: Promise<void>[] = [];
      
      // Read operations
      for (let i = 0; i < 10; i++) {
        readPromises.push(backend.load('rw-test'));
      }
      
      // Write operations
      for (let i = 0; i < 10; i++) {
        writePromises.push(backend.save('rw-test', { 
          ...snapshot, 
          context: { counter: i + 1 },
          step: i + 1 
        }));
      }

      // Execute reads and writes separately to avoid type issues
      await Promise.all(readPromises);
      await Promise.all(writePromises);

      // Final read
      const finalResult = await backend.load('rw-test');
      expect(finalResult?.context.counter).toBeGreaterThan(0);
    });
  });

  describe('Performance and Scale', () => {
    it('should handle large number of keys efficiently', async () => {
      const keyCount = 1000; // Reduced for test performance
      const snapshot: MachineSnapshot = {
        executionId: 'scale-test',
        machineName: 'test-machine',
        currentState: 'test-state',
        context: { value: 42 },
        step: 1,
        createdAt: '2023-01-01T00:00:00Z'
      };

      const startTime = Date.now();
      
      // Add many keys
      for (let i = 0; i < keyCount; i++) {
        await backend.save(`scale-${String(i).padStart(5, '0')}`, { 
          ...snapshot, 
          step: i + 1 
        });
      }
      
      const saveTime = Date.now() - startTime;
      console.log(`Saved ${keyCount} keys in ${saveTime}ms`);
      
      // Test listing performance
      const listStartTime = Date.now();
      const allKeys = await backend.list('');
      const listTime = Date.now() - listStartTime;
      
      expect(allKeys).toHaveLength(keyCount);
      expect(listTime).toBeLessThan(1000); // Should be reasonably fast
      
      console.log(`Listed ${allKeys.length} keys in ${listTime}ms`);
    });

    it('should handle prefix filtering on large datasets', async () => {
      const totalKeys = 500; // Reduced for test performance
      const prefixes = ['a', 'b', 'c', 'd', 'e'];
      const snapshot: MachineSnapshot = {
        executionId: 'prefix-test',
        machineName: 'test-machine',
        currentState: 'test-state',
        context: { value: 42 },
        step: 1,
        createdAt: '2023-01-01T00:00:00Z'
      };

      // Add keys with different prefixes
      for (let i = 0; i < totalKeys; i++) {
        const prefix = prefixes[i % prefixes.length];
        await backend.save(`${prefix}/item-${i}`, { ...snapshot, step: i });
      }
      
      // Test prefix filtering
      const startTime = Date.now();
      const aKeys = await backend.list('a');
      const filterTime = Date.now() - startTime;
      
      const expectedAKeys = Math.floor(totalKeys / prefixes.length);
      expect(aKeys).toHaveLength(expectedAKeys);
      expect(filterTime).toBeLessThan(100);
      
      console.log(`Filtered ${aKeys.length} keys in ${filterTime}ms`);
    });
  });
});

describe('LocalFileBackend', () => {
  let backend: LocalFileBackend;
  
  beforeEach(() => {
    backend = new LocalFileBackend();
  });

  it('should store and retrieve snapshots from files', async () => {
    const snapshot: MachineSnapshot = {
      executionId: 'file-test-123',
      machineName: 'file-test-machine',
      currentState: 'file-test-state',
      context: { 
        fileTest: true,
        nested: { path: '/tmp' }
      },
      step: 1,
      createdAt: '2023-01-01T00:00:00Z'
    };

    await backend.save('file-test-key', snapshot);
    const retrieved = await backend.load('file-test-key');
    expect(retrieved).toEqual(snapshot);
  });

  it('should handle non-existent files gracefully', async () => {
    const retrieved = await backend.load('non-existent-key');
    expect(retrieved).toBeNull();
  });

  it('should create and use custom directory', async () => {
    const customBackend = new LocalFileBackend('/tmp/custom-checkpoints');
    const snapshot: MachineSnapshot = {
      executionId: 'custom-dir-test',
      machineName: 'test-machine',
      currentState: 'test-state',
      context: { custom: true },
      step: 1,
      createdAt: '2023-01-01T00:00:00Z'
    };

    await customBackend.save('custom-test', snapshot);
    const retrieved = await customBackend.load('custom-test');
    expect(retrieved).toEqual(snapshot);
  });

  it('should handle file deletion', async () => {
    const snapshot: MachineSnapshot = {
      executionId: 'delete-test',
      machineName: 'test-machine',
      currentState: 'test-state',
      context: {},
      step: 1,
      createdAt: '2023-01-01T00:00:00Z'
    };

    await backend.save('delete-me', snapshot);
    expect(await backend.load('delete-me')).toEqual(snapshot);
    
    await backend.delete('delete-me');
    expect(await backend.load('delete-me')).toBeNull();
  });

  it('should handle deletion of non-existent files gracefully', async () => {
    await expect(backend.delete('non-existent-file')).resolves.toBeUndefined();
  });

  it('should list files in directory', async () => {
    const snapshot: MachineSnapshot = {
      executionId: 'list-test',
      machineName: 'test-machine',
      currentState: 'test-state',
      context: {},
      step: 1,
      createdAt: '2023-01-01T00:00:00Z'
    };

    await backend.save('list/item1', snapshot);
    await backend.save('list/item2', snapshot);
    await backend.save('other/item3', snapshot);
    
    const listKeys = await backend.list('list');
    const otherKeys = await backend.list('other');
    const allKeys = await backend.list('');
    
    expect(listKeys).toHaveLength(2);
    expect(listKeys).toContain('list/item1');
    expect(listKeys).toContain('list/item2');
    
    expect(otherKeys).toHaveLength(1);
    expect(otherKeys).toContain('other/item3');
    
    expect(allKeys).toHaveLength(3);
  });
});

describe('CheckpointManager', () => {
  let memoryBackend: MemoryBackend;
  let checkpointManager: CheckpointManager;
  
  beforeEach(() => {
    memoryBackend = new MemoryBackend();
    checkpointManager = new CheckpointManager(memoryBackend);
  });

  describe('Basic Checkpoint Operations', () => {
    it('should checkpoint and restore snapshots', async () => {
      const snapshot: MachineSnapshot = {
        executionId: 'test-execution',
        machineName: 'test-machine',
        currentState: 'test-state',
        context: { value: 42 },
        step: 1,
        createdAt: '2023-01-01T00:00:00Z'
      };

      await checkpointManager.checkpoint(snapshot);
      await checkpointManager.checkpoint({
        ...snapshot,
        step: 2,
        currentState: 'next-state',
        context: { value: 84 }
      });

      const restored = await checkpointManager.restore('test-execution');
      expect(restored?.step).toBe(2);
      expect(restored?.currentState).toBe('next-state');
      expect(restored?.context.value).toBe(84);
    });

    it('should return null for non-existent executions', async () => {
      const restored = await checkpointManager.restore('non-existent-execution');
      expect(restored).toBeNull();
    });

    it('should overwrite checkpoints for same execution', async () => {
      const executionId = 'overwrite-test';
      const snapshot1: MachineSnapshot = {
        executionId,
        machineName: 'test-machine',
        currentState: 'state1',
        context: { step: 1 },
        step: 1,
        createdAt: '2023-01-01T00:00:00Z'
      };

      const snapshot2: MachineSnapshot = {
        executionId,
        machineName: 'test-machine',
        currentState: 'state2',
        context: { step: 2 },
        step: 2,
        createdAt: '2023-01-01T00:00:00Z'
      };

      await checkpointManager.checkpoint(snapshot1);
      await checkpointManager.checkpoint(snapshot2);

      const restored = await checkpointManager.restore(executionId);
      expect(restored?.step).toBe(2);
      expect(restored?.currentState).toBe('state2');
    });

    it('should create proper step keys', async () => {
      const executionId = 'step-key-test';
      const snapshots = [];
      
      for (let step = 1; step <= 5; step++) {
        const snapshot: MachineSnapshot = {
          executionId,
          machineName: 'test-machine',
          currentState: `step-${step}`,
          context: { step },
          step,
          createdAt: '2023-01-01T00:00:00Z'
        };
        snapshots.push(snapshot);
        await checkpointManager.checkpoint(snapshot);
      }
      
      // Verify key format: executionId/step_XXXXXX
      const allKeys = await memoryBackend.list(executionId);
      expect(allKeys).toHaveLength(5);
      expect(allKeys).toContain(`${executionId}/step_000001`);
      expect(allKeys).toContain(`${executionId}/step_000005`);
      
      // Should restore latest (step 5)
      const restored = await checkpointManager.restore(executionId);
      expect(restored?.step).toBe(5);
    });

    it('should handle zero-padding in step numbers', async () => {
      const executionId = 'padding-test';
      const snapshot = {
        executionId,
        machineName: 'test-machine',
        currentState: 'test-state',
        context: {},
        step: 123,
        createdAt: '2023-01-01T00:00:00Z'
      };
      
      await checkpointManager.checkpoint(snapshot);
      
      const key = `${executionId}/step_000123`;
      const stored = await memoryBackend.load(key);
      expect(stored?.step).toBe(123);
    });
  });

  describe('Multi-Execution Support', () => {
    it('should handle multiple executions independently', async () => {
      const executions = ['exec1', 'exec2', 'exec3'];
      
      for (const execId of executions) {
        for (let step = 1; step <= 3; step++) {
          const snapshot: MachineSnapshot = {
            executionId: execId,
            machineName: 'test-machine',
            currentState: `${execId}-step-${step}`,
            context: { execId, step },
            step,
            createdAt: '2023-01-01T00:00:00Z'
          };
          await checkpointManager.checkpoint(snapshot);
        }
      }
      
      // Verify each execution restores its latest checkpoint
      for (const execId of executions) {
        const restored = await checkpointManager.restore(execId);
        expect(restored?.executionId).toBe(execId);
        expect(restored?.step).toBe(3);
        expect(restored?.context.execId).toBe(execId);
      }
    });

    it('should not interfere between executions', async () => {
      const snapshot1: MachineSnapshot = {
        executionId: 'execution-a',
        machineName: 'machine',
        currentState: 'state-a',
        context: { data: 'from-a' },
        step: 10,
        createdAt: '2023-01-01T00:00:00Z'
      };
      
      const snapshot2: MachineSnapshot = {
        executionId: 'execution-b',
        machineName: 'machine',
        currentState: 'state-b',
        context: { data: 'from-b' },
        step: 5,
        createdAt: '2023-01-01T00:00:00Z'
      };
      
      await checkpointManager.checkpoint(snapshot1);
      await checkpointManager.checkpoint(snapshot2);
      
      const restoredA = await checkpointManager.restore('execution-a');
      const restoredB = await checkpointManager.restore('execution-b');
      
      expect(restoredA?.context.data).toBe('from-a');
      expect(restoredB?.context.data).toBe('from-b');
    });
  });

  describe('Error Handling', () => {
    it('should handle invalid snapshot data gracefully', async () => {
      // Test missing required fields by creating invalid snapshots
      const invalidSnapshots = [
        { executionId: '', machineName: '', currentState: '', context: {}, step: -1, createdAt: 'invalid' },
        { executionId: 'test', machineName: 'test' } as MachineSnapshot // Missing other required fields
      ];

      for (const invalidSnapshot of invalidSnapshots) {
        await expect(
          checkpointManager.checkpoint(invalidSnapshot)
        ).rejects.toThrow();
      }
    });

    it('should handle backend failures gracefully', async () => {
      // Mock backend that fails
      const mockBackend = {
        save: vi.fn().mockRejectedValue(new Error('Backend failure')),
        load: vi.fn().mockRejectedValue(new Error('Backend failure')),
        list: vi.fn().mockRejectedValue(new Error('Backend failure')),
        delete: vi.fn().mockRejectedValue(new Error('Backend failure'))
      } as any;

      const errorManager = new CheckpointManager(mockBackend);
      const snapshot: MachineSnapshot = {
        executionId: 'error-test',
        machineName: 'test-machine',
        currentState: 'test-state',
        context: {},
        step: 1,
        createdAt: '2023-01-01T00:00:00Z'
      };

      await expect(errorManager.checkpoint(snapshot)).rejects.toThrow('Backend failure');
      await expect(errorManager.restore('test')).rejects.toThrow('Backend failure');
    });
  });

  describe('Performance and Concurrency', () => {
    it('should handle concurrent checkpoint operations', async () => {
      const executionCount = 10;
      const snapshotsPerExecution = 5;

      const checkpointPromises: Promise<void>[] = [];
      
      for (let exec = 1; exec <= executionCount; exec++) {
        for (let step = 1; step <= snapshotsPerExecution; step++) {
          const snapshot: MachineSnapshot = {
            executionId: `exec-${exec}`,
            machineName: 'test-machine',
            currentState: `state-${step}`,
            context: { exec, step },
            step,
            createdAt: `2023-01-01T00:${String(step).padStart(2, '0')}:00Z`
          };
          checkpointPromises.push(checkpointManager.checkpoint(snapshot));
        }
      }

      await Promise.all(checkpointPromises);

      // Verify all executions have latest checkpoints
      for (let exec = 1; exec <= executionCount; exec++) {
        const restored = await checkpointManager.restore(`exec-${exec}`);
        expect(restored?.step).toBe(snapshotsPerExecution); // Latest step
        expect(restored?.currentState).toBe(`state-${snapshotsPerExecution}`);
      }
    });

    it('should handle large context data efficiently', async () => {
      const largeContext = {
        items: Array.from({ length: 500 }, (_, i) => ({ // Reduced for test performance
          id: i,
          data: `data-${i}`.repeat(50)
        })),
        metadata: {
          total: 500,
          processed: 500,
          batchSize: 50
        }
      };

      const snapshot: MachineSnapshot = {
        executionId: 'large-context-test',
        machineName: 'test-machine',
        currentState: 'processing-complete',
        context: largeContext,
        step: 500,
        createdAt: '2023-01-01T00:00:00Z'
      };

      const startTime = Date.now();
      await checkpointManager.checkpoint(snapshot);
      const checkpointTime = Date.now() - startTime;

      const restoreStartTime = Date.now();
      const restored = await checkpointManager.restore('large-context-test');
      const restoreTime = Date.now() - restoreStartTime;

      expect(restored).toEqual(snapshot);
      expect(checkpointTime).toBeLessThan(1000); // Should be reasonably fast
      expect(restoreTime).toBeLessThan(1000);

      console.log(`Large context checkpoint: ${checkpointTime}ms, restore: ${restoreTime}ms`);
    });
  });
});

describe('Persistence Integration', () => {
  it('should work with different backend types', async () => {
    const snapshot: MachineSnapshot = {
      executionId: 'integration-test',
      machineName: 'test-machine',
      currentState: 'test-state',
      context: { integration: true },
      step: 1,
      createdAt: '2023-01-01T00:00:00Z'
    };

    // Test with memory backend
    const memoryManager = new CheckpointManager(new MemoryBackend());
    await memoryManager.checkpoint(snapshot);
    const memoryRestored = await memoryManager.restore('integration-test');
    expect(memoryRestored).toEqual(snapshot);

    // Test with file backend
    const fileManager = new CheckpointManager(new LocalFileBackend());
    await fileManager.checkpoint(snapshot);
    const fileRestored = await fileManager.restore('integration-test');
    expect(fileRestored).toEqual(snapshot);
  });

  it('should handle complex workflows with nested execution contexts', async () => {
    const parentSnapshot: MachineSnapshot = {
      executionId: 'parent-execution',
      machineName: 'parent-machine',
      currentState: 'parent-state',
      context: {
        parentData: 'parent-value',
        childExecutions: ['child-1', 'child-2']
      },
      step: 1,
      createdAt: '2023-01-01T00:00:00Z',
      parentExecutionId: 'root-execution'
    };

    const childSnapshot: MachineSnapshot = {
      executionId: 'child-execution',
      machineName: 'child-machine',
      currentState: 'child-state',
      context: {
        childData: 'child-value',
        parentRef: 'parent-execution'
      },
      step: 1,
      createdAt: '2023-01-01T00:00:00Z',
      parentExecutionId: 'parent-execution'
    };

    const manager = new CheckpointManager(new MemoryBackend());
    
    await manager.checkpoint(parentSnapshot);
    await manager.checkpoint(childSnapshot);

    const restoredParent = await manager.restore('parent-execution');
    const restoredChild = await manager.restore('child-execution');

    expect(restoredParent?.parentExecutionId).toBe('root-execution');
    expect(restoredChild?.parentExecutionId).toBe('parent-execution');
    
    // Verify nested execution contexts are preserved
    expect(restoredParent?.context.childExecutions).toEqual(['child-1', 'child-2']);
    expect(restoredChild?.context.parentRef).toBe('parent-execution');
  });
});
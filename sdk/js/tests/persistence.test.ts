import { test, expect } from 'vitest';
import { MemoryBackend, LocalFileBackend, CheckpointManager } from '../src/persistence';
import { MachineSnapshot } from '../src/types';

test('MemoryBackend stores and retrieves snapshots', async () => {
  const backend = new MemoryBackend();
  const snapshot: MachineSnapshot = {
    executionId: 'test-123',
    machineName: 'test-machine',
    currentState: 'test-state',
    context: { value: 42 },
    step: 1,
    createdAt: '2023-01-01T00:00:00Z'
  };

  await backend.save('test-key', snapshot);
  const retrieved = await backend.load('test-key');
  expect(retrieved).toEqual(snapshot);
});

test('MemoryBackend lists snapshots by prefix', async () => {
  const backend = new MemoryBackend();
  const snapshot: MachineSnapshot = {
    executionId: 'test-123',
    machineName: 'test-machine',
    currentState: 'test-state',
    context: { value: 42 },
    step: 1,
    createdAt: '2023-01-01T00:00:00Z'
  };

  await backend.save('execution-1/step_000001', snapshot);
  await backend.save('execution-2/step_000001', snapshot);
  
  const keys = await backend.list('execution-1');
  expect(keys).toEqual(['execution-1/step_000001']);
});

test('CheckpointManager checkpoints and restores', async () => {
  const memoryBackend = new MemoryBackend();
  const checkpointManager = new CheckpointManager(memoryBackend);
  
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
    currentState: 'next-state'
  });

  const restored = await checkpointManager.restore('test-execution');
  expect(restored?.step).toBe(2);
  expect(restored?.currentState).toBe('next-state');
});
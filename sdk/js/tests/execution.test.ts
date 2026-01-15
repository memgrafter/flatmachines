import { test, expect } from 'vitest';
import { DefaultExecution, RetryExecution, getExecutionType } from '../src/execution';

test('DefaultExecution executes function', async () => {
  const execution = new DefaultExecution();
  const result = await execution.execute(() => Promise.resolve('success'));
  expect(result).toBe('success');
});

test('RetryExecution retries on failure', async () => {
  let attempts = 0;
  const execution = new RetryExecution([0.01, 0.01]); // Short delays for testing
  
  try {
    await execution.execute(() => {
      attempts++;
      if (attempts < 3) {
        throw new Error('Fail');
      }
      return Promise.resolve('success');
    });
    expect(attempts).toBe(3);
  } catch (error) {
    expect(false).toBe(true); // Should not reach here
  }
});

test('RetryExecution fails after max attempts', async () => {
  const execution = new RetryExecution([0.01]); // One retry attempt
  
  try {
    await execution.execute(() => {
      throw new Error('Always fails');
    });
    expect(false).toBe(true); // Should not reach here
  } catch (error) {
    expect(error.message).toBe('Always fails');
  }
});

test('getExecutionType returns correct type', () => {
  const defaultExec = getExecutionType();
  expect(defaultExec).toBeInstanceOf(DefaultExecution);
  
  const retryExec = getExecutionType({ type: 'retry', backoffs: [1, 2, 3] });
  expect(retryExec).toBeInstanceOf(RetryExecution);
});
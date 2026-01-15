import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { DefaultExecution, RetryExecution, getExecutionType } from '../src/execution';

describe('DefaultExecution', () => {
  describe('Basic Execution', () => {
    it('should execute function successfully', async () => {
      const execution = new DefaultExecution();
      const result = await execution.execute(() => Promise.resolve('success'));
      expect(result).toBe('success');
    });

    it('should handle synchronous functions', async () => {
      const execution = new DefaultExecution();
      const result = await execution.execute(() => 'sync result');
      expect(result).toBe('sync result');
    });

    it('should handle different return types', async () => {
      const execution = new DefaultExecution();
      
      const stringResult = await execution.execute(() => Promise.resolve('string'));
      expect(stringResult).toBe('string');
      
      const numberResult = await execution.execute(() => Promise.resolve(42));
      expect(numberResult).toBe(42);
      
      const boolResult = await execution.execute(() => Promise.resolve(true));
      expect(boolResult).toBe(true);
      
      const objectResult = await execution.execute(() => Promise.resolve({ key: 'value' }));
      expect(objectResult).toEqual({ key: 'value' });
      
      const arrayResult = await execution.execute(() => Promise.resolve([1, 2, 3]));
      expect(arrayResult).toEqual([1, 2, 3]);
    });

    it('should handle null and undefined returns', async () => {
      const execution = new DefaultExecution();
      
      const nullResult = await execution.execute(() => Promise.resolve(null));
      expect(nullResult).toBe(null);
      
      const undefinedResult = await execution.execute(() => Promise.resolve(undefined));
      expect(undefinedResult).toBe(undefined);
    });
  });

  describe('Error Handling', () => {
    it('should propagate errors without retrying', async () => {
      const execution = new DefaultExecution();
      const error = new Error('Test error');
      
      await expect(execution.execute(() => Promise.reject(error))).rejects.toThrow('Test error');
    });

    it('should handle different error types', async () => {
      const execution = new DefaultExecution();
      
      await expect(execution.execute(() => Promise.reject(new Error('Regular error')))).rejects.toThrow();
      await expect(execution.execute(() => Promise.reject(new TypeError('Type error')))).rejects.toThrow(TypeError);
      await expect(execution.execute(() => Promise.reject(new RangeError('Range error')))).rejects.toThrow(RangeError);
    });

    it('should handle thrown errors', async () => {
      const execution = new DefaultExecution();
      
      await expect(execution.execute(() => {
        throw new Error('Thrown error');
      })).rejects.toThrow('Thrown error');
    });

    it('should handle custom error objects', async () => {
      const execution = new DefaultExecution();
      const customError = new Error('Custom error');
      customError.name = 'CustomError';
      
      await expect(execution.execute(() => Promise.reject(customError))).rejects.toThrow('Custom error');
    });
  });

  describe('Performance and Load', () => {
    it('should handle multiple concurrent executions', async () => {
      const execution = new DefaultExecution();
      const operations = [];
      
      for (let i = 0; i < 100; i++) {
        operations.push(execution.execute(() => Promise.resolve(i)));
      }
      
      const results = await Promise.all(operations);
      results.forEach((result, index) => {
        expect(result).toBe(index);
      });
    });

    it('should handle long-running functions', async () => {
      const execution = new DefaultExecution();
      const startTime = Date.now();
      
      const result = await execution.execute(async () => {
        await new Promise(resolve => setTimeout(resolve, 100));
        return 'completed';
      });
      
      const duration = Date.now() - startTime;
      expect(result).toBe('completed');
      expect(duration).toBeGreaterThan(90);
    });

    it('should handle large payloads', async () => {
      const execution = new DefaultExecution();
      const largeData = {
        array: Array.from({ length: 10000 }, (_, i) => ({ id: i, value: `item_${i}` })),
        text: 'x'.repeat(50000),
        nested: { data: 'large payload' }
      };
      
      const result = await execution.execute(() => Promise.resolve(largeData));
      expect(result).toEqual(largeData);
      expect(result.array).toHaveLength(10000);
    });
  });
});

describe('RetryExecution', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  describe('Basic Retry Logic', () => {
    it('should retry on failure and succeed', async () => {
      let attempts = 0;
      const execution = new RetryExecution([0.01, 0.01]); // Short delays for testing
      
      const result = await execution.execute(() => {
        attempts++;
        if (attempts < 3) {
          throw new Error('Fail');
        }
        return Promise.resolve('success');
      });
      
      expect(attempts).toBe(3);
      expect(result).toBe('success');
    });

    it('should fail after exhausting retries', async () => {
      const execution = new RetryExecution([0.01]); // One retry attempt
      
      await expect(execution.execute(() => {
        throw new Error('Always fails');
      })).rejects.toThrow('Always fails');
    });

    it('should succeed on first attempt', async () => {
      let attempts = 0;
      const execution = new RetryExecution([0.01, 0.01, 0.01]);
      
      const result = await execution.execute(() => {
        attempts++;
        return Promise.resolve('first try success');
      });
      
      expect(attempts).toBe(1);
      expect(result).toBe('first try success');
    });

    it('should succeed on last possible retry', async () => {
      let attempts = 0;
      const execution = new RetryExecution([0.01, 0.01]); // 2 backoffs = 3 total attempts
      
      const result = await execution.execute(() => {
        attempts++;
        if (attempts < 3) {
          throw new Error(`Attempt ${attempts} failed`);
        }
        return Promise.resolve('last attempt success');
      });
      
      expect(attempts).toBe(3);
      expect(result).toBe('last attempt success');
    });
  });

  describe('Backoff and Jitter', () => {
    it('should apply backoff delays between retries', async () => {
      let attempts = 0;
      const execution = new RetryExecution([0.1, 0.2], 0); // No jitter
      
      const resultPromise = execution.execute(() => {
        attempts++;
        if (attempts < 3) {
          throw new Error('Fail');
        }
        return Promise.resolve('success');
      });
      
      // Let first attempt fail
      await vi.advanceTimersByTime(50);
      expect(await vi.isPending(resultPromise)).toBe(true);
      
      // Advance by first backoff
      await vi.advanceTimersByTime(50); // Total: 100ms
      await advanceTimerAndAwait(resultPromise);
      
      const result = await resultPromise;
      expect(result).toBe('success');
    });

    it('should apply jitter to delays', async () => {
      vi.spyOn(Math, 'random').mockReturnValue(0.5); // 50% random
      
      let attempts = 0;
      const execution = new RetryExecution([1, 2], 0.1); // ±10% jitter
      
      const resultPromise = execution.execute(() => {
        attempts++;
        if (attempts < 3) {
          throw new Error('Fail');
        }
        return Promise.resolve('success');
      });
      
      // First attempt fails, wait for retry
      await vi.advanceTimersByTime(1000);
      
      // Second attempt fails, wait for retry with jitter
      await vi.advanceTimersByTime(2000);
      
      const result = await resultPromise;
      expect(result).toBe('success');
      
      vi.restoreAllMocks();
    });

    it('should handle zero jitter', async () => {
      vi.spyOn(Math, 'random').mockReturnValue(0);
      
      let attempts = 0;
      const execution = new RetryExecution([0.05], 0);
      
      await execution.execute(() => {
        attempts++;
        if (attempts < 2) {
          throw new Error('Fail');
        }
        return Promise.resolve('success');
      });
      
      expect(attempts).toBe(2);
      vi.restoreAllMocks();
    });
  });

  describe('Error Type Handling', () => {
    it('should retry on different error types', async () => {
      let attempts = 0;
      const execution = new RetryExecution([0.01, 0.01]);
      
      const result = await execution.execute(() => {
        attempts++;
        if (attempts < 2) {
          if (attempts === 1) {
            throw new TypeError('Type error');
          } else {
            throw new RangeError('Range error');
          }
        }
        return Promise.resolve('success');
      });
      
      expect(attempts).toBe(2);
      expect(result).toBe('success');
    });

    it('should propagate the last error after retries exhausted', async () => {
      let attempts = 0;
      const execution = new RetryExecution([0.01, 0.01]);
      
      try {
        await execution.execute(() => {
          attempts++;
          throw new Error(`Attempt ${attempts} error`);
        });
      } catch (error) {
        expect(error.message).toBe('Attempt 3 error');
        expect(attempts).toBe(3);
      }
    });

    it('should handle custom error properties', async () => {
      const execution = new RetryExecution([0.01]);
      const customError = new Error('Custom') as any;
      customError.code = 'CUSTOM_ERROR';
      customError.statusCode = 500;
      
      try {
        await execution.execute(() => {
          throw customError;
        });
      } catch (error) {
        expect(error.code).toBe('CUSTOM_ERROR');
        expect(error.statusCode).toBe(500);
      }
    });
  });

  describe('Complex Retry Scenarios', () => {
    it('should handle intermittent failures', async () => {
      let attempts = 0;
      const execution = new RetryExecution([0.01, 0.01, 0.01, 0.01]);
      
      const result = await execution.execute(() => {
        attempts++;
        // Fail on attempts 1, 2, and 4, succeed on 3
        if (attempts === 1 || attempts === 2 || attempts === 4) {
          throw new Error(`Intermittent failure ${attempts}`);
        }
        return Promise.resolve(`Success on attempt ${attempts}`);
      });
      
      expect(attempts).toBe(3);
      expect(result).toBe('Success on attempt 3');
    });

    it('should handle functions that throw promises', async () => {
      let attempts = 0;
      const execution = new RetryExecution([0.01, 0.01]);
      
      const result = await execution.execute(() => {
        attempts++;
        if (attempts < 2) {
          return Promise.reject(new Error('Promise rejection'));
        }
        return Promise.resolve('Promise success');
      });
      
      expect(attempts).toBe(2);
      expect(result).toBe('Promise success');
    });

    it('should handle async functions directly', async () => {
      let attempts = 0;
      const execution = new RetryExecution([0.01]);
      
      const result = await execution.execute(async () => {
        attempts++;
        if (attempts < 2) {
          throw new Error('Async function failure');
        }
        return 'Async function success';
      });
      
      expect(attempts).toBe(2);
      expect(result).toBe('Async function success');
    });
  });

  describe('Performance and Load', () => {
    it('should handle concurrent retry executions', async () => {
      const execution = new RetryExecution([0.01]);
      const operations = [];
      
      for (let i = 0; i < 10; i++) {
        operations.push(execution.execute(() => Promise.resolve(`success ${i}`)));
      }
      
      const results = await Promise.all(operations);
      results.forEach((result, index) => {
        expect(result).toBe(`success ${index}`);
      });
    });

    it('should handle many retries efficiently', async () => {
      let attempts = 0;
      const execution = new RetryExecution(Array.from({ length: 10 }, () => 0.01));
      
      const result = await execution.execute(() => {
        attempts++;
        if (attempts < 5) { // Succeed on 5th attempt
          throw new Error(`Attempt ${attempts}`);
        }
        return Promise.resolve('success after 5 attempts');
      });
      
      expect(attempts).toBe(5);
      expect(result).toBe('success after 5 attempts');
    });

    it('should handle long backoff periods', async () => {
      let attempts = 0;
      const execution = new RetryExecution([1, 2, 4]); // Long delays for testing
      
      const resultPromise = execution.execute(() => {
        attempts++;
        if (attempts < 2) {
          throw new Error('Fail');
        }
        return Promise.resolve('success');
      });
      
      // Advance through first backoff
      await vi.advanceTimersByTime(1000);
      await advanceTimerAndAwait(resultPromise);
      
      const result = await resultPromise;
      expect(result).toBe('success');
    });
  });

  describe('Edge Cases', () => {
    it('should handle empty backoff array', async () => {
      let attempts = 0;
      const execution = new RetryExecution([]);
      
      try {
        await execution.execute(() => {
          attempts++;
          if (attempts < 2) {
            throw new Error('Should retry');
          }
          return Promise.resolve('success');
        });
      } catch (error) {
        expect(attempts).toBe(1);
        expect(error.message).toBe('Should retry');
      }
    });

    it('should handle single backoff value', async () => {
      let attempts = 0;
      const execution = new RetryExecution([0.01]);
      
      const result = await execution.execute(() => {
        attempts++;
        if (attempts < 2) {
          throw new Error('First attempt fails');
        }
        return Promise.resolve('success on second try');
      });
      
      expect(attempts).toBe(2);
      expect(result).toBe('success on second try');
    });

    it('should handle very small backoff values', async () => {
      let attempts = 0;
      const execution = new RetryExecution([0.001, 0.001, 0.001]);
      
      const result = await execution.execute(() => {
        attempts++;
        if (attempts < 3) {
          throw new Error(`Micro retry ${attempts}`);
        }
        return Promise.resolve('micro success');
      });
      
      expect(attempts).toBe(3);
      expect(result).toBe('micro success');
    });
  });
});

describe('getExecutionType', () => {
  describe('Default Execution Type', () => {
    it('should return DefaultExecution when no config provided', () => {
      const executionType = getExecutionType();
      expect(executionType).toBeInstanceOf(DefaultExecution);
    });

    it('should return DefaultExecution when config type is default', () => {
      const executionType = getExecutionType({ type: 'default' });
      expect(executionType).toBeInstanceOf(DefaultExecution);
    });

    it('should handle undefined config', () => {
      const executionType = getExecutionType(undefined);
      expect(executionType).toBeInstanceOf(DefaultExecution);
    });
  });

  describe('Retry Execution Type', () => {
    it('should return RetryExecution with default parameters', () => {
      const executionType = getExecutionType({ type: 'retry' });
      expect(executionType).toBeInstanceOf(RetryExecution);
    });

    it('should return RetryExecution with custom backoffs', () => {
      const backoffs = [1, 5, 10, 30];
      const executionType = getExecutionType({ type: 'retry', backoffs });
      expect(executionType).toBeInstanceOf(RetryExecution);
    });

    it('should return RetryExecution with custom jitter', () => {
      const jitter = 0.2;
      const executionType = getExecutionType({ type: 'retry', jitter });
      expect(executionType).toBeInstanceOf(RetryExecution);
    });

    it('should return RetryExecution with all custom parameters', () => {
      const config = {
        type: 'retry' as const,
        backoffs: [2, 4, 8, 16],
        jitter: 0.15
      };
      const executionType = getExecutionType(config);
      expect(executionType).toBeInstanceOf(RetryExecution);
    });

    it('should handle empty backoffs array in retry config', () => {
      const executionType = getExecutionType({ type: 'retry', backoffs: [] });
      expect(executionType).toBeInstanceOf(RetryExecution);
    });
  });

  describe('Configuration Validation', () => {
    it('should handle malformed config gracefully', () => {
      const invalidConfigs = [
        null,
        undefined,
        {},
        { type: 'invalid' },
        { type: 'retry', backoffs: null },
        { type: 'retry', jitter: -1 },
        { type: 'retry', backoffs: [-1, 2, 3] }
      ];
      
      invalidConfigs.forEach(config => {
        expect(() => getExecutionType(config as any)).not.toThrow();
      });
    });

    it('should handle partial config objects', () => {
      const partialConfigs = [
        { type: 'retry' },
        { type: 'retry', backoffs: [1, 2] },
        { type: 'retry', jitter: 0.1 },
        { type: 'default' }
      ];
      
      partialConfigs.forEach(config => {
        expect(() => getExecutionType(config as any)).not.toThrow();
      });
    });
  });

  describe('Instance Independence', () => {
    it('should return new instances each call', () => {
      const executionType1 = getExecutionType({ type: 'retry', backoffs: [1, 2] });
      const executionType2 = getExecutionType({ type: 'retry', backoffs: [1, 2] });
      
      expect(executionType1).not.toBe(executionType2);
      expect(executionType1).toBeInstanceOf(RetryExecution);
      expect(executionType2).toBeInstanceOf(RetryExecution);
    });

    it('should handle different configs returning different behaviors', async () => {
      const retry1 = getExecutionType({ type: 'retry', backoffs: [0.01] });
      const retry2 = getExecutionType({ type: 'retry', backoffs: [0.01, 0.01] });
      
      let attempts1 = 0;
      let attempts2 = 0;
      
      // First fails after 1 retry
      try {
        await retry1.execute(() => {
          attempts1++;
          throw new Error('Fail');
        });
      } catch (error) {
        expect(attempts1).toBe(2);
      }
      
      // Second fails after 2 retries
      try {
        await retry2.execute(() => {
          attempts2++;
          throw new Error('Fail');
        });
      } catch (error) {
        expect(attempts2).toBe(3);
      }
    });
  });
});

// Helper function to advance timers and wait for promise resolution
async function advanceTimerAndAwait<T>(promise: Promise<T>): Promise<void> {
  await vi.runAllTimersAsync();
  // Small delay to ensure promise chain completes
  await new Promise(resolve => setTimeout(resolve, 0));
}
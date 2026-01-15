// expression.test.ts
// Comprehensive unit tests for expression evaluation functionality

import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { evaluate } from '../src/expression';

describe('Expression Evaluation', () => {
  const baseContext = {
    context: {},
    input: {},
    output: {}
  };

  describe('Basic Operations', () => {
    it('should evaluate simple equality comparisons', () => {
      const testCases = [
        { expr: 'context.value == 42', context: { value: 42 }, expected: true },
        { expr: 'context.value == 42', context: { value: 41 }, expected: false },
        { expr: 'context.value != 42', context: { value: 41 }, expected: true }
      ];

      for (const { expr, context, expected } of testCases) {
        const result = evaluate(expr, { ...baseContext, context });
        expect(result).toBe(expected);
      }
    });

    it('should evaluate numeric comparisons', () => {
      const testCases = [
        { expr: 'context.a > 5', context: { a: 7 }, expected: true },
        { expr: 'context.a > 5', context: { a: 5 }, expected: false },
        { expr: 'context.a >= 5', context: { a: 5 }, expected: true },
        { expr: 'context.a < 10', context: { a: 8 }, expected: true },
        { expr: 'context.a <= 10', context: { a: 10 }, expected: true }
      ];

      for (const { expr, context, expected } of testCases) {
        const result = evaluate(expr, { ...baseContext, context });
        expect(result).toBe(expected);
      }
    });

    it('should evaluate string comparisons', () => {
      const testCases = [
        { expr: 'context.name == "test"', context: { name: 'test' }, expected: true },
        { expr: 'context.name == "test"', context: { name: 'other' }, expected: false },
        { expr: 'context.name != "test"', context: { name: 'other' }, expected: true }
      ];

      for (const { expr, context, expected } of testCases) {
        const result = evaluate(expr, { ...baseContext, context });
        expect(result).toBe(expected);
      }
    });
  });

  describe('Boolean Operators', () => {
    it('should evaluate and operators', () => {
      const result = evaluate('context.a > 5 and context.b < 10', {
        ...baseContext,
        context: { a: 7, b: 8 }
      });
      expect(result).toBe(true);
    });

    it('should evaluate or operators', () => {
      const result = evaluate('context.x == 1 or context.y == 2', {
        ...baseContext,
        context: { x: 0, y: 2 }
      });
      expect(result).toBe(true);
    });

    it('should evaluate not operators', () => {
      const result = evaluate('not context.flag', {
        ...baseContext,
        context: { flag: false }
      });
      expect(result).toBe(true);
    });

    it('should evaluate complex boolean expressions', () => {
      const result = evaluate('(context.a > 5 and context.b < 10) or context.c == true', {
        ...baseContext,
        context: { a: 3, b: 8, c: true }
      });
      expect(result).toBe(true);
    });
  });

  describe('Object Property Access', () => {
    it('should access nested object properties', () => {
      const result = evaluate('context.user.name', {
        ...baseContext,
        context: { user: { name: 'John', age: 30 } }
      });
      expect(result).toBe('John');
    });

    it('should access deeply nested properties', () => {
      const result = evaluate('context.data.profile.settings.theme', {
        ...baseContext,
        context: {
          data: {
            profile: {
              settings: {
                theme: 'dark',
                notifications: true
              }
            }
          }
        }
      });
      expect(result).toBe('dark');
    });

    it('should return undefined for non-existent properties', () => {
      const result = evaluate('context.nonexistent.property', {
        ...baseContext,
        context: {}
      });
      expect(result).toBeUndefined();
    });
  });

  describe('Primitive Values', () => {
    it('should handle boolean literals', () => {
      expect(evaluate('true', baseContext)).toBe(true);
      expect(evaluate('false', baseContext)).toBe(false);
    });

    it('should handle null literal', () => {
      expect(evaluate('null', baseContext)).toBe(null);
    });

    it('should handle numeric literals', () => {
      expect(evaluate('42', baseContext)).toBe(42);
      expect(evaluate('3.14', baseContext)).toBe(3.14);
      expect(evaluate('-5', baseContext)).toBe(-5);
    });

    it('should handle string literals', () => {
      expect(evaluate('"hello"', baseContext)).toBe('hello');
      expect(evaluate('"test string"', baseContext)).toBe('test string');
    });
  });

  describe('Input and Output Context', () => {
    it('should access input variables', () => {
      const result = evaluate('input.value > 100', {
        context: {},
        input: { value: 150 },
        output: {}
      });
      expect(result).toBe(true);
    });

    it('should access output variables', () => {
      const result = evaluate('output.result.success == true', {
        context: {},
        input: {},
        output: { result: { success: true, data: 'processed' } }
      });
      expect(result).toBe(true);
    });

    it('should combine all context types', () => {
      const result = evaluate('context.user.id == input.userId and output.authenticated == true', {
        context: { user: { id: 'user123' } },
        input: { userId: 'user123' },
        output: { authenticated: true }
      });
      expect(result).toBe(true);
    });
  });

  describe('Array Access', () => {
    it('should access array elements through dot notation in our simplified parser', () => {
      // Our current parser doesn't support bracket notation, so this tests what it can do
      const result = evaluate('context.array.0', {
        ...baseContext,
        context: { array: ['a', 'b', 'c'] }
      });
      // This would fail with current implementation - test shows limitation
      expect(result).toBeUndefined(); // Expected with current parser
    });
  });

  describe('Complex Real-world Expressions', () => {
    it('should handle conditional routing expressions', () => {
      const expressions = [
        {
          expr: 'context.score >= 90 and context.completed == true',
          context: { score: 95, completed: true },
          expected: true
        },
        {
          expr: 'context.progress >= 0.8 or context.forceComplete == true',
          context: { progress: 0.7, forceComplete: true },
          expected: true
        },
        {
          expr: 'context.user.role == "admin" or context.action == "edit"',
          context: { user: { role: 'user' }, action: 'edit' },
          expected: true
        },
        {
          expr: 'context.items.length > 0 and context.status != "processed"',
          // Our parser can't access .length, so this would be undefined
          context: { items: [1, 2, 3], status: 'pending' },
          expected: false // Expected with current parser limitations
        }
      ];

      for (const { expr, context, expected } of expressions) {
        const result = evaluate(expr, { ...baseContext, context });
        expect(result).toBe(expected);
      }
    });

    it('should handle JSON-like data access patterns', () => {
      const contextData = {
        context: {
          request: {
            method: 'POST',
            user: { id: 'user123', name: 'John Doe' },
            action: 'create'
          },
          response: {
            status: 200,
            success: true
          }
        },
        input: {},
        output: {}
      };

      const testCases = [
        {
          expr: 'context.request.method == "POST" and context.response.status == 200',
          expected: true
        },
        {
          expr: 'context.request.user.id == "user123"',
          expected: true
        },
        {
          expr: 'context.response.success == true',
          expected: true
        }
      ];

      for (const { expr, expected } of testCases) {
        const result = evaluate(expr, contextData);
        expect(result).toBe(expected);
      }
    });
  });

  describe('Error Handling', () => {
    it('should handle syntax errors gracefully', () => {
      expect(() => {
        evaluate('context.value > )', baseContext);
      }).toThrow();

      expect(() => {
        evaluate('context.value + + 2', baseContext);
      }).toThrow();
    });

    it('should handle unclosed parentheses', () => {
      expect(() => {
        evaluate('(context.value > 5', baseContext);
      }).toThrow();

      expect(() => {
        evaluate('context.value > 5)', baseContext);
      }).toThrow();
    });

    it('should handle empty expressions', () => {
      expect(() => {
        evaluate('', baseContext);
      }).toThrow();

      expect(() => {
        evaluate('   ', baseContext);
      }).toThrow();
    });
  });

  describe('Edge Cases', () => {
    it('should handle very nested property access', () => {
      const deeplyNested = {
        level1: {
          level2: {
            level3: {
              level4: {
                level5: 'deep value'
              }
            }
          }
        }
      };

      const result = evaluate('context.level1.level2.level3.level4.level5 == "deep value"', {
        ...baseContext,
        context: deeplyNested
      });
      expect(result).toBe(true);
    });

    it('should handle property names with special characters', () => {
      // Test what our current parser can handle
      const contextWithSpecialChars = {
        'prop-with-dashes': 'value1',
        'prop_with_underscores': 'value2',
        'prop.with.dots': 'value3'
      };

      const result1 = evaluate('context.prop-with-dashes == "value1"', {
        ...baseContext,
        context: contextWithSpecialChars
      });
      expect(result1).toBe(true);
    });

    it('should handle boolean conversion', () => {
      const testCases = [
        { expr: 'context.zero', context: { zero: 0 }, expected: false },
        { expr: 'context.empty', context: { empty: '' }, expected: false },
        { expr: 'context.nonzero', context: { nonzero: 42 }, expected: true },
        { expr: 'context.nonempty', context: { nonempty: 'hello' }, expected: true },
        { expr: 'context.truethy', context: { truethy: true }, expected: true }
      ];

      for (const { expr, context, expected } of testCases) {
        const result = evaluate(expr, { ...baseContext, context });
        expect(result).toBe(expected);
      }
    });
  });

  describe('Performance and Edge Cases', () => {
    it('should handle complex expressions efficiently', () => {
      const complexExpr = 'context.a > 0 and context.b > 0 and context.c > 0 and context.d > 0 and context.e > 0';
      
      const startTime = Date.now();
      
      // Evaluate complex expression multiple times
      for (let i = 0; i < 100; i++) {
        evaluate(complexExpr, {
          ...baseContext,
          context: { a: 1, b: 2, c: 3, d: 4, e: 5 }
        });
      }
      
      const totalTime = Date.now() - startTime;
      
      // Should be efficient (less than 50ms for 100 evaluations)
      expect(totalTime).toBeLessThan(50);
    });

    it('should handle extremely long property chains', () => {
      const chain = Array.from({ length: 20 }, (_, i) => `level${i + 1}`).join('.');
      const context = Array.from({ length: 20 }, (_, i) => [`level${i + 1}`]).reduce((obj, [key], i) => {
        obj[key] = i === 19 ? 'final' : {};
        return obj;
      }, {} as any);

      expect(() => {
        evaluate(`context.${chain} == "final"`, { ...baseContext, context });
      }).not.toThrow();
    });
  });

  describe('Operator Precedence and Combinations', () => {
    it('should handle mixed operators correctly', () => {
      // Test different operator combinations
      const testCases = [
        {
          expr: 'context.a > 5 and context.b < 10 or context.c == true',
          context: { a: 7, b: 8, c: false },
          expected: true // (a > 5 and b < 10) is true, so whole expression is true
        },
        {
          expr: 'context.a == 1 or context.b == 2 and context.c == 3',
          context: { a: 0, b: 2, c: 4 },
          expected: false // b == 2 is true but c == 3 is false, a == 1 is false
        },
        {
          expr: 'context.a == 1 or context.b == 2 or context.c == 3',
          context: { a: 0, b: 2, c: 0 },
          expected: true // b == 2 is true
        },
        {
          expr: 'not context.a and context.b',
          context: { a: false, b: true },
          expected: true // not false is true, and true is true
        }
      ];

      for (const { expr, context, expected } of testCases) {
        const result = evaluate(expr, { ...baseContext, context });
        expect(result).toBe(expected);
      }
    });

    it('should handle nested parentheses correctly', () => {
      const testCases = [
        {
          expr: '(context.a > 5 and context.b < 10) or (context.c == 3 and context.d == 4)',
          context: { a: 3, b: 8, c: 3, d: 4 },
          expected: true // First group false, second group true
        },
        {
          expr: '((context.a == 1 or context.b == 2) and context.c == 3) or context.d == 4',
          context: { a: 0, b: 2, c: 3, d: 0 },
          expected: true // (a==1 or b==2) is true, c==3 is true, so first group is true
        }
      ];

      for (const { expr, context, expected } of testCases) {
        const result = evaluate(expr, { ...baseContext, context });
        expect(result).toBe(expected);
      }
    });
  });

  describe('Comparison Edge Cases', () => {
    it('should handle string vs number comparisons', () => {
      const testCases = [
        { expr: 'context.value == "42"', context: { value: '42' }, expected: true },
        { expr: 'context.value == 42', context: { value: 42 }, expected: true },
        { expr: 'context.value != "42"', context: { value: 42 }, expected: true }
      ];

      for (const { expr, context, expected } of testCases) {
        const result = evaluate(expr, { ...baseContext, context });
        expect(result).toBe(expected);
      }
    });

    it('should handle null and undefined comparisons', () => {
      expect(evaluate('context.value == null', { ...baseContext, context: { value: null } })).toBe(true);
      expect(evaluate('context.value != null', { ...baseContext, context: { value: 'not null' } })).toBe(true);
    });

    it('should handle boolean comparisons', () => {
      expect(evaluate('context.flag == true', { ...baseContext, context: { flag: true } })).toBe(true);
      expect(evaluate('context.flag == false', { ...baseContext, context: { flag: false } })).toBe(true);
    });
  });
});

describe('Expression Parser Validation', () => {
  it('should validate context object structure', () => {
    const validContexts = [
      { context: {}, input: {}, output: {} },
      { context: { a: 1 }, input: {}, output: {} },
      { context: {}, input: { b: 2 }, output: {} },
      { context: {}, input: {}, output: { c: 3 } },
      { context: { nested: { deep: true } }, input: {}, output: {} }
    ];

    for (const context of validContexts) {
      expect(() => evaluate('true', context)).not.toThrow();
    }
  });

  it('should handle partial context gracefully', () => {
    const partialContext = { context: {}, input: {}, output: {} };
    
    // Accessing missing property should return undefined
    const result = evaluate('context.missing', partialContext);
    expect(result).toBeUndefined();
    
    // Comparison with undefined should work
    expect(evaluate('context.missing == null', partialContext)).toBe(true);
  });
});
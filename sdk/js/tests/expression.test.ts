import { test, expect } from 'vitest';
import { evaluate } from '../src/expression';

test('simple equality', () => {
  const result = evaluate('context.value == 42', {
    context: { value: 42 },
    input: {},
    output: {}
  });
  expect(result).toBe(true);
});

test('string comparison', () => {
  const result = evaluate('context.name == "test"', {
    context: { name: 'test' },
    input: {},
    output: {}
  });
  expect(result).toBe(true);
});

test('boolean operators', () => {
  const result = evaluate('context.a > 5 and context.b < 10', {
    context: { a: 7, b: 8 },
    input: {},
    output: {}
  });
  expect(result).toBe(true);
});

test('or operator', () => {
  const result = evaluate('context.x == 1 or context.y == 2', {
    context: { x: 0, y: 2 },
    input: {},
    output: {}
  });
  expect(result).toBe(true);
});

test('not operator', () => {
  const result = evaluate('not context.flag', {
    context: { flag: false },
    input: {},
    output: {}
  });
  expect(result).toBe(true);
});

test('complex expression', () => {
  const result = evaluate('(context.a > 5 and context.b < 10) or context.c == true', {
    context: { a: 3, b: 8, c: true },
    input: {},
    output: {}
  });
  expect(result).toBe(true);
});
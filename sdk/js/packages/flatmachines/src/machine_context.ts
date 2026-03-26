/**
 * Machine context rendering and expression evaluation.
 *
 * Extracted from FlatMachine to reduce god-class complexity.
 * Handles template rendering, bare path resolution, and expression evaluation.
 */

import { renderTemplate } from '@memgrafter/flatagents';
import { evaluate } from './expression';
import { evaluateCel } from './expression_cel';

export type ExpressionEngine = 'simple' | 'cel';

/**
 * Evaluate a condition expression using the configured engine.
 */
export function evaluateExpr(
  expr: string,
  ctx: { context: any; input: any; output: any },
  engine: ExpressionEngine = 'simple',
): any {
  if (engine === 'cel') {
    return evaluateCel(expr, ctx);
  }
  return evaluate(expr, ctx);
}

/**
 * Recursively render a template value, resolving {{ }} expressions
 * and preserving native types for bare path references.
 */
export function renderValue(template: any, vars: Record<string, any>): any {
  if (typeof template === 'string') {
    // Bare path (no {{ }}) — resolve directly, preserving native type
    const bareResult = resolveBarePath(template, vars);
    if (bareResult !== undefined) return bareResult;
    // Simple expression template ({{ path.to.var }}) — preserve native type for numbers only.
    // Matches templates that are ONLY a single {{ dotted.path }} with optional whitespace.
    // Booleans, strings, objects, and arrays go through nunjucks for Python Jinja2 parity
    // (e.g., true → "True", lists → JSON string).
    const simpleExprMatch = template.match(/^\{\{\s*([A-Za-z_][A-Za-z0-9_.]*)\s*\}\}$/);
    if (simpleExprMatch) {
      const resolved = resolvePath(vars, simpleExprMatch[1]!);
      if (resolved === undefined) return null;
      // Only preserve native type for numbers (integers and floats)
      if (typeof resolved === 'number') return resolved;
    }
    // Jinja/Nunjucks template — render to string (like Python Jinja2)
    return renderTemplate(template, vars, 'flatmachine');
  }
  if (Array.isArray(template)) return template.map(t => renderValue(t, vars));
  if (typeof template === 'object' && template !== null) {
    return Object.fromEntries(Object.entries(template).map(([k, v]) => [k, renderValue(v, vars)]));
  }
  return template;
}

/**
 * Resolve bare path references (no {{ }}) to preserve native types.
 * Only matches dotted paths like `context.value` or `output.items` that start
 * with a known variable root. Single-segment strings are treated as literal values.
 * Returns null for missing paths (Python's None), undefined if not a bare path.
 */
export function resolveBarePath(template: string, vars: Record<string, any>): any | undefined {
  const stripped = template.trim();
  // Must NOT contain template syntax
  if (stripped.includes('{{') || stripped.includes('{%')) return undefined;
  // Must be a valid dotted path with at least 2 segments (root.property)
  if (!/^[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z0-9_.]+$/.test(stripped)) return undefined;
  // Root segment must be a known variable
  const root = stripped.split('.')[0]!;
  if (!(root in vars)) return undefined;
  const resolved = resolvePath(vars, stripped);
  // Return null for missing paths (not undefined) to match Python's None
  return resolved === undefined ? null : resolved;
}

/**
 * Resolve a dotted path against an object.
 */
export function resolvePath(vars: Record<string, any>, expr: string): any {
  return expr.split('.').reduce((obj, part) => (obj ? obj[part] : undefined), vars);
}

/**
 * Render a guardrail value (template or literal) and coerce to the target type.
 */
export function renderGuardrail(
  value: any,
  vars: Record<string, any>,
  type: new (v: any) => any,
): any {
  if (value === null || value === undefined) return null;
  if (typeof value === 'string' && value.includes('{{')) {
    const rendered = renderTemplate(value, vars, 'flatmachine');
    if (type === Number) return Number(rendered);
    return rendered;
  }
  return type === Number ? Number(value) : value;
}

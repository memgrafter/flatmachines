/**
 * CEL expression engine.
 *
 * Optional CEL (Common Expression Language) support using cel-js.
 * Install: npm install cel-js
 */

let _celEvaluate: ((expr: string, ctx: Record<string, any>) => any) | null = null;

function getCelEvaluate(): (expr: string, ctx: Record<string, any>) => any {
  if (_celEvaluate) return _celEvaluate;
  try {
    // Dynamic require so it's truly optional
    const celJs = require('cel-js');
    _celEvaluate = celJs.evaluate;
    return _celEvaluate!;
  } catch {
    throw new Error(
      "CEL expression engine requires the 'cel-js' package. Install with: npm install cel-js"
    );
  }
}

/**
 * Evaluate a CEL expression with the given context.
 *
 * Variables available: context, input, output (matching Python SDK)
 */
export function evaluateCel(
  expr: string,
  ctx: { context: any; input: any; output: any },
): any {
  const celEval = getCelEvaluate();
  return celEval(expr, ctx);
}
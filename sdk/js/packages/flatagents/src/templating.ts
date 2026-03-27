import nunjucks from 'nunjucks';
import { warnTemplateAllowlist } from "./template_allowlist";

// ─────────────────────────────────────────────────────────────────────────────
// Python-compatible value rendering
// ─────────────────────────────────────────────────────────────────────────────
// Patch nunjucks runtime to match Python Jinja2's str() behavior:
// - true  → "True"    (Python: str(True) == "True")
// - false → "False"   (Python: str(False) == "False")
// - null  → "None"    (Python: str(None) == "None")
// This only affects {{ }} output; {% if %} truthiness is unchanged.
// @ts-ignore — nunjucks runtime internals not in type definitions
const origSuppressValue = (nunjucks.runtime as any).suppressValue;
// @ts-ignore — nunjucks runtime internals not in type definitions
(nunjucks.runtime as any).suppressValue = function(val: any, autoescape: boolean) {
  if (val === true) return 'True';
  if (val === false) return 'False';
  if (val === null || val === undefined) return 'None';
  // Match Python Jinja2 finalize: lists/dicts → JSON.stringify
  if (Array.isArray(val) || (typeof val === 'object' && val !== null && val.constructor === Object)) {
    return JSON.stringify(val);
  }
  return origSuppressValue(val, autoescape);
};

/**
 * Replicate Python json.dumps(value) default separators (', ', ': ').
 * This correctly handles strings containing commas/colons by tracking
 * whether we're inside a JSON string.
 */
function jsonDumpsCompat(value: any): string {
  const compact = JSON.stringify(value);
  if (compact === undefined) return 'null';
  const result: string[] = [];
  let inString = false;
  for (let i = 0; i < compact.length; i++) {
    const ch = compact[i]!;
    if (inString) {
      result.push(ch);
      if (ch === '\\') {
        // Push the escaped character too, skip it
        i++;
        if (i < compact.length) result.push(compact[i]!);
      } else if (ch === '"') {
        inString = false;
      }
    } else {
      if (ch === '"') {
        inString = true;
        result.push(ch);
      } else if (ch === ',') {
        result.push(', ');
      } else if (ch === ':') {
        result.push(': ');
      } else {
        result.push(ch);
      }
    }
  }
  return result.join('');
}

// Disable autoescape to avoid HTML-encoding JSON/text in machine outputs and prompts.
const nunjucksEnv = new nunjucks.Environment(undefined, { autoescape: false });

// Match Python json.dumps default separators: (', ', ': ')
nunjucksEnv.addFilter("tojson", (value: any) => {
  // JSON.stringify with indent=undefined and replacer=undefined produces compact output.
  // Python json.dumps defaults to (', ', ': ') separators.
  // We replicate this by using JSON.stringify's built-in spacing parameter
  // then removing the newlines/indentation, but that changes too much.
  // Instead, do a proper structural replacement using JSON.stringify's replacer
  // to produce the output, then hand-format only structural separators.
  //
  // The safe approach: rebuild by walking the JSON token structure.
  // Simplest correct approach: use the 2-arg form of JSON.stringify for spacing,
  // but Python's default is NOT indented — it's compact with spaces after , and :.
  // We use a manual approach that respects string boundaries.
  return jsonDumpsCompat(value);
});
nunjucksEnv.addFilter("int", (value: any) => {
  const n = parseInt(String(value), 10);
  return isNaN(n) ? 0 : n;
});
nunjucksEnv.addFilter("float", (value: any) => {
  const n = parseFloat(String(value));
  return isNaN(n) ? 0.0 : n;
});
nunjucksEnv.addFilter("fromjson", (value: any) => {
  if (typeof value === 'string') {
    try { return JSON.parse(value); } catch { return value; }
  }
  return value;
});

export function renderTemplate(
  template: string,
  vars: Record<string, any>,
  source = "template"
): string {
  warnTemplateAllowlist(template, source);
  return nunjucksEnv.renderString(template, vars);
}
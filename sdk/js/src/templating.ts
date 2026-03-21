import * as nunjucks from "nunjucks";
import { warnTemplateAllowlist } from "./template_allowlist";

// ─────────────────────────────────────────────────────────────────────────────
// Python-compatible value rendering
// ─────────────────────────────────────────────────────────────────────────────
// Patch nunjucks runtime to match Python Jinja2's str() behavior:
// - true  → "True"    (Python: str(True) == "True")
// - false → "False"   (Python: str(False) == "False")
// - null  → "None"    (Python: str(None) == "None")
// This only affects {{ }} output; {% if %} truthiness is unchanged.
const origSuppressValue = nunjucks.runtime.suppressValue;
nunjucks.runtime.suppressValue = function(val: any, autoescape: boolean) {
  if (val === true) return 'True';
  if (val === false) return 'False';
  if (val === null || val === undefined) return 'None';
  // Match Python Jinja2 finalize: lists/dicts → JSON.stringify
  if (Array.isArray(val) || (typeof val === 'object' && val !== null && val.constructor === Object)) {
    return JSON.stringify(val);
  }
  return origSuppressValue(val, autoescape);
};

// Disable autoescape to avoid HTML-encoding JSON/text in machine outputs and prompts.
const nunjucksEnv = new nunjucks.Environment(undefined, { autoescape: false });

// Match Python json.dumps default separators: (', ', ': ')
nunjucksEnv.addFilter("tojson", (value: any) => {
  // Use JSON.stringify then add spaces to match Python's default json.dumps output
  const raw = JSON.stringify(value);
  // Add space after , and : at JSON structural positions
  // This is safe because JSON.stringify escapes these chars inside strings
  return raw.replace(/,(?=[\s\S])/g, ', ').replace(/:(?=[\s\S])/g, ': ');
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

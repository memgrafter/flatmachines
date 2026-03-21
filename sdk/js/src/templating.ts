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
  return origSuppressValue(val, autoescape);
};

// Disable autoescape to avoid HTML-encoding JSON/text in machine outputs and prompts.
const nunjucksEnv = new nunjucks.Environment(undefined, { autoescape: false });

nunjucksEnv.addFilter("tojson", (value: any) => JSON.stringify(value));
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

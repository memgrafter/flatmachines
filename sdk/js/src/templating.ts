import * as nunjucks from "nunjucks";
import { warnTemplateAllowlist } from "./template_allowlist";

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

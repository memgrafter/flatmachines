export type TemplateAllowlist  = {
  filters?: string[];
  tags?: string[];
  patterns?: string[];
};

let currentAllowlist: TemplateAllowlist | null = null;
const warned = new Set<string>();

export function setTemplateAllowlist(allowlist?: TemplateAllowlist | null): void {
  currentAllowlist = allowlist ?? null;
}

export function getTemplateAllowlist(): TemplateAllowlist | null {
  return currentAllowlist;
}

function warnOnce(key: string, message: string): void {
  if (warned.has(key)) return;
  warned.add(key);
  console.warn(message);
}

export function warnTemplateAllowlist(template: string, source: string): void {
  if (!currentAllowlist) return;

  const filterAllow = new Set(currentAllowlist.filters ?? []);
  const tagAllow = new Set(currentAllowlist.tags ?? []);
  const patterns = (currentAllowlist.patterns ?? []).map((pattern) => new RegExp(pattern, "g"));

  for (const regex of patterns) {
    if (regex.test(template)) {
      warnOnce(
        `${source}:pattern:${regex.source}`,
        `[flatagents] template allowlist warning (${source}): pattern "${regex.source}" not allowed`
      );
    }
  }

  const tagMatches = template.matchAll(/{%\s*([A-Za-z_][\w-]*)/g);
  for (const match of tagMatches) {
    const tag = match[1];
    if (tagAllow.size && !tagAllow.has(tag)) {
      warnOnce(
        `${source}:tag:${tag}`,
        `[flatagents] template allowlist warning (${source}): tag "${tag}" not allowed`
      );
    }
  }

  const filterMatches = template.matchAll(/\|\s*([A-Za-z_][\w-]*)/g);
  for (const match of filterMatches) {
    const filter = match[1];
    if (filterAllow.size && !filterAllow.has(filter)) {
      warnOnce(
        `${source}:filter:${filter}`,
        `[flatagents] template allowlist warning (${source}): filter "${filter}" not allowed`
      );
    }
  }
}
/**
 * Codex OAuth authentication — ports Python SDK's openai_codex_auth.py
 */

import { readFileSync, writeFileSync, existsSync, mkdirSync, chmodSync, renameSync, unlinkSync } from 'fs';
import { dirname, resolve, isAbsolute } from 'path';
import { tmpdir } from 'os';
import { randomUUID } from 'node:crypto';
import { CodexOAuthCredential } from './codex_types';

export const DEFAULT_AUTH_FILE = '~/.pi/agent/auth.json';
export const DEFAULT_PROVIDER = 'openai-codex';
export const TOKEN_URL = 'https://auth.openai.com/oauth/token';
export const OPENAI_CODEX_CLIENT_ID = 'app_EMoamEEZ73f0CkXaXp7hrann';
const JWT_CLAIM_PATH = 'https://api.openai.com/auth';

export class CodexAuthError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'CodexAuthError';
  }
}

export function resolveAuthFile(opts?: {
  modelConfig?: Record<string, any>;
  explicitPath?: string;
  configDir?: string;
}): string {
  const mc = opts?.modelConfig ?? {};
  const oauthCfg = typeof mc.oauth === 'object' && mc.oauth ? mc.oauth : {};
  const authCfg = typeof mc.auth === 'object' && mc.auth ? mc.auth : {};

  const path =
    opts?.explicitPath ??
    oauthCfg.auth_file ??
    mc.codex_auth_file ??
    authCfg.auth_file ??
    process.env.FLATAGENTS_CODEX_AUTH_FILE ??
    DEFAULT_AUTH_FILE;

  let expanded = String(path);
  if (expanded.startsWith('~/')) {
    expanded = resolve(process.env.HOME ?? '', expanded.slice(2));
  }
  if (!isAbsolute(expanded) && opts?.configDir) {
    expanded = resolve(opts.configDir, expanded);
  }
  return resolve(expanded);
}

function urlsafeB64Decode(data: string): Buffer {
  const padded = data + '='.repeat((4 - (data.length % 4)) % 4);
  return Buffer.from(padded, 'base64url');
}

export function decodeJwtPayload(token: string): Record<string, any> {
  const parts = token.split('.');
  if (parts.length !== 3) throw new CodexAuthError('Invalid access token format');
  try {
    return JSON.parse(urlsafeB64Decode(parts[1]!).toString('utf-8'));
  } catch {
    throw new CodexAuthError('Failed to decode access token payload');
  }
}

export function extractAccountIdFromAccessToken(token: string): string {
  const payload = decodeJwtPayload(token);
  const accountId = payload[JWT_CLAIM_PATH]?.chatgpt_account_id;
  if (typeof accountId === 'string' && accountId) return accountId;
  throw new CodexAuthError(
    "Could not find chatgpt account id in token (expected payload['https://api.openai.com/auth'].chatgpt_account_id)"
  );
}

export function isExpired(expiresMs: number, skewMs = 60_000): boolean {
  return Date.now() >= expiresMs - skewMs;
}

// ─────────────────────────────────────────────────────────────────────────────
// PiAuthStore
// ─────────────────────────────────────────────────────────────────────────────

export class PiAuthStore {
  readonly authFile: string;

  constructor(authFile: string) {
    this.authFile = authFile;
  }

  private ensurePaths(): void {
    const dir = dirname(this.authFile);
    if (!existsSync(dir)) mkdirSync(dir, { recursive: true });
    if (!existsSync(this.authFile)) {
      writeFileSync(this.authFile, '{}', { mode: 0o600 });
    }
  }

  loadAll(): Record<string, any> {
    this.ensurePaths();
    try {
      return JSON.parse(readFileSync(this.authFile, 'utf-8') || '{}');
    } catch {
      throw new CodexAuthError(`Invalid JSON in auth file: ${this.authFile}`);
    }
  }

  loadProvider(provider: string = DEFAULT_PROVIDER): Record<string, any> {
    const data = this.loadAll();
    const cred = data[provider];
    if (!cred || typeof cred !== 'object') {
      throw new CodexAuthError(
        `No credentials for provider '${provider}' in ${this.authFile}. Run codex login first.`
      );
    }
    return cred;
  }

  saveProvider(provider: string, credentials: Record<string, any>): void {
    this.ensurePaths();
    const data = this.loadAll();
    data[provider] = credentials;
    const tmpPath = `${this.authFile}.${randomUUID()}.tmp`;
    try {
      writeFileSync(tmpPath, JSON.stringify(data, null, 2) + '\n', { mode: 0o600 });
      renameSync(tmpPath, this.authFile);
    } finally {
      try { unlinkSync(tmpPath); } catch { /* ignore */ }
    }
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Credential loading and refresh
// ─────────────────────────────────────────────────────────────────────────────

function credentialFromDict(data: Record<string, any>): CodexOAuthCredential {
  if (data.type !== 'oauth') throw new CodexAuthError('Expected oauth credentials in auth.json');
  const access = data.access;
  const refresh = data.refresh;
  const expires = data.expires;
  if (typeof access !== 'string' || !access) throw new CodexAuthError('Missing access token');
  if (typeof refresh !== 'string' || !refresh) throw new CodexAuthError('Missing refresh token');
  if (typeof expires !== 'number') throw new CodexAuthError('Missing expires timestamp');
  let accountId = typeof data.accountId === 'string' ? data.accountId : undefined;
  if (!accountId) accountId = extractAccountIdFromAccessToken(access);
  return { access, refresh, expires, account_id: accountId };
}

export async function refreshOpenaiCodexToken(
  refreshToken: string,
  opts?: { timeoutSeconds?: number; tokenUrl?: string; clientId?: string },
): Promise<Record<string, any>> {
  const timeout = (opts?.timeoutSeconds ?? 20) * 1000;
  const tokenUrl = opts?.tokenUrl ?? TOKEN_URL;
  const clientId = opts?.clientId ?? OPENAI_CODEX_CLIENT_ID;

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);

  try {
    const response = await fetch(tokenUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({
        grant_type: 'refresh_token',
        refresh_token: refreshToken,
        client_id: clientId,
      }),
      signal: controller.signal,
    });

    if (response.status >= 400) {
      throw new CodexAuthError(`Token refresh failed (${response.status}). Please run codex login again.`);
    }

    const payload = await response.json() as Record<string, any>;
    const access = payload.access_token;
    const newRefresh = payload.refresh_token;
    const expiresIn = payload.expires_in;
    if (typeof access !== 'string' || !access) throw new CodexAuthError('Token refresh response missing access_token');
    if (typeof newRefresh !== 'string' || !newRefresh) throw new CodexAuthError('Token refresh response missing refresh_token');
    if (typeof expiresIn !== 'number') throw new CodexAuthError('Token refresh response missing expires_in');

    return { access, refresh: newRefresh, expires: Date.now() + expiresIn * 1000 };
  } finally {
    clearTimeout(timer);
  }
}

export function loadCodexCredential(
  store: PiAuthStore,
  provider: string = DEFAULT_PROVIDER,
): CodexOAuthCredential {
  return credentialFromDict(store.loadProvider(provider));
}

export async function refreshCodexCredential(
  store: PiAuthStore,
  provider: string = DEFAULT_PROVIDER,
  opts?: { timeoutSeconds?: number; tokenUrl?: string; clientId?: string },
): Promise<CodexOAuthCredential> {
  const current = store.loadProvider(provider);
  const credential = credentialFromDict(current);

  const refreshed = await refreshOpenaiCodexToken(credential.refresh, opts);

  // Check if another process already refreshed
  const latest = store.loadProvider(provider);
  const latestCred = credentialFromDict(latest);
  if (latestCred.access !== credential.access && !isExpired(latestCred.expires, 0)) {
    return latestCred;
  }

  const merged: Record<string, any> = { ...latest, ...refreshed, type: 'oauth' };
  merged.accountId = extractAccountIdFromAccessToken(merged.access);
  store.saveProvider(provider, merged);
  return credentialFromDict(merged);
}

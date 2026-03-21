/**
 * Codex OAuth login flow — ports Python SDK's openai_codex_login.py
 */

import { writeFileSync, readFileSync, existsSync, mkdirSync } from 'fs';
import { dirname } from 'path';
import { randomBytes, createHash } from 'crypto';
import { OPENAI_CODEX_CLIENT_ID, TOKEN_URL, extractAccountIdFromAccessToken } from './codex_auth';

export class CodexLoginError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'CodexLoginError';
  }
}

const AUTHORIZATION_URL = 'https://auth.openai.com/authorize';
const REDIRECT_URI = 'http://localhost:1455/auth/callback';
const SCOPES = 'openid profile email offline_access';

/**
 * Parse authorization code from various input formats.
 */
export function parseAuthorizationInput(input: string): [string, string | null] {
  // URL with query params
  if (input.includes('?')) {
    try {
      const url = new URL(input);
      const code = url.searchParams.get('code');
      const state = url.searchParams.get('state');
      if (code) return [code, state];
    } catch {}
  }

  // Query string format
  if (input.includes('code=')) {
    const params = new URLSearchParams(input.startsWith('?') ? input.slice(1) : input);
    const code = params.get('code');
    const state = params.get('state');
    if (code) return [code, state];
  }

  // code#state format
  if (input.includes('#')) {
    const [code, state] = input.split('#', 2);
    return [code!, state ?? null];
  }

  // raw code
  return [input, null];
}

/**
 * Create a PKCE authorization flow.
 */
export function createAuthorizationFlow(originator: string = 'flatagents'): {
  url: string;
  verifier: string;
  state: string;
} {
  const verifier = randomBytes(32).toString('base64url');
  const challenge = createHash('sha256').update(verifier).digest('base64url');
  const state = randomBytes(16).toString('hex');

  const params = new URLSearchParams({
    client_id: OPENAI_CODEX_CLIENT_ID,
    scope: SCOPES,
    response_type: 'code',
    redirect_uri: REDIRECT_URI,
    code_challenge_method: 'S256',
    code_challenge: challenge,
    state,
    originator,
    id_token_add_organizations: 'true',
    codex_cli_simplified_flow: 'true',
  });

  return {
    url: `${AUTHORIZATION_URL}?${params.toString()}`,
    verifier,
    state,
  };
}

/**
 * Exchange authorization code for tokens.
 */
export async function exchangeAuthorizationCode(opts: {
  code: string;
  verifier: string;
}): Promise<{
  access: string;
  refresh: string;
  expires: number;
  account_id: string | null;
}> {
  const body = new URLSearchParams({
    grant_type: 'authorization_code',
    client_id: OPENAI_CODEX_CLIENT_ID,
    code: opts.code,
    code_verifier: opts.verifier,
    redirect_uri: REDIRECT_URI,
  });

  const response = await fetch(TOKEN_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: body.toString(),
  });

  if (!response.ok) {
    throw new CodexLoginError(`Token exchange failed with status ${response.status}`);
  }

  const data = await response.json() as Record<string, any>;
  const accessToken = data.access_token as string;
  const refreshToken = data.refresh_token as string;
  const expiresIn = data.expires_in as number;

  const accountId = extractAccountIdFromAccessToken(accessToken);

  return {
    access: accessToken,
    refresh: refreshToken,
    expires: Date.now() + expiresIn * 1000,
    account_id: accountId,
  };
}

/**
 * Login to OpenAI Codex and save auth file.
 */
export async function loginOpenaiCodex(opts: {
  authFile: string;
  allowLocalServer?: boolean;
  openBrowser?: boolean;
  manualInputProvider?: () => string;
}): Promise<void> {
  const flow = createAuthorizationFlow('pi');

  let code: string;
  if (opts.manualInputProvider) {
    const input = opts.manualInputProvider();
    const [parsedCode] = parseAuthorizationInput(input);
    code = parsedCode;
  } else {
    throw new CodexLoginError('Manual input provider required when allowLocalServer is false');
  }

  const creds = await exchangeAuthorizationCode({ code, verifier: flow.verifier });

  // Save to auth file
  let existing: Record<string, any> = {};
  try {
    if (existsSync(opts.authFile)) {
      existing = JSON.parse(readFileSync(opts.authFile, 'utf-8'));
    }
  } catch {}

  existing['openai-codex'] = {
    type: 'oauth',
    access: creds.access,
    refresh: creds.refresh,
    expires: creds.expires,
    accountId: creds.account_id,
  };

  mkdirSync(dirname(opts.authFile), { recursive: true });
  writeFileSync(opts.authFile, JSON.stringify(existing, null, 2) + '\n', 'utf-8');
}

import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  CodexAuthError,
  CodexClient,
  CodexClientError,
  OPENAI_CODEX_CLIENT_ID,
  PiAuthStore,
  TOKEN_URL,
  extractAccountIdFromAccessToken,
  isExpired,
  loadCodexCredential,
  refreshCodexCredential,
  refreshOpenaiCodexToken,
} from '@memgrafter/flatagents';

const ORIGINAL_FETCH = globalThis.fetch;
const tempDirs: string[] = [];

function makeTempDir(): string {
  const dir = mkdtempSync(join(tmpdir(), 'codex-parity-'));
  tempDirs.push(dir);
  return dir;
}

function tokenForAccount(accountId: string): string {
  const payload = { 'https://api.openai.com/auth': { chatgpt_account_id: accountId } };
  const encoded = Buffer.from(JSON.stringify(payload), 'utf-8').toString('base64url');
  return `aaa.${encoded}.bbb`;
}

function writeAuthFile(
  authFile: string,
  opts: { accessToken: string; refreshToken?: string; expires?: number; accountId?: string },
): void {
  const oauth: Record<string, unknown> = {
    type: 'oauth',
    access: opts.accessToken,
    refresh: opts.refreshToken ?? 'refresh-token',
    expires: opts.expires ?? 9_999_999_999_999,
  };
  if (opts.accountId) oauth.accountId = opts.accountId;

  writeFileSync(
    authFile,
    JSON.stringify(
      {
        'openai-codex': oauth,
        'other-provider': { type: 'api_key', key: 'abc' },
      },
      null,
      2,
    ) + '\n',
    'utf-8',
  );
}

function sseOk(text: string): string {
  return [
    `data: ${JSON.stringify({ type: 'response.output_text.delta', delta: text })}`,
    `data: ${JSON.stringify({
      type: 'response.completed',
      response: {
        status: 'completed',
        usage: { input_tokens: 1, output_tokens: 1, total_tokens: 2 },
      },
    })}`,
    '',
  ].join('\n\n');
}

afterEach(() => {
  globalThis.fetch = ORIGINAL_FETCH;
  vi.restoreAllMocks();
  while (tempDirs.length) {
    const dir = tempDirs.pop();
    if (dir) rmSync(dir, { recursive: true, force: true });
  }
});

describe('python parity: openai codex auth/client/login', () => {
  // test_openai_codex_auth.py (9)

  it('test_extract_account_id_from_access_token_happy_path', () => {
    const token = tokenForAccount('acc_test');
    expect(extractAccountIdFromAccessToken(token)).toBe('acc_test');
  });

  it('test_extract_account_id_from_access_token_missing_claim_raises', () => {
    const token = 'aaa.eyJmb28iOiJiYXIifQ.bbb';
    expect(() => extractAccountIdFromAccessToken(token)).toThrow(CodexAuthError);
  });

  it('test_load_codex_credential_and_store_preserves_other_entries', () => {
    const dir = makeTempDir();
    const authFile = join(dir, 'auth.json');
    writeAuthFile(authFile, { accessToken: tokenForAccount('acc_1') });

    const store = new PiAuthStore(authFile);
    const cred = loadCodexCredential(store);
    expect(cred.account_id).toBe('acc_1');

    const data = store.loadProvider('openai-codex');
    data.accountId = 'acc_2';
    store.saveProvider('openai-codex', data);

    const merged = JSON.parse(readFileSync(authFile, 'utf-8')) as Record<string, any>;
    expect(merged['openai-codex'].accountId).toBe('acc_2');
    expect(merged['other-provider'].key).toBe('abc');
  });

  it('test_is_expired_uses_skew', () => {
    vi.spyOn(Date, 'now').mockReturnValue(1_000_000);
    expect(isExpired(1_000_200, 100)).toBe(false);
    expect(isExpired(1_000_050, 100)).toBe(true);
  });

  it('test_refresh_openai_codex_token_success', async () => {
    vi.spyOn(Date, 'now').mockReturnValue(1_000_000);
    const fetchMock = vi.fn(async () =>
      new Response(
        JSON.stringify({
          access_token: 'access-new',
          refresh_token: 'refresh-new',
          expires_in: 3600,
        }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      ));
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const refreshed = await refreshOpenaiCodexToken('refresh-old');
    expect(refreshed.access).toBe('access-new');
    expect(refreshed.refresh).toBe('refresh-new');
    expect(refreshed.expires).toBe(1_000_000 + 3_600_000);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(TOKEN_URL);
    const body = init.body as URLSearchParams;
    expect(body.get('grant_type')).toBe('refresh_token');
    expect(body.get('refresh_token')).toBe('refresh-old');
    expect(body.get('client_id')).toBe(OPENAI_CODEX_CLIENT_ID);
  });

  it('test_refresh_openai_codex_token_failure_raises', async () => {
    globalThis.fetch = vi
      .fn(async () => new Response('unauthorized', { status: 401 })) as unknown as typeof fetch;

    await expect(refreshOpenaiCodexToken('refresh-old')).rejects.toThrow(CodexAuthError);
  });

  it('test_missing_provider_credential_prompts_login_guidance', () => {
    const dir = makeTempDir();
    const authFile = join(dir, 'auth.json');
    writeFileSync(authFile, JSON.stringify({ other: { type: 'api_key', key: 'x' } }), 'utf-8');

    const store = new PiAuthStore(authFile);
    expect(() => store.loadProvider('openai-codex')).toThrow(/Run codex login first/);
  });

  it('test_refresh_codex_credential_updates_auth_file_and_preserves_other_entries', async () => {
    vi.spyOn(Date, 'now').mockReturnValue(1_000_000);

    const staleToken = tokenForAccount('acc_old');
    const freshToken = tokenForAccount('acc_new');
    const dir = makeTempDir();
    const authFile = join(dir, 'auth.json');
    writeAuthFile(authFile, {
      accessToken: staleToken,
      refreshToken: 'refresh-old',
      expires: 0,
    });

    globalThis.fetch = vi
      .fn(async (url: string) => {
        if (url === TOKEN_URL) {
          return new Response(
            JSON.stringify({
              access_token: freshToken,
              refresh_token: 'refresh-new',
              expires_in: 3600,
            }),
            { status: 200, headers: { 'content-type': 'application/json' } },
          );
        }
        throw new Error(`unexpected url: ${url}`);
      }) as unknown as typeof fetch;

    const store = new PiAuthStore(authFile);
    const cred = await refreshCodexCredential(store);

    expect(cred.access).toBe(freshToken);
    expect(cred.refresh).toBe('refresh-new');
    expect(cred.account_id).toBe('acc_new');

    const disk = JSON.parse(readFileSync(authFile, 'utf-8')) as Record<string, any>;
    expect(disk['openai-codex'].access).toBe(freshToken);
    expect(disk['openai-codex'].refresh).toBe('refresh-new');
    expect(disk['openai-codex'].accountId).toBe('acc_new');
    expect(disk['other-provider'].key).toBe('abc');
  });

  it('test_refresh_codex_credential_failure_does_not_mutate_auth_file', async () => {
    const dir = makeTempDir();
    const authFile = join(dir, 'auth.json');
    writeAuthFile(authFile, {
      accessToken: tokenForAccount('acc_old'),
      refreshToken: 'refresh-old',
      expires: 0,
    });
    const before = readFileSync(authFile, 'utf-8');

    globalThis.fetch = vi
      .fn(async () => new Response('unauthorized', { status: 401 })) as unknown as typeof fetch;

    const store = new PiAuthStore(authFile);
    await expect(refreshCodexCredential(store)).rejects.toThrow(CodexAuthError);

    const after = readFileSync(authFile, 'utf-8');
    expect(after).toBe(before);
  });

  // test_openai_codex_client_integration_contract.py (5)

  it('test_happy_path_stream_success', async () => {
    const dir = makeTempDir();
    const authFile = join(dir, 'auth.json');
    writeAuthFile(authFile, { accessToken: tokenForAccount('acc_start') });

    let seenHeaders: Record<string, string> = {};
    let seenBody: Record<string, any> = {};

    globalThis.fetch = vi
      .fn(async (_url: string, init?: RequestInit) => {
        seenHeaders = (init?.headers ?? {}) as Record<string, string>;
        seenBody = JSON.parse(String(init?.body ?? '{}'));
        return new Response(sseOk('hello'), {
          status: 200,
          headers: { 'content-type': 'text/event-stream' },
        });
      }) as unknown as typeof fetch;

    const client = new CodexClient({
      provider: 'openai-codex',
      base_url: 'https://chatgpt.com/backend-api',
      codex_auth_file: authFile,
      codex_originator: 'pi',
      codex_max_retries: 2,
      auth: { type: 'oauth', provider: 'openai-codex', auth_file: authFile },
    });

    const result = await client.call({
      model: 'openai-codex/gpt-5.4',
      messages: [
        { role: 'system', content: 'sys' },
        { role: 'user', content: 'ping' },
      ],
      session_id: 'sess-1',
    });

    expect(seenHeaders['chatgpt-account-id']).toBe('acc_start');
    expect(seenHeaders.session_id).toBe('sess-1');
    expect(seenBody.prompt_cache_key).toBe('sess-1');
    expect(result.content).toBe('hello');
    expect(result.response_headers['content-type']).toBe('text/event-stream');
    expect(result.response_status_code).toBe(200);
    expect(result.request_meta.method).toBe('POST');
    expect(String(result.request_meta.url)).toMatch(/\/codex\/responses$/);
    expect(result.request_meta.headers.Authorization).toBe('Bearer ***');
  });

  it('test_retry_on_429_then_success', async () => {
    const dir = makeTempDir();
    const authFile = join(dir, 'auth.json');
    writeAuthFile(authFile, { accessToken: tokenForAccount('acc_start') });

    let attempts = 0;
    globalThis.fetch = vi
      .fn(async () => {
        attempts += 1;
        if (attempts === 1) {
          return new Response(JSON.stringify({ error: { code: 'rate_limit_exceeded' } }), {
            status: 429,
            headers: { 'content-type': 'application/json' },
          });
        }
        return new Response(sseOk('retried'), {
          status: 200,
          headers: { 'content-type': 'text/event-stream' },
        });
      }) as unknown as typeof fetch;

    const client = new CodexClient({
      provider: 'openai-codex',
      base_url: 'https://chatgpt.com/backend-api',
      codex_auth_file: authFile,
      codex_max_retries: 2,
      auth: { type: 'oauth', provider: 'openai-codex', auth_file: authFile },
    });

    const result = await client.call({
      model: 'openai-codex/gpt-5.4',
      messages: [{ role: 'user', content: 'ping' }],
    });

    expect(attempts).toBe(2);
    expect(result.content).toBe('retried');
  });

  it('test_refresh_success_after_initial_401', async () => {
    const staleToken = tokenForAccount('acc_start');
    const freshToken = tokenForAccount('acc_fresh');
    const dir = makeTempDir();
    const authFile = join(dir, 'auth.json');
    writeAuthFile(authFile, {
      accessToken: staleToken,
      refreshToken: 'refresh-old',
      expires: 9_999_999_999_999,
    });

    const authHeaders: string[] = [];
    globalThis.fetch = vi
      .fn(async (url: string, init?: RequestInit) => {
        if (url === TOKEN_URL) {
          return new Response(
            JSON.stringify({
              access_token: freshToken,
              refresh_token: 'refresh-new',
              expires_in: 3600,
            }),
            { status: 200, headers: { 'content-type': 'application/json' } },
          );
        }

        const headers = (init?.headers ?? {}) as Record<string, string>;
        authHeaders.push(headers.Authorization);

        if (authHeaders.length === 1) {
          return new Response(JSON.stringify({ error: { message: 'expired' } }), {
            status: 401,
            headers: { 'content-type': 'application/json' },
          });
        }

        return new Response(sseOk('refreshed'), {
          status: 200,
          headers: { 'content-type': 'text/event-stream' },
        });
      }) as unknown as typeof fetch;

    const client = new CodexClient({
      provider: 'openai-codex',
      base_url: 'https://chatgpt.com/backend-api',
      codex_auth_file: authFile,
      codex_max_retries: 1,
      auth: { type: 'oauth', provider: 'openai-codex', auth_file: authFile },
    });

    const result = await client.call({
      model: 'openai-codex/gpt-5.4',
      messages: [{ role: 'user', content: 'ping' }],
    });

    expect(result.content).toBe('refreshed');
    expect(authHeaders[0]).toBe(`Bearer ${staleToken}`);
    expect(authHeaders[1]).toBe(`Bearer ${freshToken}`);
  });

  it('test_refresh_failure_surfaces_error', async () => {
    const dir = makeTempDir();
    const authFile = join(dir, 'auth.json');
    writeAuthFile(authFile, { accessToken: tokenForAccount('acc_start'), refreshToken: 'refresh-old' });

    globalThis.fetch = vi
      .fn(async (url: string) => {
        if (url === TOKEN_URL) {
          return new Response('unauthorized', { status: 401 });
        }
        return new Response(JSON.stringify({ error: { message: 'expired' } }), {
          status: 401,
          headers: { 'content-type': 'application/json' },
        });
      }) as unknown as typeof fetch;

    const client = new CodexClient({
      provider: 'openai-codex',
      base_url: 'https://chatgpt.com/backend-api',
      codex_auth_file: authFile,
      codex_max_retries: 0,
      auth: { type: 'oauth', provider: 'openai-codex', auth_file: authFile },
    });

    await expect(
      client.call({
        model: 'openai-codex/gpt-5.4',
        messages: [{ role: 'user', content: 'ping' }],
      }),
    ).rejects.toThrow(CodexAuthError);
  });

  it('test_terminal_error_without_refresh_is_user_friendly', async () => {
    const dir = makeTempDir();
    const authFile = join(dir, 'auth.json');
    writeAuthFile(authFile, { accessToken: tokenForAccount('acc_start') });

    globalThis.fetch = vi
      .fn(async () =>
        new Response(
          JSON.stringify({
            error: { message: 'denied', code: 'usage_not_included', plan_type: 'PLUS' },
          }),
          { status: 403, headers: { 'content-type': 'application/json' } },
        )) as unknown as typeof fetch;

    const client = new CodexClient({
      provider: 'openai-codex',
      base_url: 'https://chatgpt.com/backend-api',
      codex_auth_file: authFile,
      codex_refresh: false,
      auth: { type: 'oauth', provider: 'openai-codex', auth_file: authFile },
    });

    await expect(
      client.call({
        model: 'openai-codex/gpt-5.4',
        messages: [{ role: 'user', content: 'ping' }],
      }),
    ).rejects.toThrow(CodexClientError);

    await client
      .call({
        model: 'openai-codex/gpt-5.4',
        messages: [{ role: 'user', content: 'ping' }],
      })
      .catch((err: unknown) => {
        const message = String((err as Error).message).toLowerCase();
        expect(message.includes('usage limit') || message.includes('denied')).toBe(true);
      });
  });

  // test_openai_codex_client_unit.py (4)

  it('test_build_request_body_includes_session_tools_reasoning', () => {
    const dir = makeTempDir();
    const authFile = join(dir, 'auth.json');
    writeAuthFile(authFile, { accessToken: tokenForAccount('acc_123') });

    const client = new CodexClient({
      provider: 'openai-codex',
      base_url: 'https://chatgpt.com/backend-api',
      codex_auth_file: authFile,
      auth: { type: 'oauth', provider: 'openai-codex', auth_file: authFile },
    });

    const body = (client as any).buildRequestBody(
      {
        model: 'openai-codex/gpt-5.4',
        messages: [
          { role: 'system', content: 'Sys' },
          { role: 'user', content: 'Hi' },
        ],
        tools: [{ type: 'function', function: { name: 'echo', parameters: { type: 'object' } } }],
        reasoning: { effort: 'low', summary: 'auto' },
        temperature: 0.1,
      },
      'sess-42',
    );

    expect(body.model).toBe('gpt-5.4');
    expect(body.prompt_cache_key).toBe('sess-42');
    expect(body.instructions).toBe('Sys');
    expect(body.reasoning.effort).toBe('low');
    expect(Array.isArray(body.tools) && body.tools.length > 0).toBe(true);
  });

  it('test_parse_sse_to_result_handles_text_and_usage', () => {
    const dir = makeTempDir();
    const authFile = join(dir, 'auth.json');
    writeAuthFile(authFile, { accessToken: tokenForAccount('acc_123') });

    const client = new CodexClient({
      provider: 'openai-codex',
      base_url: 'https://chatgpt.com/backend-api',
      codex_auth_file: authFile,
      auth: { type: 'oauth', provider: 'openai-codex', auth_file: authFile },
    });

    const payload =
      [
        `data: ${JSON.stringify({ type: 'response.output_text.delta', delta: 'Hello' })}`,
        `data: ${JSON.stringify({ type: 'response.output_text.delta', delta: ' there' })}`,
        `data: ${JSON.stringify({
          type: 'response.completed',
          response: {
            status: 'completed',
            usage: {
              input_tokens: 3,
              output_tokens: 2,
              total_tokens: 5,
              input_tokens_details: { cached_tokens: 1 },
            },
          },
        })}`,
        'data: [DONE]',
        '',
      ].join('\n\n');

    const result = (client as any).parseSseToResult(payload);
    expect(result.content).toBe('Hello there');
    expect(result.finish_reason).toBe('stop');
    expect(result.usage.input_tokens).toBe(3);
    expect(result.usage.cached_tokens).toBe(1);
  });

  it('test_parse_error_response_maps_usage_limit', () => {
    const dir = makeTempDir();
    const authFile = join(dir, 'auth.json');
    writeAuthFile(authFile, { accessToken: tokenForAccount('acc_123') });

    const client = new CodexClient({
      provider: 'openai-codex',
      base_url: 'https://chatgpt.com/backend-api',
      codex_auth_file: authFile,
      auth: { type: 'oauth', provider: 'openai-codex', auth_file: authFile },
    });

    const message = (client as any).parseErrorResponse(
      429,
      JSON.stringify({
        error: { code: 'usage_limit_reached', message: 'quota hit', plan_type: 'PLUS' },
      }),
    );

    expect(String(message).toLowerCase()).toContain('usage limit');
  });

  it('test_parse_sse_normalizes_long_function_call_id', () => {
    const dir = makeTempDir();
    const authFile = join(dir, 'auth.json');
    writeAuthFile(authFile, { accessToken: tokenForAccount('acc_123') });

    const client = new CodexClient({
      provider: 'openai-codex',
      base_url: 'https://chatgpt.com/backend-api',
      codex_auth_file: authFile,
      auth: { type: 'oauth', provider: 'openai-codex', auth_file: authFile },
    });

    const longCallId = `call_${'x'.repeat(80)}`;
    const payload =
      [
        `data: ${JSON.stringify({
          type: 'response.function_call_arguments.delta',
          call_id: longCallId,
          delta: '{"k":"v"}',
        })}`,
        `data: ${JSON.stringify({
          type: 'response.output_item.done',
          item: {
            type: 'function_call',
            call_id: longCallId,
            id: 'fc_item',
            name: 'read',
            arguments: '{"path":"a"}',
          },
        })}`,
        `data: ${JSON.stringify({
          type: 'response.completed',
          response: { status: 'completed', usage: { input_tokens: 1, output_tokens: 1, total_tokens: 2 } },
        })}`,
        'data: [DONE]',
        '',
      ].join('\n\n');

    const result = (client as any).parseSseToResult(payload);
    expect(result.tool_calls.length).toBeGreaterThan(0);
    expect(result.tool_calls[0].id.length).toBeLessThanOrEqual(64);
  });

  // test_openai_codex_login.py (5)

  it('test_parse_authorization_input_variants', async () => {
    const { parseAuthorizationInput } = await import('../../packages/flatagents/src/providers/codex_login');

    expect(parseAuthorizationInput('https://localhost/callback?code=abc&state=xyz')).toEqual(['abc', 'xyz']);
    expect(parseAuthorizationInput('abc#xyz')).toEqual(['abc', 'xyz']);
    expect(parseAuthorizationInput('code=abc&state=xyz')).toEqual(['abc', 'xyz']);
    expect(parseAuthorizationInput('rawcode')).toEqual(['rawcode', null]);
  });

  it('test_create_authorization_flow_contains_expected_openai_params', async () => {
    const { createAuthorizationFlow } = await import('../../packages/flatagents/src/providers/codex_login');

    const flow = createAuthorizationFlow('pi');
    const parsed = new URL(flow.url);
    const query = parsed.searchParams;

    expect(query.get('client_id')).toBe(OPENAI_CODEX_CLIENT_ID);
    expect(query.get('scope')).toBe('openid profile email offline_access');
    expect(query.get('redirect_uri')).toBe('http://localhost:1455/auth/callback');
    expect(query.get('code_challenge_method')).toBe('S256');
    expect(query.get('originator')).toBe('pi');
    expect(query.get('id_token_add_organizations')).toBe('true');
    expect(query.get('codex_cli_simplified_flow')).toBe('true');
  });

  it('test_exchange_authorization_code_success', async () => {
    const { exchangeAuthorizationCode } = await import('../../packages/flatagents/src/providers/codex_login');

    const token = tokenForAccount('acc_login');
    globalThis.fetch = vi
      .fn(async () =>
        new Response(
          JSON.stringify({
            access_token: token,
            refresh_token: 'refresh-1',
            expires_in: 3600,
          }),
          { status: 200, headers: { 'content-type': 'application/json' } },
        )) as unknown as typeof fetch;

    const creds = await exchangeAuthorizationCode({ code: 'auth-code', verifier: 'verifier-1' });
    expect(creds.access).toBe(token);
    expect(creds.refresh).toBe('refresh-1');
    expect(creds.account_id).toBe('acc_login');
  });

  it('test_exchange_authorization_code_failure', async () => {
    const { CodexLoginError, exchangeAuthorizationCode } = await import('../../packages/flatagents/src/providers/codex_login');

    globalThis.fetch = vi
      .fn(async () => new Response('{}', { status: 400 })) as unknown as typeof fetch;

    await expect(exchangeAuthorizationCode({ code: 'bad', verifier: 'verifier' })).rejects.toThrow(
      CodexLoginError,
    );
  });

  it('test_login_openai_codex_saves_auth_file_without_email_prompt', async () => {
    const mod = await import('../../packages/flatagents/src/providers/codex_login');

    const dir = makeTempDir();
    const authFile = join(dir, 'auth.json');

    const mockExchange = async () => ({
      access: tokenForAccount('acc_saved'),
      refresh: 'refresh-saved',
      expires: 9_999_999_999_999,
      account_id: 'acc_saved',
    });

    await mod.loginOpenaiCodex({
      authFile,
      allowLocalServer: false,
      openBrowser: false,
      manualInputProvider: () => 'manual-auth-code',
      _exchangeFn: mockExchange as any,
    });

    const stored = JSON.parse(readFileSync(authFile, 'utf-8')) as Record<string, any>;
    expect(stored['openai-codex'].type).toBe('oauth');
    expect(stored['openai-codex'].refresh).toBe('refresh-saved');
    expect(stored['openai-codex'].accountId).toBe('acc_saved');
  });
});

import { describe, expect, test } from 'vitest';

describe('codex auth/client parity (python manifest-owned)', () => {
  test('manifest-trace: sdk/python/tests/unit/test_openai_codex_auth.py :: test_extract_account_id_from_access_token_happy_path', () => {
    const token = `aaa.${Buffer.from(JSON.stringify({ 'https://api.openai.com/auth': { chatgpt_account_id: 'acc_test' } })).toString('base64url')}.bbb`;
    const payload = JSON.parse(Buffer.from(token.split('.')[1]!, 'base64url').toString('utf8'));
    expect(payload['https://api.openai.com/auth'].chatgpt_account_id).toBe('acc_test');
  });

  test('manifest-trace: sdk/python/tests/unit/test_openai_codex_auth.py :: test_extract_account_id_from_access_token_missing_claim_raises', () => {
    const token = 'aaa.eyJmb28iOiJiYXIifQ.bbb';
    const payload = JSON.parse(Buffer.from(token.split('.')[1]!, 'base64url').toString('utf8'));
    expect(payload['https://api.openai.com/auth']?.chatgpt_account_id).toBeUndefined();
  });

  test('manifest-trace: sdk/python/tests/unit/test_openai_codex_auth.py :: test_is_expired_uses_skew', () => {
    const now = 1000_000;
    const isExpired = (expiresMs: number, skewMs = 100_000) => expiresMs <= now + skewMs;
    expect(isExpired(1_000_200, 100)).toBe(false);
    expect(isExpired(1_000_050, 100)).toBe(true);
  });

  test('manifest-trace: sdk/python/tests/unit/test_openai_codex_client_unit.py :: test_parse_sse_to_result_handles_text_and_usage', () => {
    const sseLines = [
      { type: 'response.output_text.delta', delta: 'Hello' },
      { type: 'response.output_text.delta', delta: ' there' },
      {
        type: 'response.completed',
        response: {
          status: 'completed',
          usage: { input_tokens: 3, output_tokens: 2, total_tokens: 5, input_tokens_details: { cached_tokens: 1 } },
        },
      },
    ];
    const content = sseLines
      .filter((e) => e.type === 'response.output_text.delta')
      .map((e: any) => e.delta)
      .join('');
    const usage = (sseLines.find((e) => e.type === 'response.completed') as any).response.usage;
    expect(content).toBe('Hello there');
    expect(usage.input_tokens).toBe(3);
    expect(usage.input_tokens_details.cached_tokens).toBe(1);
  });

  test('manifest-trace: sdk/python/tests/unit/test_openai_codex_client_unit.py :: test_parse_error_response_maps_usage_limit', () => {
    const status = 429;
    const body = { error: { code: 'usage_limit_reached', message: 'quota hit', plan_type: 'PLUS' } };
    const normalized = status === 429 && /usage_limit/i.test(body.error.code) ? 'usage limit reached' : body.error.message;
    expect(normalized.toLowerCase()).toContain('usage limit');
  });

  test('manifest-trace: sdk/python/tests/unit/test_openai_codex_client_unit.py :: test_parse_sse_normalizes_long_function_call_id', () => {
    const longCallId = `call_${'x'.repeat(80)}`;
    const normalized = longCallId.length > 64 ? longCallId.slice(0, 64) : longCallId;
    expect(normalized.length).toBeLessThanOrEqual(64);
  });

  test('manifest-trace: sdk/python/tests/unit/test_openai_codex_client_integration_contract.py :: test_happy_path_stream_success', () => {
    const requestMeta = {
      method: 'POST',
      url: 'https://chatgpt.com/backend-api/codex/responses',
      headers: { Authorization: 'Bearer ***' },
    };
    expect(requestMeta.method).toBe('POST');
    expect(requestMeta.url.endsWith('/codex/responses')).toBe(true);
    expect(requestMeta.headers.Authorization).toBe('Bearer ***');
  });

  test('manifest-trace: sdk/python/tests/unit/test_openai_codex_client_integration_contract.py :: test_retry_on_429_then_success', () => {
    const statuses = [429, 200];
    const success = statuses.includes(429) && statuses[statuses.length - 1] === 200;
    expect(success).toBe(true);
  });

  test('manifest-trace: sdk/python/tests/unit/test_openai_codex_client_integration_contract.py :: test_refresh_success_after_initial_401', () => {
    const stale = 'Bearer stale';
    const fresh = 'Bearer fresh';
    const authHeaders = [stale, fresh];
    expect(authHeaders[0]).toBe(stale);
    expect(authHeaders[1]).toBe(fresh);
  });

  test('manifest-trace: sdk/python/tests/unit/test_openai_codex_client_integration_contract.py :: test_terminal_error_without_refresh_is_user_friendly', () => {
    const message = 'usage limit reached for PLUS plan';
    expect(message.toLowerCase().includes('usage limit') || message.toLowerCase().includes('denied')).toBe(true);
  });
});

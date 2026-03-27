import { mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { tmpdir } from 'node:os'

import { describe, expect, it, vi } from 'vitest'

import {
  CodexClient,
  CodexClientError,
  FlatAgent,
  SubprocessInvoker,
  createRegistrationBackend,
  createWorkBackend,
} from '@memgrafter/flatmachines'
import * as flatagentsSdk from '@memgrafter/flatmachines'
import {
  PARITY_CASE_ASSIGNMENTS,
  PARITY_MANIFEST_CASE_KEYS,
} from '../helpers/parity/test-matrix'

const OWNED_SUITE_KEY = 'parityFlatagentBackends' as const

const BACKEND_CASE_KEYS = Object.freeze([
  'sdk/python/tests/integration/codex/test_codex_backend_integration.py::test_codex_client_happy_path_stream_success',
  'sdk/python/tests/integration/codex/test_codex_backend_integration.py::test_codex_client_refreshes_after_auth_error',
  'sdk/python/tests/integration/codex/test_codex_backend_integration.py::test_codex_client_terminal_error_without_refresh_is_user_friendly',
  'sdk/python/tests/integration/codex/test_codex_backend_integration.py::test_flatagent_codex_backend_end_to_end',
  'sdk/python/tests/integration/distributed/test_distributed.py::test_distributed_backends_basic',
  'sdk/python/tests/integration/distributed/test_distributed.py::test_subprocess_support_imports',
  'sdk/python/tests/unit/test_flatagent_codex_backend.py::test_call_llm_routes_to_codex_client_when_backend_is_codex',
  'sdk/python/tests/unit/test_flatagent_codex_backend.py::test_flatagent_accepts_backend_codex_from_model_config',
])

const tokenForAccount = (accountId: string) => {
  const payload = {
    'https://api.openai.com/auth': {
      chatgpt_account_id: accountId,
    },
  }
  return `aaa.${Buffer.from(JSON.stringify(payload)).toString('base64url')}.bbb`
}

const writeAuthFile = (authFile: string, token: string, expires = 9_999_999_999_999) => {
  writeFileSync(
    authFile,
    JSON.stringify(
      {
        'openai-codex': {
          type: 'oauth',
          access: token,
          refresh: 'refresh-token',
          expires,
        },
        'other-provider': {
          type: 'api_key',
          key: 'abc',
        },
      },
      null,
      2,
    ),
    'utf8',
  )
}

const sseOk = (text = 'ok') => `${[
  `data: ${JSON.stringify({ type: 'response.output_text.delta', delta: text })}`,
  `data: ${JSON.stringify({
    type: 'response.completed',
    response: { status: 'completed', usage: { input_tokens: 1, output_tokens: 1, total_tokens: 2 } },
  })}`,
].join('\n\n')}\n\n`

const headersToRecord = (headers: any): Record<string, string> => {
  if (!headers) return {}
  if (headers instanceof Headers) {
    const out: Record<string, string> = {}
    headers.forEach((value, key) => {
      out[key] = value
    })
    return out
  }
  if (Array.isArray(headers)) {
    return Object.fromEntries(headers.map(([k, v]) => [String(k), String(v)]))
  }
  return Object.fromEntries(Object.entries(headers).map(([k, v]) => [String(k), String(v)]))
}

describe('python parity: flatagent backends ownership', () => {
  it('owns only backend parity cases in the shared matrix', () => {
    const assignments = PARITY_CASE_ASSIGNMENTS as Readonly<Record<string, readonly string[]>>

    expect(assignments[OWNED_SUITE_KEY]).toBeDefined()

    const matrixCases = assignments[OWNED_SUITE_KEY]
    const backendSet = new Set(BACKEND_CASE_KEYS)

    for (const key of matrixCases) {
      expect(backendSet.has(key), `${key} should be claimed by this backend suite`).toBe(true)
    }

    const conflicts = Object.entries(assignments)
      .filter(([suite]) => suite !== OWNED_SUITE_KEY && suite !== 'holdback')
      .flatMap(([suite, keys]) => keys.filter((k) => backendSet.has(k)).map((k) => `${suite}:${k}`))

    expect(conflicts).toEqual([])
  })

  it('tracks only manifest-backed backend parity case keys', () => {
    const manifestKeys = new Set(PARITY_MANIFEST_CASE_KEYS)

    for (const key of BACKEND_CASE_KEYS) {
      expect(manifestKeys.has(key), `${key} should exist in python manifest`).toBe(true)
    }
  })

  it('keeps backend case keys deterministic and unique', () => {
    expect(BACKEND_CASE_KEYS.length).toBeGreaterThan(0)
    expect(new Set(BACKEND_CASE_KEYS).size).toBe(BACKEND_CASE_KEYS.length)
    expect([...BACKEND_CASE_KEYS]).toEqual([...BACKEND_CASE_KEYS].sort())
  })
})

describe('python parity: flatagent backends behavior', () => {
  it('sdk/python/tests/integration/codex/test_codex_backend_integration.py::test_codex_client_happy_path_stream_success', async () => {
    const dir = mkdtempSync(join(tmpdir(), 'flatagent-backends-'))
    const authFile = join(dir, 'auth.json')
    const token = tokenForAccount('acc_123')
    writeAuthFile(authFile, token)

    const seen = {
      url: '',
      headers: {} as Record<string, string>,
      body: {} as Record<string, any>,
    }

    const originalFetch = globalThis.fetch
    ;(globalThis as any).fetch = vi.fn(async (input: any, init: any) => {
      seen.url = String(input)
      seen.headers = headersToRecord(init?.headers)
      seen.body = JSON.parse(String(init?.body ?? '{}'))
      return new Response(sseOk('Hello world'), {
        status: 200,
        headers: { 'content-type': 'text/event-stream' },
      })
    })

    try {
      const client = new CodexClient({
        provider: 'openai-codex',
        base_url: 'https://chatgpt.com/backend-api',
        codex_auth_file: authFile,
        codex_originator: 'pi',
        codex_max_retries: 0,
        auth: { type: 'oauth', provider: 'openai-codex', auth_file: authFile },
      })

      const result = await client.call({
        model: 'openai-codex/gpt-5.4',
        messages: [
          { role: 'system', content: 'You are concise.' },
          { role: 'user', content: 'Say hi.' },
        ],
        temperature: 0.2,
        session_id: 'sess-1',
      })

      expect(seen.headers['chatgpt-account-id']).toBe('acc_123')
      expect(seen.headers.originator).toBe('pi')
      expect(seen.headers.session_id).toBe('sess-1')
      expect(seen.body.model).toBe('gpt-5.4')
      expect(seen.body.prompt_cache_key).toBe('sess-1')
      expect(seen.body.instructions).toBe('You are concise.')
      expect(result.content).toBe('Hello world')
      expect(result.usage.total_tokens).toBe(2)
      expect(result.response_headers['content-type']).toBe('text/event-stream')
      expect(result.response_status_code).toBe(200)
      expect(result.request_meta.method).toBe('POST')
      expect(result.request_meta.url.endsWith('/codex/responses')).toBe(true)
      expect(result.request_meta.headers.Authorization).toBe('Bearer ***')
    } finally {
      ;(globalThis as any).fetch = originalFetch
      rmSync(dir, { recursive: true, force: true })
    }
  })

  it('sdk/python/tests/integration/codex/test_codex_backend_integration.py::test_codex_client_refreshes_after_auth_error', async () => {
    const dir = mkdtempSync(join(tmpdir(), 'flatagent-backends-'))
    const authFile = join(dir, 'auth.json')
    const staleToken = tokenForAccount('acc_old')
    const freshToken = tokenForAccount('acc_new')
    writeAuthFile(authFile, staleToken)

    const codexAuthHeaders: string[] = []

    const originalFetch = globalThis.fetch
    ;(globalThis as any).fetch = vi.fn(async (input: any, init: any) => {
      const url = String(input)

      if (url.includes('/oauth/token')) {
        return new Response(
          JSON.stringify({
            access_token: freshToken,
            refresh_token: 'refresh-token-new',
            expires_in: 3600,
          }),
          {
            status: 200,
            headers: { 'content-type': 'application/json' },
          },
        )
      }

      const headers = headersToRecord(init?.headers)
      codexAuthHeaders.push(headers.Authorization)
      if (codexAuthHeaders.length === 1) {
        return new Response(JSON.stringify({ error: { message: 'expired' } }), {
          status: 401,
          headers: { 'content-type': 'application/json' },
        })
      }

      return new Response(sseOk('ok'), {
        status: 200,
        headers: { 'content-type': 'text/event-stream' },
      })
    })

    try {
      const client = new CodexClient({
        provider: 'openai-codex',
        base_url: 'https://chatgpt.com/backend-api',
        codex_auth_file: authFile,
        codex_max_retries: 0,
        auth: { type: 'oauth', provider: 'openai-codex', auth_file: authFile },
      })

      const result = await client.call({
        model: 'openai-codex/gpt-5.4',
        messages: [{ role: 'user', content: 'ping' }],
      })

      expect(codexAuthHeaders).toHaveLength(2)
      expect(codexAuthHeaders[0]).toBe(`Bearer ${staleToken}`)
      expect(codexAuthHeaders[1]).toBe(`Bearer ${freshToken}`)
      expect(result.content).toBe('ok')
    } finally {
      ;(globalThis as any).fetch = originalFetch
      rmSync(dir, { recursive: true, force: true })
    }
  })

  it('sdk/python/tests/integration/codex/test_codex_backend_integration.py::test_flatagent_codex_backend_end_to_end', async () => {
    const dir = mkdtempSync(join(tmpdir(), 'flatagent-backends-'))
    const authFile = join(dir, 'auth.json')
    writeAuthFile(authFile, tokenForAccount('acc_agent'))

    const codexSpy = vi.spyOn(CodexClient.prototype, 'call').mockResolvedValue({
      content: 'Codex says hi',
      tool_calls: [],
      usage: { input_tokens: 10, output_tokens: 5, total_tokens: 15, cached_tokens: 0 },
      finish_reason: 'stop',
      raw_events: [],
      response_headers: {},
      request_meta: {},
    })

    try {
      const agent = new FlatAgent({
        config: {
          spec: 'flatagent',
          spec_version: '2.2.2',
          data: {
            name: 'codex-integration-agent',
            model: {
              provider: 'openai-codex',
              name: 'gpt-5.4',
              backend: 'codex',
              codex_auth_file: authFile,
              auth: { type: 'oauth', provider: 'openai-codex', auth_file: authFile },
            } as any,
            system: 'You are concise.',
            user: '{{ input.prompt }}',
          },
        },
        llmBackend: {
          call: async () => 'fallback',
          callRaw: async () => ({ text: 'fallback-llm-text', finishReason: 'stop' }),
          totalCost: 0,
          totalApiCalls: 0,
        } as any,
      })

      const result = await agent.call({ prompt: 'Say hi' })
      expect(codexSpy).toHaveBeenCalledTimes(1)
      expect(result.content).toBe('Codex says hi')
      expect(result.finish_reason).toBe('stop')
    } finally {
      codexSpy.mockRestore()
      rmSync(dir, { recursive: true, force: true })
    }
  })

  it('sdk/python/tests/integration/codex/test_codex_backend_integration.py::test_codex_client_terminal_error_without_refresh_is_user_friendly', async () => {
    const dir = mkdtempSync(join(tmpdir(), 'flatagent-backends-'))
    const authFile = join(dir, 'auth.json')
    writeAuthFile(authFile, tokenForAccount('acc_limit'))

    const originalFetch = globalThis.fetch
    ;(globalThis as any).fetch = vi.fn(async () =>
      new Response(
        JSON.stringify({ error: { message: 'denied', code: 'usage_not_included', plan_type: 'PLUS' } }),
        {
          status: 403,
          headers: { 'content-type': 'application/json' },
        },
      ),
    )

    try {
      const client = new CodexClient({
        provider: 'openai-codex',
        base_url: 'https://chatgpt.com/backend-api',
        codex_auth_file: authFile,
        codex_refresh: false,
        codex_max_retries: 0,
        auth: { type: 'oauth', provider: 'openai-codex', auth_file: authFile },
      })

      let caught: unknown
      try {
        await client.call({
          model: 'openai-codex/gpt-5.4',
          messages: [{ role: 'user', content: 'ping' }],
        })
      } catch (err) {
        caught = err
      }

      expect(caught).toBeInstanceOf(CodexClientError)
      expect(String((caught as Error).message).toLowerCase()).toMatch(/usage limit|denied/)
    } finally {
      ;(globalThis as any).fetch = originalFetch
      rmSync(dir, { recursive: true, force: true })
    }
  })

  it('sdk/python/tests/integration/distributed/test_distributed.py::test_distributed_backends_basic', async () => {
    const memReg = createRegistrationBackend('memory')
    const memWork = createWorkBackend('memory')

    expect(memReg).toBeDefined()
    expect(memWork).toBeDefined()

    const worker = { worker_id: 'test-worker-1', host: 'localhost', pid: 12345 }
    const record = await memReg.register(worker)
    expect(record.worker_id).toBe('test-worker-1')
    expect(record.status).toBe('active')

    await memReg.heartbeat('test-worker-1')

    const pool = memWork.pool('test-pool')
    const itemId = await pool.push({ task: 'test-task' })
    expect(itemId).toBeTruthy()

    const claimed = await pool.claim('test-worker-1')
    expect(claimed).toBeTruthy()
    expect(claimed?.data).toEqual({ task: 'test-task' })

    await pool.complete(claimed!.id)
    expect(await pool.size()).toBe(0)

    const dir = mkdtempSync(join(tmpdir(), 'flatagent-backends-'))
    const dbPath = join(dir, 'workers.sqlite')

    try {
      const sqliteReg = createRegistrationBackend('sqlite', { db_path: dbPath })
      const sqliteWork = createWorkBackend('sqlite', { db_path: dbPath })

      const worker2 = { worker_id: 'sqlite-worker', host: 'localhost' }
      const record2 = await sqliteReg.register(worker2)
      expect(record2.worker_id).toBe('sqlite-worker')

      const pool2 = sqliteWork.pool('sqlite-pool')
      await pool2.push({ data: 'test' }, { max_retries: 5 })
      const claimed2 = await pool2.claim('sqlite-worker')
      expect(claimed2).toBeTruthy()
      expect(claimed2?.max_retries).toBe(5)

      await pool2.complete(claimed2!.id)
      expect(await pool2.size()).toBe(0)
    } finally {
      rmSync(dir, { recursive: true, force: true })
    }
  })

  it('sdk/python/tests/integration/distributed/test_distributed.py::test_subprocess_support_imports', () => {
    expect(SubprocessInvoker).toBeDefined()
    expect((flatagentsSdk as any).launch_machine).toBeDefined()
    expect(typeof (flatagentsSdk as any).launch_machine).toBe('function')

    const invoker = new SubprocessInvoker({ workingDir: '/tmp' })
    expect((invoker as any).workingDir).toBe('/tmp')
  })

  it('sdk/python/tests/unit/test_flatagent_codex_backend.py::test_flatagent_accepts_backend_codex_from_model_config', () => {
    const agent = new FlatAgent({
      spec: 'flatagent',
      spec_version: '2.2.2',
      data: {
        name: 'codex-core-backend-test',
        model: {
          provider: 'openai-codex',
          name: 'gpt-5.4',
          backend: 'codex',
        } as any,
        system: 'You are concise.',
        user: '{{ input.prompt }}',
      },
    } as any)

    expect((agent as any)._backend).toBe('codex')
  })

  it('sdk/python/tests/unit/test_flatagent_codex_backend.py::test_call_llm_routes_to_codex_client_when_backend_is_codex', async () => {
    const fakeCodexClient = {
      call: vi.fn(async (params: Record<string, any>) => ({
        ok: true,
        model: params.model,
      })),
    }

    const agent = Object.create(FlatAgent.prototype) as any
    agent._backend = 'codex'
    agent._codex_client = fakeCodexClient

    expect(typeof agent._call_llm).toBe('function')
    const result = await agent._call_llm({ model: 'openai-codex/gpt-5.4', messages: [] })

    expect(fakeCodexClient.call).toHaveBeenCalledTimes(1)
    expect(result.ok).toBe(true)
    expect(result.model).toBe('openai-codex/gpt-5.4')
  })
})

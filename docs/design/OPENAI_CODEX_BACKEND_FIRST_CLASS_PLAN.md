# OpenAI Codex as a First-Class FlatAgents Backend (Option A)

## Status
Proposed

## Goal
Promote the current standalone example (`sdk/examples/openai_codex_oauth/python/`) into a **built-in FlatAgents backend** (`backend: codex`) without introducing a generic extension/plugin system yet.

This is the fastest path to productionizing ChatGPT Plus/Pro OAuth-backed Codex calls in core FlatAgents.

---

## Scope

### In scope
1. Built-in backend: `backend: codex` in `FlatAgent` runtime.
2. Core Codex client (SSE transport only).
3. Core auth handling for `openai-codex` credentials from auth.json.
4. OAuth refresh support with safe persistence.
5. Login helper command/script for acquiring creds (PKCE + callback + manual fallback).
6. Tests + docs + migration notes.

### Out of scope
1. Generic extension framework.
2. WebSocket transport.
3. Multi-provider OAuth abstraction beyond what is needed for `openai-codex`.
4. Broad schema redesign.

---

## Current State
- Working vertical slice exists in example folder:
  - `codex_flatagent.py`
  - `openai_codex_client.py`
  - `openai_codex_auth.py`
  - `openai_codex_login.py`
- Behavior is validated with unit + integration tests.
- `run.sh -- --login` supports OAuth login flow and writes credentials.

---

## Proposed Core Design

## 1) Runtime integration in FlatAgent
Add native codex backend path in `sdk/python/flatagents/flatagents/flatagent.py`:

- `_init_backend()`
  - accept `self._backend == "codex"`
  - initialize codex client instance
- `_call_llm(params)`
  - route to codex client when backend is codex
  - preserve existing litellm/aisuite behavior unchanged

### Backend selection behavior
- Keep existing precedence:
  1. constructor `backend=...`
  2. `data.model.backend`
  3. auto-detect
- `codex` should be explicit via config/constructor (not auto-detected).

---

## 2) Core Codex client module
Create a core provider module, e.g.:
- `flatagents/providers/openai_codex_client.py`

Responsibilities:
- Build request body with Codex parity fields:
  - `model`, `store:false`, `stream:true`, `instructions`, `input`
  - `text.verbosity`, `include:["reasoning.encrypted_content"]`
  - `prompt_cache_key` from `session_id`
  - optional `tools`, `reasoning`, `service_tier`, `temperature`
- Build headers:
  - `Authorization: Bearer ...`
  - `chatgpt-account-id`
  - `OpenAI-Beta: responses=experimental`
  - `originator` (default `pi`)
  - `accept: text/event-stream`, `content-type: application/json`
  - optional `session_id`
- Retry/backoff:
  - retry on `429,500,502,503,504`
  - exponential backoff, default max retries 3
- Parse SSE stream and map to FlatAgent-compatible response object
  (`choices[0].message.content`, `tool_calls`, `usage`, `finish_reason`).

---

## 3) Core auth module
Create:
- `flatagents/providers/openai_codex_auth.py`

Responsibilities:
- Read/write auth credentials for provider `openai-codex`.
- Resolve auth path from:
  1. model config (`codex_auth_file` / auth field)
  2. env (`FLATAGENTS_CODEX_AUTH_FILE`)
  3. default (`~/.pi/agent/auth.json`) for compatibility
- Extract account id from JWT claim path:
  - `payload["https://api.openai.com/auth"].chatgpt_account_id`
- Refresh flow:
  - `POST https://auth.openai.com/oauth/token`
  - `grant_type=refresh_token`, `refresh_token`, `client_id`
- Persistence safety:
  - lock during write
  - atomic replace
  - preserve unrelated providers
  - `0600` permissions

Refresh policy parity:
- If `expires` is reached, refresh **before** request dispatch.
- If refresh fails, re-read auth store once to detect another process refresh.
- Keep `401/403` refresh-and-retry as fallback safety.

---

## 4) Login helper
Add a minimal core login entrypoint (module/script) reusing example logic:
- PKCE auth URL generation
- localhost callback on `127.0.0.1:1455`
- manual paste fallback
- save credential object under `openai-codex`

This can be exposed as:
- `python -m flatagents.providers.openai_codex_login`
- and/or documented script wrapper

---

## 5) Config & schema updates (**profiles.d.ts + flatagent.d.ts first-class**)
This plan must explicitly update canonical specs, because schema validation is derived from root `.d.ts` files.

### Source-of-truth files to update
1. `/profiles.d.ts` (model profiles)
2. `/flatagent.d.ts` (inline agent model config)

Derived assets are generated from these files (`scripts/generate-spec-assets.ts`) and copied into SDK assets.

### Required additive fields (both profile + inline model config)
For `ModelProfileConfig` in `profiles.d.ts` and `ModelConfig` in `flatagent.d.ts`:
- `backend?: "litellm" | "aisuite" | "codex"`
- `api?: string` (or narrow union including `"openai-codex-responses"`)
- `auth?: {
    type: "oauth" | "api_key";
    provider?: string;
    auth_file?: string;
  }`
- codex runtime hints used by client (optional):
  - `codex_auth_file?: string`
  - `codex_originator?: string`
  - `codex_transport?: "sse"`
  - `codex_refresh?: boolean`
  - `codex_timeout_seconds?: number`
  - `codex_max_retries?: number`

### Versioning + generation requirements
Because specs are lockstep-versioned in this repo:
1. Bump `SPEC_VERSION` consistently in changed root specs (and any required companions per release policy).
2. Regenerate derived assets:
   - `npx tsx scripts/generate-spec-assets.ts`
3. Ensure generated assets are updated in:
   - `assets/*`
   - `sdk/python/flatagents/flatagents/assets/*`
   - `sdk/js/schemas/*`
4. Keep docs/examples using the new fields in sync.

Without this, `profiles.schema.json`/`flatagent.schema.json` will reject Codex fields even if runtime code supports them.

---

## Migration Path (from current example)
1. Move/reuse logic from example modules into `flatagents/providers/*`.
2. Keep example as thin wrapper that imports core modules.
3. Add deprecation note in example modules after one release cycle.

---

## Testing Plan

## Unit
- auth file parsing, missing provider, bad token, JWT extraction
- refresh success/failure
- auth file write safety (preserve unrelated keys)
- request/header construction
- SSE parsing and response adaptation

## Integration (mock HTTP/SSE)
- happy path stream
- `429` retry then success
- stale token `401` -> refresh -> success
- refresh failure path
- terminal errors (usage/rate/auth friendly messaging)

## Regression
- litellm and aisuite paths unchanged
- non-codex profiles unaffected

---

## Risks & Mitigations
1. **Schema friction** (strict profile schema)
   - Mitigation: additive schema update, no breaking fields.
2. **Auth path confusion** (pi file vs project-local)
   - Mitigation: clear precedence and docs; recommend explicit `codex_auth_file`.
3. **Concurrency during refresh**
   - Mitigation: lock + atomic write + re-read-before-write pattern.
4. **Transport drift from pi**
   - Mitigation: keep parity constants and event handling tested.

---

## Delivery Estimate (Option A)

### Engineering time
- Core integration + module move: **1.5–2.5 days**
- Auth/login hardening: **1–1.5 days**
- Tests and regression suite: **1–1.5 days**
- Docs/schema cleanup: **0.5–1 day**

**Total: 3–5 engineering days**

### Calendar time (with review/iteration)
**~1 week**

---

## Acceptance Criteria
1. `backend: codex` works in core FlatAgent without subclass hacks.
2. OAuth creds load + refresh correctly from configured auth file.
3. SSE responses map through existing FlatAgent result path (content, usage, tool calls).
4. Login helper can populate credentials for `openai-codex`.
5. Existing backends remain behaviorally unchanged.

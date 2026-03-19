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
5. Any changes to the existing example implementation.

---

## Current State
- Working vertical slice exists in example folder:
  - `codex_flatagent.py`
  - `openai_codex_client.py`
  - `openai_codex_auth.py`
  - `openai_codex_login.py`
  - `openai_codex_types.py`
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
Create core provider modules:
- `flatagents/providers/openai_codex_client.py`
- `flatagents/providers/openai_codex_types.py`

Responsibilities:
- Build request body with Codex parity fields:
  - `model`, `store:false`, `stream:true`, `instructions`, `input`
  - `text.verbosity` (default `"medium"`), `include:["reasoning.encrypted_content"]`
  - `prompt_cache_key` from `session_id`
  - optional `tools`, `reasoning`, `service_tier`, `temperature`
  - `tool_choice:"auto"` and `parallel_tool_calls:true` (fixed defaults in Option A)
- Build headers:
  - `Authorization: Bearer ...`
  - `chatgpt-account-id`
  - `OpenAI-Beta: responses=experimental`
  - `originator` (default `pi`)
  - `User-Agent`
  - `accept: text/event-stream`, `content-type: application/json`
  - optional `session_id`
- Retry/backoff:
  - retry on `429,500,502,503,504`
  - exponential backoff, default max retries 3
  - **no jitter in Option A** (simple parity-first behavior)
- Parse SSE stream and map to FlatAgent-compatible response object
  (`choices[0].message.content`, `tool_calls`, `usage`, `finish_reason`).

---

## 3) Core auth module
Create:
- `flatagents/providers/openai_codex_auth.py`

Responsibilities:
- Read/write auth credentials for provider `openai-codex`.
- Resolve auth path with explicit precedence:
  1. `model.oauth.auth_file` (new schema)
  2. `model.codex_auth_file` (legacy)
  3. `model.auth.auth_file` (legacy)
  4. env (`FLATAGENTS_CODEX_AUTH_FILE`)
  5. default (`~/.pi/agent/auth.json`) for compatibility
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

### Schema direction (backend-driven, no required `api` switch)
Routing is determined by `backend: "codex"`. `api` is not required for selection.

#### Explicit additive schema changes
For both `ModelProfileConfig` (`profiles.d.ts`) and `ModelConfig` (`flatagent.d.ts`):
- add backend option:
  - `backend?: "litellm" | "aisuite" | "codex"`
- add optional oauth config block:
  - `oauth?: OAuthConfig`

Add new shared shape in both specs (or equivalent inline type):

```ts
interface OAuthConfig {
  provider?: "openai-codex" | string;   // default openai-codex for backend=codex
  auth_file?: string;                     // default resolver if omitted
  refresh?: boolean;                      // default true
  originator?: string;                    // default "pi"
  timeout_seconds?: number;               // request timeout
  max_retries?: number;                   // retry budget
  token_url?: string;                     // default OpenAI token endpoint
  client_id?: string;                     // default Codex OAuth client id
}
```

Notes:
- `api` may remain optional in schema for compatibility, but runtime does not require it for codex routing.
- `oauth` being optional is acceptable; invalid/insufficient config fails at runtime with actionable errors.

### Runtime mapping changes required for new schema
`flatagent.py` / Codex client should read in this order:
1. `model.oauth.*` (new first-class path)
2. fallback to legacy keys for one migration cycle:
   - `codex_*`
   - `auth.*`

For auth file specifically, enforce:
`oauth.auth_file` → `codex_auth_file` → `auth.auth_file` → env → default.

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

## 6) Explicit code changes (core)

### FlatAgents runtime
- `sdk/python/flatagents/flatagents/flatagent.py`
  - allow `backend == "codex"` in `_init_backend()`
  - route `_call_llm()` to codex client for this backend
  - keep litellm/aisuite paths unchanged

### New core provider modules
- `sdk/python/flatagents/flatagents/providers/openai_codex_client.py`
- `sdk/python/flatagents/flatagents/providers/openai_codex_auth.py`
- `sdk/python/flatagents/flatagents/providers/openai_codex_login.py`
- `sdk/python/flatagents/flatagents/providers/openai_codex_types.py`

### Spec files (source of truth)
- `profiles.d.ts`
- `flatagent.d.ts`

### Generated assets (derived)
- `assets/*` generated schema + d.ts assets
- `sdk/python/flatagents/flatagents/assets/*`
- `sdk/js/schemas/*`

### Tests/docs
- Add codex backend tests under SDK Python tests
- Update `README.md` + `sdk/python/flatagents/MACHINES.md` snippets for `backend: codex` + `oauth`

### Non-goal for this Option A doc
- **No required changes to the existing example implementation** to adopt this plan.
- Example code/config/tests remain untouched in this phase.

---

## Migration Path (from current example)
1. Copy/reuse logic from example modules into `flatagents/providers/*`.
2. Keep the existing example unchanged and fully standalone.
3. Optionally evaluate wrapper/deprecation strategy in a later, separate proposal.

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
- expired token -> pre-request refresh -> success
- `401/403` fallback refresh -> success
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
   - Mitigation: explicit precedence rules and docs; recommend explicit `oauth.auth_file`.
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
6. Existing example remains unchanged and continues to run independently.

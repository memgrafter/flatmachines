# Plan: Claude Code OAuth Backend for FlatAgents Python SDK ✅ IMPLEMENTED

## Summary

Add a `claude_code` backend to the FlatAgents Python SDK that authenticates via Anthropic's Claude Code OAuth flow (using claude.ai + console.anthropic.com OAuth), identical to how the existing `codex` backend authenticates via OpenAI's ChatGPT OAuth flow. This lets users with Claude Pro/Max subscriptions use their subscription quota through FlatAgents without needing API keys.

---

## Reference Implementations

### 1. Pi-mono (TypeScript) — The Source of Truth

The working implementation lives in `~/clones/pi-mono/packages/ai/`:

| File | Role |
|------|------|
| `src/utils/oauth/anthropic.ts` | OAuth flow: PKCE + authorization code exchange |
| `src/utils/oauth/types.ts` | `OAuthProviderInterface`, `OAuthCredentials` |
| `src/utils/oauth/pkce.ts` | PKCE code verifier/challenge generation |
| `src/providers/anthropic.ts` | Anthropic API client with OAuth-aware request building |
| `packages/coding-agent/src/core/auth-storage.ts` | Credential persistence with file locking |

**Key OAuth details from `anthropic.ts`:**
- **Client ID**: `9d1c250a-e61b-44d9-88ed-5944d1962f5e` (base64-encoded in source)
- **Authorize URL**: `https://claude.ai/oauth/authorize`
- **Token URL**: `https://console.anthropic.com/v1/oauth/token`
- **Redirect URI**: `https://console.anthropic.com/oauth/code/callback`
- **Scopes**: `org:create_api_key user:profile user:inference`
- **Flow**: Authorization Code + PKCE (no local callback server; user pastes `code#state`)
- **Token format**: Access tokens contain `sk-ant-oat` prefix

**Key API request details from `providers/anthropic.ts`:**

When `isOAuthToken(apiKey)` is true (token contains `sk-ant-oat`), the client:
1. Uses **Bearer auth** (`authToken` not `apiKey`) via `Anthropic({ apiKey: null, authToken: token })` 
2. Sets special **beta headers**: `anthropic-beta: claude-code-20250219,oauth-2025-04-20,fine-grained-tool-streaming-2025-05-14`
3. Sets **user-agent**: `claude-cli/2.1.62`
4. Sets **x-app**: `cli`
5. **Prepends a system prompt**: `"You are Claude Code, Anthropic's official CLI for Claude."`
6. **Renames tools** to match Claude Code canonical names (e.g., `read` → `Read`, `bash` → `Bash`)
7. **Reverse-maps tool names** in responses back to original names
8. Uses standard Anthropic Messages API at `https://api.anthropic.com`

### 2. Existing Codex Backend (Python) — The Pattern to Follow

| File | Role |
|------|------|
| `providers/openai_codex_auth.py` | Auth store, token refresh, credential loading |
| `providers/openai_codex_client.py` | SSE client, request building, retry logic |
| `providers/openai_codex_login.py` | Interactive login flow with local callback server |
| `providers/openai_codex_types.py` | Dataclasses for credentials, results, tool calls |
| `flatagent.py` | Backend integration (`_init_backend`, `_call_llm`, `_adapt_codex_result`) |

**Codex pattern**: Custom SSE transport to a proprietary API (`chatgpt.com/backend-api/codex/responses`), requiring account ID extraction from JWT, custom headers.

---

## Architecture Differences: Codex vs Claude Code

| Aspect | Codex Backend | Claude Code Backend |
|--------|--------------|-------------------|
| **API** | Custom SSE endpoint (`/codex/responses`) | Standard Anthropic Messages API |
| **Auth** | Bearer + `chatgpt-account-id` header | Bearer (via `authToken`, not `apiKey`) |
| **Transport** | Raw SSE parsing | Anthropic SDK streaming (or raw httpx) |
| **Tool names** | Pass-through | Must rename to Claude Code canonical names |
| **System prompt** | Instructions field | Must prepend Claude Code identity |
| **Token format** | JWT with embedded account ID | `sk-ant-oat*` prefix tokens |
| **Login flow** | Local callback server on port 1455 | User pastes `code#state` (no local server) |
| **Token URL** | `auth.openai.com/oauth/token` | `console.anthropic.com/v1/oauth/token` |

**Critical insight**: The Claude Code backend can use the standard `litellm` or native `anthropic` SDK for the actual API call — it just needs to:
1. Swap the API key for a Bearer auth token
2. Add the right headers
3. Inject the Claude Code system prompt identity
4. Rename tools to/from Claude Code canonical names

This means the Claude Code backend is **simpler** than Codex — no custom SSE parsing needed.

---

## Implementation Plan

### Phase 1: Auth Module (`providers/anthropic_claude_code_auth.py`)

Mirror the structure of `openai_codex_auth.py`:

```python
# Constants
CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
AUTHORIZE_URL = "https://claude.ai/oauth/authorize"
TOKEN_URL = "https://console.anthropic.com/v1/oauth/token"
REDIRECT_URI = "https://console.anthropic.com/oauth/code/callback"
SCOPES = "org:create_api_key user:profile user:inference"
DEFAULT_PROVIDER = "anthropic"  # key in auth.json
```

**Functions to implement:**
- `resolve_auth_file()` — Reuse existing from `openai_codex_auth.py` (shared `PiAuthStore`)
- `is_claude_code_oauth_token(token: str) -> bool` — Check for `sk-ant-oat` prefix
- `is_expired(expires_ms: int, skew_ms: int) -> bool` — Reuse existing
- `refresh_anthropic_token(refresh_token: str, ...) -> Dict` — POST to TOKEN_URL with `grant_type=refresh_token`
- `load_claude_code_credential(store, provider) -> ClaudeCodeOAuthCredential`
- `refresh_claude_code_credential(store, provider, ...) -> ClaudeCodeOAuthCredential`

**Key difference from Codex**: No JWT decoding needed. No `accountId`. The access token is used directly as a Bearer token.

### Phase 2: Types (`providers/anthropic_claude_code_types.py`)

```python
@dataclass
class ClaudeCodeOAuthCredential:
    access: str
    refresh: str
    expires: int
```

No `account_id` needed (unlike Codex which requires `chatgpt_account_id` from JWT).

### Phase 3: Login Flow (`providers/anthropic_claude_code_login.py`)

Mirror `openai_codex_login.py` but simpler — no local callback server needed:

```python
async def login_anthropic_claude_code(
    *,
    auth_file: str | None = None,
    provider: str = "anthropic",
    open_browser: bool = True,
    manual_input_provider: Callable[[], str] | None = None,
) -> ClaudeCodeOAuthCredential:
```

**Flow:**
1. Generate PKCE verifier/challenge (same `generate_pkce()` as Codex)
2. Build authorize URL with params: `code=true`, `client_id`, `response_type=code`, `redirect_uri`, `scope`, `code_challenge`, `code_challenge_method=S256`, `state=verifier`
3. Open browser to authorize URL
4. User completes auth on claude.ai, gets redirected, copies `code#state` 
5. Parse pasted input to extract `code` and `state`
6. Exchange code for tokens: POST to TOKEN_URL with `grant_type=authorization_code`, JSON body (not form-encoded like Codex)
7. Calculate expiry: `now + expires_in * 1000 - 5min buffer`
8. Save to `auth.json` under provider key `"anthropic"`

**Important difference**: Anthropic uses `Content-Type: application/json` for token exchange (not `application/x-www-form-urlencoded` like OpenAI).

### Phase 4: Client (`providers/anthropic_claude_code_client.py`)

This is the main client that makes API calls. Unlike Codex, it uses the **standard Anthropic Messages API** with OAuth modifications.

```python
CLAUDE_CODE_VERSION = "2.1.62"  # Keep in sync with pi-mono
CLAUDE_CODE_TOOLS = [
    "Read", "Write", "Edit", "Bash", "Grep", "Glob",
    "AskUserQuestion", "EnterPlanMode", "ExitPlanMode",
    "KillShell", "NotebookEdit", "Skill", "Task",
    "TaskOutput", "TodoWrite", "WebFetch", "WebSearch",
]

class ClaudeCodeClient:
    def __init__(self, model_config, *, config_dir=None):
        # Read oauth config from model_config (same pattern as CodexClient)
        # Initialize PiAuthStore
        pass
    
    async def call(self, params: Dict) -> ClaudeCodeResult:
        # 1. Load credential from auth store
        # 2. Refresh if expired (with cross-process safety)
        # 3. Build Anthropic API request with OAuth headers
        # 4. Rename tools to Claude Code names
        # 5. Prepend Claude Code identity system prompt
        # 6. Call Anthropic Messages API
        # 7. Rename tools back in response
        # 8. Handle 401/403 with refresh+retry
        pass
```

**Two implementation strategies** (choose one):

#### Option A: Use `anthropic` SDK (Recommended)
```python
from anthropic import Anthropic

client = Anthropic(
    api_key=None,          # MUST be None for OAuth
    auth_token=access_token,
    base_url="https://api.anthropic.com",
    default_headers={
        "anthropic-beta": "claude-code-20250219,oauth-2025-04-20,fine-grained-tool-streaming-2025-05-14",
        "user-agent": f"claude-cli/{CLAUDE_CODE_VERSION}",
        "x-app": "cli",
        "anthropic-dangerous-direct-browser-access": "true",
    },
)
```
- **Pro**: Handles streaming, types, error mapping
- **Con**: Adds `anthropic` SDK as dependency

#### Option B: Use `httpx` directly (like Codex does)
- **Pro**: No new dependency, consistent with Codex pattern
- **Con**: Must handle streaming ourselves, but we'd parse SSE just like Codex

**Recommendation**: Option A if `anthropic` SDK is already a dependency (check); otherwise Option B for consistency with Codex.

**Actually, better approach**: Since the Claude Code backend uses the standard Messages API, we can **delegate to litellm** with header injection. The client just needs to:
1. Load/refresh the OAuth credential
2. Inject the required headers
3. Rename tools
4. Add the Claude Code identity system prompt
5. Pass through to litellm's `anthropic/model-name` call

This makes it even simpler — no custom transport at all.

#### Option C: Thin wrapper over litellm (Simplest)
```python
class ClaudeCodeClient:
    async def call(self, params):
        credential = self._get_valid_credential()
        
        # Inject OAuth headers
        params["extra_headers"] = {
            "anthropic-beta": "claude-code-20250219,oauth-2025-04-20",
            "user-agent": f"claude-cli/{CLAUDE_CODE_VERSION}",
            "x-app": "cli",
        }
        
        # Use Bearer auth via litellm
        params["api_key"] = credential.access
        
        # Prepend Claude Code identity
        params["messages"] = self._inject_system_prompt(params["messages"])
        
        # Rename tools
        params["tools"] = self._rename_tools_to_cc(params["tools"])
        
        result = await litellm.acompletion(**params)
        
        # Rename tools back in response
        return self._rename_tools_from_cc(result)
```

**Problem with Option C**: litellm may not handle `authToken` vs `apiKey` correctly for Anthropic. Need to verify.

**Final recommendation: Option B** — Use `httpx` directly with Anthropic Messages API, consistent with Codex pattern. We have full control over headers and auth.

### Phase 5: Integrate into `flatagent.py`

Add `claude_code` as an explicit-only backend (same pattern as `codex`):

```python
# In _init_backend():
elif self._backend == "claude_code":
    self._claude_code_client = ClaudeCodeClient(
        self._model_config_raw, config_dir=self._config_dir
    )

# In _call_llm():
if self._backend == "claude_code":
    result = await self._claude_code_client.call(params)
    if isinstance(result, ClaudeCodeResult):
        return self._adapt_claude_code_result(result)
    return result
```

### Phase 6: Update Spec (`flatagent.d.ts`)

```typescript
export interface OAuthConfig {
  provider?: "openai-codex" | "anthropic" | string;
  // ... existing fields ...
}

export interface ModelConfig {
  // ...
  backend?: "litellm" | "aisuite" | "codex" | "claude_code";
  // ...
}
```

### Phase 7: Update `__init__.py` exports

```python
from .anthropic_claude_code_auth import ClaudeCodeAuthError
from .anthropic_claude_code_client import ClaudeCodeClient, ClaudeCodeClientError
from .anthropic_claude_code_types import ClaudeCodeOAuthCredential, ClaudeCodeResult
```

### Phase 8: Tests

Mirror the Codex test structure:

| Test File | Coverage |
|-----------|----------|
| `test_anthropic_claude_code_auth.py` | Token refresh, credential loading, expiry checks |
| `test_anthropic_claude_code_client_unit.py` | Request building, header injection, tool renaming, SSE parsing |
| `test_anthropic_claude_code_login.py` | PKCE generation, auth URL building, code exchange |
| `test_flatagent_claude_code_backend.py` | Backend selection, result adaptation |

### Phase 9: Login CLI

Add a CLI entry point (like `codex-login`):

```python
# In openai_codex_login.py pattern:
def cli() -> None:
    parser = argparse.ArgumentParser(description="Anthropic Claude Code OAuth login")
    # ...
    asyncio.run(login_anthropic_claude_code(...))
```

Add to `pyproject.toml`:
```toml
[project.scripts]
claude-code-login = "flatagents.providers.anthropic_claude_code_login:cli"
```

---

## Files to Create/Modify

### New Files
1. `sdk/python/flatagents/flatagents/providers/anthropic_claude_code_types.py`
2. `sdk/python/flatagents/flatagents/providers/anthropic_claude_code_auth.py`
3. `sdk/python/flatagents/flatagents/providers/anthropic_claude_code_login.py`
4. `sdk/python/flatagents/flatagents/providers/anthropic_claude_code_client.py`
5. `sdk/python/tests/unit/test_anthropic_claude_code_auth.py`
6. `sdk/python/tests/unit/test_anthropic_claude_code_client_unit.py`
7. `sdk/python/tests/unit/test_anthropic_claude_code_login.py`
8. `sdk/python/tests/unit/test_flatagent_claude_code_backend.py`

### Modified Files
1. `sdk/python/flatagents/flatagents/providers/__init__.py` — Add exports
2. `sdk/python/flatagents/flatagents/flatagent.py` — Add `claude_code` backend
3. `flatagent.d.ts` — Add `claude_code` to backend enum, `anthropic` to OAuthConfig provider
4. `AGENTS.md` — Document Claude Code backend behavior

---

## Usage Example

### Profile-based (recommended)
```yaml
# profiles.yml
spec: flatprofiles
spec_version: "2.3.0"
data:
  model_profiles:
    claude-sub:
      provider: anthropic
      name: claude-sonnet-4-20250514
      backend: claude_code
      oauth:
        provider: anthropic
        auth_file: ~/.pi/agent/auth.json
```

### Inline agent config
```yaml
spec: flatagent
spec_version: "2.3.0"
data:
  model:
    provider: anthropic
    name: claude-sonnet-4-20250514
    backend: claude_code
    oauth:
      provider: anthropic
```

### Login
```bash
# Login first
claude-code-login

# Or with options
claude-code-login --auth-file /custom/path/auth.json --no-browser
```

---

## Key Implementation Details

### Tool Name Mapping
The Claude Code OAuth endpoint requires tools to use Claude Code canonical casing. The client must:

1. **Before request**: Map tool names case-insensitively to Claude Code names
   - `read` → `Read`, `bash` → `Bash`, `edit` → `Edit`, etc.
   - Non-matching names pass through unchanged

2. **After response**: Map tool names back to the original caller's names
   - Find matching tool by case-insensitive comparison against the original tool list

### System Prompt Injection
The OAuth endpoint **requires** a Claude Code identity prefix:
```
"You are Claude Code, Anthropic's official CLI for Claude."
```
This must be prepended as the first system message, with the user's actual system prompt following.

### Token Refresh Strategy
Same as Codex:
1. Pre-request: Check expiry, refresh if needed
2. Cross-process safety: Re-read auth file if refresh fails (another process may have refreshed)
3. On 401/403: Refresh token and retry once
4. Expiry buffer: 5 minutes (300,000ms) subtracted from `expires_in`

### Shared Infrastructure
Reuse from Codex:
- `PiAuthStore` — File-based credential storage with locking
- `resolve_auth_file()` — Auth file path resolution chain
- `is_expired()` — Expiry check
- `generate_pkce()` — PKCE verifier/challenge generation

---

## Open Questions

1. **Anthropic SDK dependency**: Should we require `anthropic` SDK or use raw `httpx`? Raw `httpx` is more consistent with the Codex pattern and avoids a new dependency.

2. **Streaming**: Should the Claude Code backend support streaming? The Codex backend currently consumes the full SSE payload before returning. Same approach here? Or should we support streaming since the Anthropic Messages API supports it natively?

3. **Claude Code version tracking**: The `user-agent` header includes a Claude Code version (`claude-cli/2.1.62`). How do we keep this in sync? Pin it and update periodically?

4. **Beta header stability**: The `anthropic-beta: claude-code-20250219,oauth-2025-04-20` headers may change. Should these be configurable?

5. **Auth file sharing**: Since both Codex and Claude Code use the same `auth.json` (with different provider keys), this should just work. Verify no conflicts with `PiAuthStore` locking.

6. **Interleaved thinking beta**: Pi-mono adds `interleaved-thinking-2025-05-14` beta header for non-adaptive-thinking models. Should we include this?

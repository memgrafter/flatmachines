# 1-Pager: Add GitHub Copilot as a First-Class FlatAgents Provider (OAuth + Inference)

**Timestamp:** 2026-04-08T17:24:35  
**Updated:** 2026-04-08T22:10:16  
**Status:** Proposed

## Summary

Add `github-copilot` as a first-class **FlatAgents Python provider/backend** with:

1. OAuth auth lifecycle (device-code login + refresh + auth.json persistence)
2. Direct inference client support

Then provide a **small example `run.sh`** in `sdk/examples/github_copilot_oauth/python/` that demonstrates how applications can wire auth/login for their own FlatMachines/FlatAgents usage.

This is based on proven behavior in `~/clones/pi-mono`.

Credentials storage target:

`~/.agents/flatmachines/auth.json`

---

## Goals

1. Accept `github-copilot` as an OAuth credential provider in FlatAgents Python.
2. Add a first-class `copilot` backend in FlatAgents Python (similar to codex-style first-class path).
3. Support a Copilot profile in `profiles.yml`.
4. Support **device code login only** (no callback server/browser redirect mode).
5. Persist credentials under `github-copilot` in `~/.agents/flatmachines/auth.json`.
6. Ship a minimal reference `run.sh` example for app-level login usage.

## Non-goals

- No product/frontend login UI in this change.
- No username/password flow.
- No PKCE callback-server flow.
- No generic multi-provider OAuth framework redesign.
- No automatic migration from `~/.pi/agent/auth.json`.

---

## Proposed UX (example-only)

### Login (example script)

```bash
cd sdk/examples/github_copilot_oauth/python
./run.sh --login-copilot
```

Flow:
1. Starts GitHub device authorization flow.
2. User opens verification URL and enters code.
3. Polls until authorized.
4. Exchanges for Copilot token and writes auth file.
5. Prints success and auth file location.

### Run with Copilot profile

```bash
./run.sh --profile copilot
```

The example demonstrates loading/refreshing Copilot credentials and executing an inference call through FlatAgents.

---

## Profile shape (target)

```yaml
spec: flatprofiles
spec_version: "2.5.0"

data:
  model_profiles:
    copilot:
      provider: github-copilot
      backend: copilot
      name: gpt-4o
      base_url: https://api.individual.githubcopilot.com
      oauth:
        provider: github-copilot
        auth_file: ~/.agents/flatmachines/auth.json

  default: copilot
```

Notes:
- `base_url` is a default; runtime may derive better value from token metadata (`proxy-ep`) for parity.
- `oauth` block remains explicit and profile-consistent.

---

## Credential format in `auth.json`

Stored under top-level key `github-copilot`:

```json
{
  "github-copilot": {
    "type": "oauth",
    "refresh": "<github-access-token>",
    "access": "<copilot-session-token>",
    "expires": 1760000000000,
    "enterpriseUrl": "optional-enterprise-domain"
  }
}
```

Parity note: this matches the shape used in `pi-mono` (`refresh`, `access`, `expires`, optional enterprise metadata).

---

## Technical approach (pi-mono parity)

1. Device flow:
   - `POST https://<domain>/login/device/code`
   - Poll `POST https://<domain>/login/oauth/access_token`
   - `grant_type=urn:ietf:params:oauth:grant-type:device_code`
2. Poll behavior:
   - `authorization_pending` => wait current interval
   - `slow_down` => increase interval (+5s)
   - `expired_token` / `access_denied` / unknown => hard fail with clear message
3. Copilot token exchange:
   - `GET https://api.<domain>/copilot_internal/v2/token`
4. Base URL resolution:
   - prefer token `proxy-ep` (`proxy.*` -> `api.*`)
   - fallback `https://copilot-api.<enterprise-domain>`
   - fallback `https://api.individual.githubcopilot.com`
5. Refresh behavior:
   - refresh near expiry (5-minute skew)
   - preserve unrelated auth providers during write
   - lock + atomic writes for multi-process safety
6. Optional parity step:
   - best-effort model enablement: `POST {base_url}/models/{modelId}/policy`
7. Inference behavior:
   - first-class backend client for Copilot requests
   - include required static Copilot headers
   - include dynamic headers (`X-Initiator`, `Openai-Intent`, `Copilot-Vision-Request` for image input)

Implementation boundary:
- **FlatAgents provider/backend code** owns login primitives, refresh, auth storage, and inference calls.
- **Example `run.sh`** shows app-level orchestration and diagnostics patterns.

---

## Planned files to create

### Runtime implementation (no tests)

```text
sdk/
├── examples/
│   └── github_copilot_oauth/
│       ├── README.md
│       ├── config/
│       │   ├── agent.yml
│       │   └── profiles.yml
│       └── python/
│           ├── README.md
│           ├── pyproject.toml
│           └── run.sh
└── python/
    └── flatagents/
        └── flatagents/
            └── providers/
                ├── github_copilot_auth.py
                ├── github_copilot_client.py
                ├── github_copilot_login.py
                └── github_copilot_types.py
```

### Tests

```text
sdk/python/tests/
├── unit/
│   ├── _github_copilot_test_helpers.py
│   ├── test_github_copilot_auth.py
│   ├── test_github_copilot_login.py
│   ├── test_github_copilot_client_unit.py
│   ├── test_github_copilot_client_integration_contract.py
│   └── test_flatagent_github_copilot_backend.py
└── integration/
    └── copilot/
        ├── conftest.py
        ├── run.sh
        ├── test_copilot_backend_integration.py
        └── test_copilot_oauth_live.py
```

---

## Security & reliability

- Create parent directories as needed.
- Use auth file lock + atomic write.
- Preserve unrelated providers in shared auth file.
- File mode `0600` for secrets.
- Never print raw tokens.
- Clear error text for pending/expired/denied device states.

---

## Acceptance criteria

1. FlatAgents can execute with `backend: copilot` and provider `github-copilot`.
2. Device-code login flow works and writes valid `github-copilot` oauth credentials.
3. Refresh works with 5-minute skew and preserves unrelated auth entries.
4. Runtime requests include required Copilot headers and correct base URL resolution.
5. Example `run.sh --profile copilot` completes a real end-to-end inference call.
6. No non-device-code sign-in path is exposed.

---

## Open questions

1. Should model policy enablement (`POST /models/{id}/policy`) be required or best-effort in v1?
2. Should example `run.sh` expose `--auth-file` override for CI/dev portability?
3. Should we include `--check-copilot-auth` diagnostics in v1 example?
4. Enterprise prompt now vs github.com-only default with later enterprise expansion?

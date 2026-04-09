# 1-Pager: Add GitHub Copilot OAuth to Accepted Credentials

**Timestamp:** 2026-04-08T17:24:35  
**Status:** Proposed

## Summary

Add `github-copilot` OAuth credentials as a first-class accepted credential in our FlatAgents-based workflow, with login handled by the plugin `run.sh` (not by core FlatAgents login commands).

This mirrors the existing GitHub Copilot device-code flow already implemented in `~/clones/pi-mono` and keeps profile config shape consistent with `sdk/examples/openai_codex_oauth/config/profiles.yml`.

Credentials will be stored in:

`~/.agents/flatmachines/auth.json`

---

## Goals

1. Accept `github-copilot` as an OAuth credential provider.
2. Support a **Copilot model profile** in `profiles.yml` for FlatAgents usage.
3. Use **device code login only** (no browser callback/local server mode).
4. Implement login orchestration in plugin `run.sh`.
5. Persist credentials under provider key `github-copilot` in `~/.agents/flatmachines/auth.json`.

## Non-goals

- No username/password login.
- No PKCE callback-server login mode.
- No generic multi-provider OAuth framework redesign in this change.
- No migration of existing `~/.pi/agent/auth.json` credentials by default.

---

## Proposed UX

### Login

```bash
./run.sh --login-copilot
```

Flow:
1. Script starts GitHub device authorization flow.
2. User opens verification URL and enters user code.
3. Script polls until authorized.
4. Script exchanges for Copilot token and writes credentials.
5. Script prints success + auth file location.

### Run with Copilot profile

```bash
./run.sh --profile copilot
```

`run.sh` loads/refreshes Copilot credentials from `~/.agents/flatmachines/auth.json` and injects the active token for execution.

---

## Profile shape (reference-aligned)

Following the same OAuth block shape used by the codex example (`provider`, `oauth.auth_file`):

```yaml
spec: flatprofiles
spec_version: "2.5.0"

data:
  model_profiles:
    copilot:
      provider: github-copilot
      name: gpt-4o
      backend: litellm
      base_url: https://api.individual.githubcopilot.com
      oauth:
        provider: github-copilot
        auth_file: ~/.agents/flatmachines/auth.json

  default: copilot
```

Notes:
- `oauth` block is included for consistency and explicitness.
- Runtime token acquisition/refresh remains plugin-managed in `run.sh`.

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

This follows the same shape used in `pi-mono` (`refresh`, `access`, `expires`, optional enterprise metadata).

---

## Technical approach

Reuse the proven `pi-mono` Copilot device-code sequence:

1. `POST https://<domain>/login/device/code`
2. Poll `POST https://<domain>/login/oauth/access_token` with
   `grant_type=urn:ietf:params:oauth:grant-type:device_code`
3. Exchange GitHub token for Copilot token via
   `GET https://api.<domain>/copilot_internal/v2/token`
4. Save credentials to `~/.agents/flatmachines/auth.json`
5. On each run, refresh if near expiry before invoking model calls

Implementation boundary:
- **Plugin** (`run.sh` + helper script/module): owns login + refresh + file write.
- **FlatAgents config** (`profiles.yml`): declares provider/auth file location and profile intent.

---

## Security & reliability

- Create parent directories as needed.
- Write auth file atomically and preserve unrelated providers.
- File mode `0600` for secrets.
- Never print raw tokens to stdout/stderr.
- Clear error messages for pending/expired/denied device flow states.

---

## Acceptance criteria

1. `./run.sh --login-copilot` completes device-code login and stores credentials in `~/.agents/flatmachines/auth.json`.
2. Auth file contains valid `github-copilot` OAuth entry (`type`, `refresh`, `access`, `expires`).
3. Copilot profile in `profiles.yml` resolves and can be selected for runs.
4. Expired token is refreshed automatically by plugin on next run.
5. No non-device-code sign-in path is exposed.

---

## Open questions

1. Do we want optional enterprise domain prompt now, or github.com-only in v1?
2. Should we add a `--auth-file` override flag to `run.sh` for CI/dev flexibility?
3. Should we add a tiny diagnostics command (`--check-copilot-auth`) similar to the codex oauth example?

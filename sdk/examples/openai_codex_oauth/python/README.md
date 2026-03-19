# OpenAI Codex OAuth (Standalone FlatAgents Vertical Slice)

This example demonstrates an **example-only** `FlatAgent` subclass (`CodexFlatAgent`) that uses ChatGPT Plus/Pro Codex OAuth credentials from:

- `./config/auth.json` (default for this example)
- or `--auth-file` / `FLATAGENTS_CODEX_AUTH_FILE`

No FlatAgents core code is modified.

## What it includes

- `backend: codex` hijack flatagents via subclass override (`_init_backend`, `_call_llm`)
- OAuth credential loading from pi auth.json (`openai-codex` provider)
- Required Codex headers (`Authorization`, `chatgpt-account-id`, `OpenAI-Beta`, `originator`)
- SSE transport only (no websocket in this slice)
- Retry/backoff on `429/5xx`
- Refresh behavior (pi parity): refresh before request when token is expired; still refresh-and-retry on `401/403` fallback
- Response adaptation to a LiteLLM-like shape consumed by FlatAgent

## Config

`config/profiles.yml` uses schema-extension fields for this standalone client:

- `api: openai-codex-responses`
- `auth.type: oauth`
- `auth.provider: openai-codex`
- `backend: codex`
- `codex_*` runtime options

## Login (new in this slice)

You can log in directly from this example now:

```bash
cd sdk/examples/openai_codex_oauth/python
./run.sh -- --login
```

This opens the OpenAI OAuth flow in your browser (or you can paste the redirect URL/code manually).
No email is requested by this CLI; authentication is handled by the OpenAI web flow.

Credentials are saved to `./config/auth.json` by default (or `--auth-file` / `FLATAGENTS_CODEX_AUTH_FILE`).

To bootstrap from your existing pi credentials:

```bash
cp ~/.pi/agent/auth.json ./config/auth.json
chmod 600 ./config/auth.json
```

## Run

```bash
cd sdk/examples/openai_codex_oauth/python
./run.sh --local -- --prompt "Explain FlatAgents in one sentence"
```

> `--local` installs local `sdk/python/flatagents` editable for development parity.

## Tests

```bash
cd sdk/examples/openai_codex_oauth/python
uv pip install --python .venv/bin/python -e ".[test]"

# all tests
.venv/bin/python -m pytest -q

# unit only
.venv/bin/python -m pytest -q tests/unit

# integration only
.venv/bin/python -m pytest -q tests/integration
```

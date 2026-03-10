# OpenAI Codex OAuth (Standalone FlatAgents Vertical Slice)

This example demonstrates an **example-only** `FlatAgent` subclass (`CodexFlatAgent`) that uses ChatGPT Plus/Pro Codex OAuth credentials from:

- `~/.pi/agent/auth.json` (default)
- or `FLATAGENTS_CODEX_AUTH_FILE`

No FlatAgents core code is modified.

## What it includes

- `backend: codex` hijack flatagents via subclass override (`_init_backend`, `_call_llm`)
- OAuth credential loading from pi auth.json (`openai-codex` provider)
- Required Codex headers (`Authorization`, `chatgpt-account-id`, `OpenAI-Beta`, `originator`)
- SSE transport only (no websocket in this slice)
- Retry/backoff on `429/5xx`
- Stale-token behavior: request once with current token, then refresh-and-retry on `401/403`
- Response adaptation to a LiteLLM-like shape consumed by FlatAgent

## Config

`config/profiles.yml` uses schema-extension fields for this standalone client:

- `api: openai-codex-responses`
- `auth.type: oauth`
- `auth.provider: openai-codex`
- `backend: codex`
- `codex_*` runtime options

## Prerequisite

Authenticate in pi first:

```bash
pi
# then run /login and choose openai-codex
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

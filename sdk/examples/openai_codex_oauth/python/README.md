# OpenAI Codex OAuth Example (Python)

This example demonstrates:

1. Browser/callback login (`--login-codex`)
2. Credential diagnostics (`--check-codex-auth`)
3. A real FlatAgent call using `backend: codex` (`--run`)

## Run

```bash
cd sdk/examples/openai_codex_oauth/python
./run.sh --local -- --check-codex-auth
./run.sh --local -- --login-codex
./run.sh --local -- --run --prompt "Reply with CODEX_OK"
```

## Remote-machine login (manual callback paste)

```bash
# prompts immediately for pasted callback URL/code
./run.sh --local -- --login-codex --paste-callback-url --no-browser

# or pass callback URL/code directly (non-interactive)
./run.sh --local -- --login-codex --callback-url "http://localhost:1455/auth/callback?..." --no-browser

# if state mismatch keeps happening, pass only the code value
./run.sh --local -- --login-codex --callback-url "ac_xxx..." --no-browser
```

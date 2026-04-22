# Codex CLI Adapter — Cache Demo

Demonstrates Responses API prefix caching with the `codex-cli` runtime via
native `prompt` + `flatprofile` + `flatagent` configs.

The Python runner uses `config/v4/`, where each machine embeds FlatAgent
bundles, and each bundle references a prompt file plus a shared Codex profile.
A two-state machine seeds a thread (`seed`), then resumes the same thread
(`verify`). The second call should show significantly higher cached token
counts, proving the prefix cache hit.

## Run

```bash
# Requires: codex CLI on $PATH, authenticated
./run.sh --local
```

## Expected output

```
seed:   tokens: ~11000→~26 (cached: ~3400)
verify: tokens: ~9500→~19  (cached: ~6500)   ← cache hit doubled
```

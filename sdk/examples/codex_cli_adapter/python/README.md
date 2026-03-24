# Codex CLI Adapter — Cache Demo

Demonstrates Responses API prefix caching with the `codex-cli` adapter.

A two-state machine sends ~10k tokens of context (`seed`), then resumes
the same thread with "Reply YES" (`verify`). The monitor log shows
`(cached: N)` on each call — the second call should show significantly
higher cached token counts, proving the prefix cache hit.

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

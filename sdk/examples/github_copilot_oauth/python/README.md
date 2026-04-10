# GitHub Copilot OAuth Example (Python)

This example demonstrates:

1. Device-code login (`--login-copilot`)
2. Credential diagnostics (`--check-copilot-auth`)
3. A real FlatAgent call using `backend: copilot` (`--run`)

## Run

```bash
cd sdk/examples/github_copilot_oauth/python
./run.sh --local -- --check-copilot-auth
./run.sh --local -- --login-copilot
./run.sh --local -- --run --prompt "Reply with COPILOT_OK"
```

# Tool Loop Example (JavaScript)

Standalone `ToolLoopAgent` demo using shared config in `../config/agent.yml`.

## Run

```bash
cd sdk/examples/tool_loop/js
./run.sh --local --mock
./run.sh --local --mock "What time is it in Tokyo?"
```

Use `--mock` for deterministic local testing without API keys.
Without `--mock`, it uses the configured model profile from `../config/profiles.yml`.

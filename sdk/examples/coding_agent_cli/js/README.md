# Tool Use CLI Example (JavaScript)

JS parity implementation for `coding_agent_cli`.

Uses shared config from `../config/`:
- `machine.yml`
- `agent.yml`
- `profiles.yml`

## Run

```bash
cd sdk/examples/coding_agent_cli/js

# REPL (machine mode)
./run.sh --local

# Single-shot machine mode
./run.sh --local -p "list TypeScript files"

# Standalone tool loop with deterministic mock backend
./run.sh --local --standalone --mock "list files"
```

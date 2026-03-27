# Claude Code Adapter Example (JavaScript)

JS parity implementation for the Claude Code adapter example.

Uses shared config files from `../config/`:
- `machine.yml`
- `machine_multi_state.yml`
- `machine_with_refs.yml`
- `claude-planner.json`
- `claude-coder.json`

## Run

```bash
cd sdk/examples/claude_code_adapter/js

# help
./run.sh --local --help

# single-state task
./run.sh --local -p "add a /health endpoint"

# multi-state task
./run.sh --local --multi-state -p "add a /health endpoint"
```

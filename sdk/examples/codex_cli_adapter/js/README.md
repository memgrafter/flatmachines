# Codex CLI Adapter — Cache Demo (JavaScript)

JS parity implementation for the Codex CLI cache demos.

Uses shared config in `../config/`:
- `machine_cache_demo.yml`
- `machine_fanout_cache_demo.yml`
- `ask_q1.yml`
- `ask_q2.yml`
- `ask_q3.yml`
- `demo_context.md`

## Run

```bash
cd sdk/examples/codex_cli_adapter/js

# help
./run.sh --local --help

# sequential cache demo
./run.sh --local --test-cache

# fanout cache demo
./run.sh --local --test-fanout-cache
```

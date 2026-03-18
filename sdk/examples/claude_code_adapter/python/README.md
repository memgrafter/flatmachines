# Claude Code Adapter Example

Drives the [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code)
as a FlatMachine agent using the `claude-code` adapter.

## Prerequisites

- Claude Code CLI installed and authenticated (`claude` on `$PATH`)
- Python 3.10+
- `flatmachines` package installed

## Usage

### Single-shot task

```bash
python -m claude_code_example.main -p "add a /health endpoint to the Flask app"
```

### Multi-state (plan → implement → test)

```bash
python -m claude_code_example.main -p "add a /health endpoint" --multi-state
```

### Custom working directory

```bash
python -m claude_code_example.main -p "fix the failing tests" -w /path/to/project
```

## How It Works

The `claude-code` adapter:

1. Spawns `claude -p <task> --output-format stream-json --verbose`
2. Streams NDJSON events, collecting tool use and results
3. Maps the CLI result to `AgentResult` with full usage/cost metrics
4. Supports session resume via `--resume` for cache-warm multi-state flows
5. Auto-continues with `--resume` until `<<AGENT_EXIT>>` sentinel is found

### Session Resume (Cache Preservation)

In the multi-state machine (`machine_multi_state.yml`), the session ID
flows through context:

```
plan (new session) → implement (--resume) → test (--resume)
```

Each resumed state sees the full prior conversation. Anthropic's prompt
cache keeps `cache_read_input_tokens` high and costs low.

## Config Reference

See `config/machine.yml` for the single-shot config and
`config/machine_multi_state.yml` for the multi-state config.

Key adapter config fields:

| Field | Default | Description |
|-------|---------|-------------|
| `model` | `opus` | Model alias or full name |
| `effort` | `high` | Effort level |
| `permission_mode` | *(required)* | `bypassPermissions` for headless |
| `tools` | *(all)* | Exact tool whitelist (`--tools`) |
| `system_prompt` | *(CLI default)* | Replace system prompt |
| `append_system_prompt` | *(none)* | Append to system prompt |
| `max_budget_usd` | `0` (disabled) | Cost cap |
| `timeout` | `0` (disabled) | Subprocess timeout (seconds) |
| `max_continuations` | `100` | Auto-continue limit (-1=unlimited) |
| `exit_sentinel` | `<<AGENT_EXIT>>` | Completion sentinel |
| `claude_bin` | `claude` | Path to claude binary |

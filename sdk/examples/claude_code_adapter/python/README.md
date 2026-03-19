# Claude Code Adapter Example

Drives the [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code)
as a FlatMachine agent using the `claude-code` adapter.

## Prerequisites

- Claude Code CLI installed and authenticated (`claude` on `$PATH`)
- Python 3.10+

## Quick Start (with `run.sh`)

```bash
# Make executable
chmod +x run.sh

# Single-shot task (installs deps, runs demo)
./run.sh -p "add a /health endpoint to the Flask app"

# Use local SDK (for development)
./run.sh --local -p "add a /health endpoint"

# Multi-state: plan → implement → test
./run.sh --multi-state -p "add a /health endpoint"

# With file refs: planner + coder + reviewer, each with its own config
./run.sh --with-refs -p "add a /health endpoint"

# Custom working directory
./run.sh -p "fix the failing tests" -w /path/to/project
```

## Manual Setup

```bash
cd sdk/examples/claude_code_adapter/python
uv venv && uv pip install -e .
python -m claude_code_example.main -p "add a /health endpoint"
```

## Machine Configs

### `machine.yml` — Single-shot task

One `work` state, inline agent config. Simplest form.

### `machine_multi_state.yml` — Plan → implement → test

Three states sharing one session via `--resume`. Each state sees the full
prior conversation. Cache keeps costs flat.

### `machine_with_refs.yml` — Per-agent config files

Three agents (`planner`, `coder`, `reviewer`), each referencing a
separate JSON config file:

```yaml
agents:
  planner:
    type: claude-code
    ref: ./claude-planner.json       # read-only tools
  coder:
    type: claude-code
    ref: ./claude-coder.json         # full tool set
  reviewer:
    type: claude-code
    ref: ./claude-coder.json         # same base as coder
    config:
      max_budget_usd: 1.0            # inline overrides file
      effort: low
```

File refs are resolved at machine load time and embedded in the config.
Checkpoints are self-contained — no path resolution needed on resume.

## How It Works

The `claude-code` adapter:

1. Spawns `claude -p <task> --output-format stream-json --verbose`
2. Streams NDJSON events, collecting tool use and results
3. Maps the CLI result to `AgentResult` with full usage/cost metrics
4. Supports session resume via `--resume` for cache-warm multi-state flows
5. Auto-continues with `--resume` until `<<AGENT_EXIT>>` sentinel is found

### Session Resume (Cache Preservation)

In multi-state machines, the session ID flows through context:

```
plan (new session) → implement (--resume) → test (--resume)
```

Each resumed state sees the full prior conversation. Anthropic's prompt
cache keeps `cache_read_input_tokens` high and costs low.

## Config Reference

Config keys map 1:1 to Claude Code CLI flags. Put them in a JSON file
and reference via `ref`, or inline in the machine YAML:

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
| `max_continuations` | `100` | Auto-continue limit |
| `exit_sentinel` | `<<AGENT_EXIT>>` | Completion sentinel |
| `claude_bin` | `claude` | Path to claude binary |

# Claude Code Adapter Example

Drives the [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code)
through native `prompt` + `flatprofile` + `flatagent` configs.

The Python runner uses `config/v4/`, where machines embed FlatAgent bundles,
and each bundle references a prompt file plus a Claude Code profile.

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

One `work` state using an inline FlatAgent bundle that references `./prompts/coder.prompt.yml`
and `./profiles/claude-coder.profile.yml`.

### `machine_multi_state.yml` — Plan → implement → test

Three states sharing one Claude session via `resume_session`. The runtime profile
stays fixed while the machine carries the live session ID in context.

### `machine_with_refs.yml` — Per-agent prompt/profile bundles

Three agents (`planner`, `coder`, `reviewer`), each defined as an inline
FlatAgent bundle with prompt/profile refs:

```yaml
agents:
  planner:
    spec: flatagent
    data:
      prompt: ./prompts/planner.prompt.yml
      profile: ./profiles/claude-planner.profile.yml
```

This keeps authored prompt text in prompt configs and runtime knobs in profiles.

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

Prompt text lives in `config/v4/prompts/*.prompt.yml`.
Runtime knobs live in `config/v4/profiles/*.profile.yml`.
FlatAgent bundles in `config/v4/agents/*.flatagent.yml` tie those together.

Representative Claude profile fields:

| Field | Default | Description |
|-------|---------|-------------|
| `model` | `opus` | Model alias or full name |
| `effort` | `high` | Effort level |
| `permission_mode` | *(required)* | `bypassPermissions` or `plan` |
| `tools` | *(all)* | Exact tool whitelist (`--tools`) |
| `working_dir` | config-dependent | Working directory, supports `{{ context.* }}` |
| `max_budget_usd` | `0` (disabled) | Cost cap |
| `timeout` | `0` (disabled) | Subprocess timeout (seconds) |
| `max_continuations` | `100` | Auto-continue limit |
| `exit_sentinel` | `<<AGENT_EXIT>>` | Completion sentinel |
| `claude_bin` | `claude` | Path to claude binary |

# Tool Use CLI Example

A coding agent with 4 tools — **read**, **write**, **bash**, **edit** — the same defaults as pi-mono. Demonstrates both FlatMachine (orchestrated) and standalone ToolLoopAgent modes.

## Tools

| Tool | Description |
|------|-------------|
| `read` | Read file contents with offset/limit, truncation at 2000 lines / 50KB |
| `bash` | Execute shell commands with timeout, tail-truncated output |
| `write` | Write/create files with automatic parent directory creation |
| `edit` | Surgical find-and-replace (exact match, single occurrence) |

## Usage

```bash
cd sdk/examples/tool-use-cli/python

# Via run.sh (sets up venv, installs deps)
./run.sh --local "list all Python files in this repo"

# Or directly (if deps are installed)
python -m tool_use_cli.main "read README.md and summarize it"

# Standalone mode (ToolLoopAgent, no machine)
python -m tool_use_cli.main --standalone "what files are in the current directory?"

# Custom working directory
python -m tool_use_cli.main --working-dir /tmp/project "create a hello world Python script"
```

## Modes

### Machine Mode (default)

Uses `FlatMachine` with a `tool_loop` state. Gets you:
- Per-tool-call hooks (`on_tool_calls`, `on_tool_result`)
- Checkpointing after every tool call
- Transition evaluation mid-loop
- File modification tracking via hooks

### Standalone Mode (`--standalone`)

Uses `ToolLoopAgent` directly. Simpler, no machine overhead. Gets you:
- Guardrails (turns, cost, timeout)
- Same tool implementations
- No hooks or checkpointing

## Architecture

```
config/
  agent.yml       — Agent config with tool definitions in YAML
  machine.yml     — Machine config with tool_loop state
  profiles.yml    — Model profiles

python/src/tool_use_cli/
  tools.py        — Tool implementations (CLIToolProvider)
  hooks.py        — CLIToolHooks (provides tool provider, tracks file modifications)
  main.py         — Entry point (machine or standalone mode)
```

## How It Works

1. Tool **definitions** live in `agent.yml` (`data.tools`) — the LLM sees these
2. Tool **execution** lives in `CLIToolProvider` — bound to a working directory
3. The machine's `tool_loop` state calls the agent, gets tool requests, executes them one-by-one with hooks and checkpoints between each call
4. The `on_tool_result` hook tracks which files were modified by write/edit operations

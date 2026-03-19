# Coding Machine CLI Example

A CLI coding agent with 4 tools — **read**, **write**, **bash**, **edit** — implemented with a **FlatMachine machine-driven tool loop** plus optional human review.

## Tools

| Tool | Description |
|------|-------------|
| `read` | Read file contents with offset/limit, truncation at 2000 lines / 50KB |
| `bash` | Execute shell commands with timeout, tail-truncated output |
| `write` | Write/create files with automatic parent directory creation |
| `edit` | Surgical find-and-replace (exact match, single occurrence) |

## Quick Start

```bash
cd sdk/examples/coding_machine_cli/python
./run.sh --local
```

Then enter a task, for example:

```text
> list all Python files in this repo
```

## Usage Modes

```bash
cd sdk/examples/coding_machine_cli/python

# Interactive REPL (default): machine tool-loop + human review
./run.sh --local

# Single-shot: one task, includes human review prompt
./run.sh --local -p "list all Python files in this repo"

# Standalone: machine tool-loop, auto-approve (no interactive review)
./run.sh --local --standalone "what files are in the current directory?"

# Custom working directory
./run.sh --local -w /tmp/project -p "create a hello world Python script"
```

## Flow

```
┌─────────────────┐
│      start      │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│      work       │◄──────────┐
│  (tool loop)    │           │
└────────┬────────┘           │
         │                    │ feedback
         ▼                    │
┌─────────────────┐           │
│  human_review   │───────────┘
└────────┬────────┘
         │ approved
         ▼
┌─────────────────┐
│      done       │
└─────────────────┘
```

## Architecture

```
config/
  agent.yml       — Agent config with tool definitions
  machine.yml     — Machine with tool_loop + human_review loop
  profiles.yml    — Model profiles

python/src/tool_use_cli/
  tools.py        — Tool implementations (CLIToolProvider)
  hooks.py        — Hooks (tool provider, tool visibility, human review)
  main.py         — Entry point (REPL, single-shot, standalone auto-approve)
```

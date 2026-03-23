# Coding Machine CLI (JavaScript)

A CLI coding agent with 4 tools — **read**, **write**, **bash**, **edit** — implemented with a **FlatMachine machine-driven tool loop** plus optional human review.

This JS implementation uses `js/profiles.yml`, configured to read Codex OAuth credentials from `~/.pi/agent/auth.json`.

## Tools

| Tool | Description |
|------|-------------|
| `read` | Read file contents with offset/limit, truncation at 2000 lines / 50KB |
| `bash` | Execute shell commands with timeout, tail-truncated output |
| `write` | Write/create files with automatic parent directory creation |
| `edit` | Surgical find-and-replace (exact match, single occurrence) |

## Quick Start

```bash
cd sdk/examples/coding_machine_cli/js
./run.sh --local
```

Then enter a task, for example:

```text
> list all TypeScript files in this repo
```

## Usage Modes

```bash
cd sdk/examples/coding_machine_cli/js

# Interactive REPL (default): machine tool-loop + human review
./run.sh --local

# Single-shot: one task, includes human review prompt
./run.sh --local -p "list all Python files in this repo"

# Standalone: machine tool-loop, auto-approve (no interactive review)
./run.sh --local --standalone "what files are in the current directory?"

# Custom working directory
./run.sh --local -w /tmp/project -p "create a hello world Python script"
```

## CLI Options

- `-p, --print <TASK>`: run one task and exit
- `-w, --working-dir <PATH>`: working directory for tools (default: current directory)
- `-s, --standalone [TASK]`: run without interactive human review; can take task inline or reuse `-p`

## File Structure

```
coding_machine_cli/
├── config/
│   ├── machine.yml
│   ├── agent.yml
│   └── profiles.yml
├── js/
│   ├── src/
│   │   └── tool_use_cli/
│   │       ├── tools.ts
│   │       ├── hooks.ts
│   │       └── main.ts
│   ├── package.json
│   ├── tsconfig.json
│   ├── run.sh
│   └── README.md
└── python/
```

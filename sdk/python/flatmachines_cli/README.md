# flatmachines-cli

Branded CLI for flatmachines — async backend with pluggable frontends.

## Quick Start

```bash
# Interactive REPL (explore, inspect, run machines)
flatmachines

# Or via run.sh from source
bash run.sh --local
```

## REPL Commands

```
list                       Show discovered machines
inspect <name|path>        Show machine structure (states, transitions, agents)
validate <name|path>       Run schema validation
context <name|path>        Show context template and required inputs
run <name|path> [json]     Execute a machine (prompts for input if needed)
history                    Show recent executions
bus                        Dump last DataBus snapshot
help                       Show commands
quit                       Exit
```

## Direct Execution

```bash
# Single-shot with human review
flatmachines run machine.yml -p "task description"

# Interactive agent REPL on a specific config
flatmachines run machine.yml

# Standalone (no human review)
flatmachines run machine.yml --standalone "task description"
```

## Architecture

- **DataBus**: UDP-like latest-value slots (writers overwrite, readers get latest)
- **Processors**: independent async tasks with Hz-capped output
- **CLIHooks**: thin bridge from flatmachines MachineHooks to event pipeline
- **CLIBackend**: orchestrates processors, bus, and frontend lifecycle
- **Frontend protocol**: abstract interface (the Rust replacement boundary)
- **TerminalFrontend**: simple line-based output (temporary, replaceable)

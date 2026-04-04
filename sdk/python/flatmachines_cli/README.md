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
stats                      Show processor/hook performance stats
save [path]                Save bus snapshot to JSON file
help                       Show commands
quit                       Exit
```

Tab-completion is available for commands and machine names.

## CLI Commands

```bash
# List discovered machines
flatmachines list

# Inspect a machine config (states, transitions, agents)
flatmachines inspect machine.yml

# Validate against schema
flatmachines validate machine.yml

# Single-shot with human review
flatmachines run machine.yml -p "task description"

# Interactive agent REPL on a specific config
flatmachines run machine.yml

# Standalone (no human review)
flatmachines run machine.yml --standalone "task description"

# Show version
flatmachines --version
```

## Architecture

- **DataBus**: UDP-like latest-value slots (writers overwrite, readers get latest)
- **Processors**: independent async tasks with Hz-capped output
- **CLIHooks**: thin bridge from flatmachines MachineHooks to event pipeline
- **CLIBackend**: orchestrates processors, bus, and frontend lifecycle
- **Frontend protocol**: abstract interface (the Rust replacement boundary)
- **TerminalFrontend**: simple line-based output (temporary, replaceable)

## Development

```bash
# Install dev dependencies
uv pip install --python .venv/bin/python -e ".[dev]"

# Run tests
.venv/bin/python -m pytest tests/ -v

# Run specific test file
.venv/bin/python -m pytest tests/test_bus.py -v

# Run with coverage
.venv/bin/python -m pytest tests/ --tb=short -q
```

### Test Structure

- `test_bus.py` — DataBus and Slot unit tests
- `test_events.py` — Event constructors and type constants
- `test_processors.py` — Processor pipeline behavior
- `test_processor_advanced.py` — Custom processors, timing, edge cases
- `test_backend.py` — CLIBackend lifecycle and dispatch
- `test_hooks.py` — CLIHooks bridge tests
- `test_frontend.py` — TerminalFrontend rendering
- `test_rendering.py` — Frontend change detection and output
- `test_protocol.py` — Frontend ABC and ActionHandler
- `test_discovery.py` — Machine config discovery
- `test_inspector.py` — Machine inspector formatting
- `test_inspector_advanced.py` — Complex config inspection
- `test_repl.py` — REPL command tests
- `test_main.py` — CLI entry point
- `test_integration.py` — Full pipeline integration tests
- `test_concurrency.py` — Concurrent access patterns
- `test_serialization.py` — JSON serialization boundary
- `test_validation.py` — Input validation and error handling
- `test_error_paths.py` — Error recovery tests
- `test_edge_cases.py` — Boundary conditions
- `test_quality.py` — Docstrings and API consistency
- `test_repr.py` — Debug repr completeness
- `test_init.py` — Public API surface
- `test_api_contract.py` — API contract stability
- `test_cli_subcommands.py` — CLI subcommand tests (list/inspect/validate/context)
- `test_json_logging.py` — Structured JSON logging
- `test_bus_persistence.py` — DataBus save/load/serialization
- `test_bus_diff.py` — Snapshot comparison
- `test_health_check.py` — Backend monitoring
- `test_hooks_timing.py` — Hook timing instrumentation
- `test_human_review.py` — Human review input handling
- `test_processor_stats.py` — Backpressure metrics
- `test_processor_reset.py` — Reset between runs
- `test_integration_lifecycle.py` — Full lifecycle integration
- `test_repl_stats.py` — REPL stats command
- `test_repl_save.py` — REPL save command
- `test_repl_completion.py` — Tab-completion

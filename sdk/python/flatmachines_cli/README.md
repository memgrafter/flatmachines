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

# Show context template and required inputs
flatmachines context machine.yml

# Dry run — validate + inspect without executing
flatmachines run machine.yml --dry-run

# Single-shot with human review
flatmachines run machine.yml -p "task description"

# Interactive agent REPL on a specific config
flatmachines run machine.yml

# Standalone (no human review)
flatmachines run machine.yml --standalone "task description"

# Show version
flatmachines --version

# Set log level for debugging
flatmachines --log-level DEBUG run machine.yml -p "task"

# Structured JSON logging for log aggregation
flatmachines --log-format json run machine.yml -p "task"
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

### Test Structure (70 test files, 959 tests)

**Core modules:**
- `test_bus.py`, `test_bus_advanced.py` — DataBus and Slot unit tests
- `test_bus_persistence.py` — DataBus save/load/to_json/from_json
- `test_bus_diff.py` — Snapshot comparison
- `test_bus_subscribe.py` — Push notification subscribe/unsubscribe
- `test_bus_slot_names.py` — Slot management and properties
- `test_slot_async.py` — Async Slot.wait() behavior
- `test_events.py`, `test_events_advanced.py` — Event constructors and type constants
- `test_event_field_naming.py` — Event-processor field name contract
- `test_processors.py`, `test_processor_advanced.py` — Processor pipeline
- `test_processor_event_types.py` — Event type filtering per processor
- `test_processor_stats.py` — Backpressure metrics (events processed/dropped/HWM)
- `test_processor_reset.py` — State reset between runs

**Backend & hooks:**
- `test_backend.py` — CLIBackend lifecycle and dispatch
- `test_backend_dispatch.py` — Event routing to processors
- `test_backend_shutdown.py` — Graceful shutdown with timeout
- `test_hooks.py`, `test_hooks_advanced.py` — CLIHooks bridge
- `test_hooks_timing.py` — Hook timing instrumentation

**Frontend:**
- `test_frontend.py`, `test_frontend_advanced.py` — TerminalFrontend
- `test_frontend_rendering.py` — Render logic (content/errors/status/tokens)
- `test_frontend_tools_render.py` — Tool display rendering
- `test_human_review.py` — Human review input handling (run_in_executor)
- `test_rendering.py` — Change detection and output

**Protocol:**
- `test_protocol.py` — Frontend ABC and ActionHandler
- `test_action_handler.py`, `test_action_handler_advanced.py` — Action routing

**CLI & REPL:**
- `test_main.py` — CLI entry point
- `test_cli_subcommands.py` — CLI subcommands (list/inspect/validate/context/--dry-run)
- `test_repl.py` — REPL command tests
- `test_repl_completion.py` — Tab-completion
- `test_repl_input.py` — Input parsing and resolution
- `test_repl_prefix_match.py` — Command prefix matching
- `test_repl_save.py` — Save command
- `test_repl_stats.py` — Stats command
- `test_json_logging.py` — Structured JSON logging (--log-format json)

**Discovery & inspection:**
- `test_discovery.py`, `test_discovery_advanced.py`, `test_discovery_comprehensive.py` — Machine scanning
- `test_inspector.py`, `test_inspector_advanced.py`, `test_inspector_robustness.py` — Config inspection

**Integration & stress:**
- `test_integration.py` — Full pipeline integration
- `test_integration_lifecycle.py` — Multi-run lifecycle
- `test_end_to_end.py` — Complete data flow verification
- `test_pipeline_stress.py` — High throughput stress tests
- `test_concurrency.py` — Concurrent access patterns

**Quality & contracts:**
- `test_api_contract.py` — API stability (method signatures, slot names)
- `test_quality.py` — Docstrings and API consistency
- `test_validation.py` — Input validation and error handling
- `test_init.py` — Public API surface (__all__)
- `test_packaging.py` — Package structure and metadata
- `test_version_check.py` — Version consistency (pyproject.toml vs __init__)
- `test_repr.py` — Debug repr completeness

**Edge cases & robustness:**
- `test_edge_cases.py` — Boundary conditions
- `test_error_paths.py` — Error recovery
- `test_defensive_access.py` — Pathological inputs to all processors
- `test_production_fixes.py` — Regression tests for specific bugs
- `test_tool_history_desync.py` — Frontend tool history rendering fix
- `test_tool_parallel.py` — Parallel tool tracking
- `test_tool_summarize.py` — Tool name summarization
- `test_serialization.py` — JSON serialization boundary
- `test_complete_coverage.py`, `test_final_coverage.py` — Remaining code paths
- `test_health_check.py` — Backend health monitoring
- `test_summary.py`, `test_run.py` — Misc coverage

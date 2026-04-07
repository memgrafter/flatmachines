# flatmachines-cli

Branded CLI for flatmachines — async backend with pluggable frontends and self-improvement capabilities.

## Quick Start

```bash
# Interactive REPL (explore, inspect, run machines)
flatmachines

# Run a machine config
flatmachines run machine.yml -p "task description"

# Self-improvement: benchmark and improve a codebase
flatmachines improve ./my-project --benchmark "bash benchmark.sh" --run

# Validate self-improvement config
flatmachines validate --self-improve
```

## Self-Improvement

flatmachines-cli can act as a **self-improving coding machine**. It uses the coding machine pattern: a FlatMachine config orchestrates a coding agent (with bash/read/write/edit tools) through an evaluate→archive loop.

### How It Works

```
┌─────────────────────────────────────────────────┐
│                  FlatMachine                     │
│                                                  │
│  start → improve → evaluate → archive → budget  │
│             │                    │        │      │
│          agent gets           machine   loop or  │
│          40 tool turns        checks    done     │
│          (bash/read/          metric             │
│           write/edit)                            │
└─────────────────────────────────────────────────┘
```

- **improve**: The coding agent gets the full task (target dir, benchmark) and 40 tool turns to analyze, implement, and verify changes. At the start of each iteration, it reads the full `experiments.jsonl` and `git log` — these are the only artifacts between sessions, never truncated.
- **evaluate**: The machine runs the benchmark and compares to the best score
- **archive**: Keep (git commit) or discard (git revert) based on the result
- **budget**: Check iteration limit and consecutive failures, then loop back

### Adapter Flexibility

The agent is configured via `profiles.yml`. Swap providers without changing the machine config:

```yaml
# config/profiles.yml — currently configured for Codex OAuth
data:
  model_profiles:
    default:
      provider: openai-codex
      name: gpt-5.3-codex
      backend: codex
      base_url: https://chatgpt.com/backend-api
      oauth:
        provider: openai-codex
        auth_file: ~/.pi/agent/auth.json
```

The coding machine pattern (flatagent with tool_loop) enables the meta agent to also modify the machine config, agent prompts, and tool definitions — enabling self-referential self-improvement.

### Config Files

| File | Purpose |
|------|---------|
| `config/self_improve.yml` | FlatMachine config — the improvement loop |
| `config/agents/coder.yml` | Unified coding agent (bash/read/write/edit) |
| `config/profiles.yml` | Model provider config (Codex OAuth) |

### Experiment Tracking

```python
from flatmachines_cli.experiment import ExperimentTracker

tracker = ExperimentTracker(
    name="optimize-perf",
    metric_name="speed_ms",
    direction="lower",
    log_path="experiments.jsonl",
    git_enabled=True,  # auto-commit on keep, auto-revert on discard
)
tracker.init()

result = tracker.run("bash benchmark.sh")
tracker.log(result=result, status="keep", description="Replaced loop with multiply")

# Query
print(tracker.best())
print(tracker.confidence_score())
tracker.export_csv("results.csv")
tracker.export_markdown("report.md")
```

### CLI Commands

```bash
# Run improvement loop (benchmark-only evaluation, no LLM)
flatmachines improve ./project -b "bash bench.sh" -m speed_ms -d lower --run

# Initialize config scaffolding
flatmachines improve ./project --init

# Validate self-improvement config
flatmachines validate --self-improve
flatmachines validate config/self_improve.yml --self-improve
```

### REPL Commands

```
improve status              Validate self-improve config
improve history <path>      Show experiment history table
improve validate [path]     Validate a machine config
experiment load <path>      Load experiment log
experiment summary <path>   Show experiment summary
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
improve [subcommand]       Self-improvement commands
experiment [subcommand]    Experiment tracking commands
help                       Show commands
quit                       Exit
```

## CLI Commands

```bash
# List discovered machines
flatmachines list

# Inspect a machine config
flatmachines inspect machine.yml

# Validate against schema
flatmachines validate machine.yml

# Validate self-improvement config
flatmachines validate --self-improve

# Show context template
flatmachines context machine.yml

# Dry run
flatmachines run machine.yml --dry-run

# Single-shot with human review
flatmachines run machine.yml -p "task description"

# Standalone (no human review)
flatmachines run machine.yml --standalone "task description"

# Self-improvement
flatmachines improve ./project -b "bash benchmark.sh" --run
flatmachines improve ./project --init

# Logging
flatmachines --log-level DEBUG run machine.yml -p "task"
flatmachines --log-format json run machine.yml -p "task"
```

## Architecture

- **DataBus**: UDP-like latest-value slots (writers overwrite, readers get latest)
- **Processors**: independent async tasks with Hz-capped output
- **CLIHooks**: thin bridge from flatmachines MachineHooks to event pipeline
- **CLIBackend**: orchestrates processors, bus, and frontend lifecycle
- **Frontend protocol**: abstract interface (the Rust replacement boundary)
- **TerminalFrontend**: simple line-based output (temporary, replaceable)
- **ExperimentTracker**: run/log/metrics/git/confidence/persist for experiment loops
- **SelfImprover**: wraps tracker for self-improvement workflows
- **ImprovementRunner**: programmatic evaluate→archive loop

## Development

```bash
# Install dev dependencies
uv pip install --python .venv/bin/python -e ".[dev]"

# Run tests
.venv/bin/python -m pytest tests/ -v

# Run specific test file
.venv/bin/python -m pytest tests/test_experiment.py -v

# Run with coverage
.venv/bin/python -m pytest tests/ --tb=short -q
```

### Test Structure (1147 tests)

**Self-improvement:**
- `test_experiment.py` — ExperimentTracker unit tests
- `test_experiment_git.py` — Git integration (commit/revert)
- `test_experiment_confidence.py` — Confidence scoring
- `test_improve.py` — SelfImprover + SelfImproveHooks
- `test_improvement_runner.py` — ImprovementRunner loop tests
- `test_self_improve_integration.py` — Full loop, config validation, adapter compat
- `test_validate_config.py` — validate_self_improve_config() tests
- `test_tracker_enhancements.py` — best/worst/diff/export_csv/get_entry
- `test_resilience.py` — Corrupted JSONL recovery, scaffold, callbacks

**Core modules:**
- `test_bus.py`, `test_bus_advanced.py` — DataBus and Slot unit tests
- `test_processors.py`, `test_processor_advanced.py` — Processor pipeline
- `test_events.py`, `test_events_advanced.py` — Event constructors

**Backend & hooks:**
- `test_backend.py`, `test_backend_dispatch.py` — CLIBackend lifecycle
- `test_hooks.py`, `test_hooks_advanced.py` — CLIHooks bridge

**Frontend:**
- `test_frontend.py`, `test_frontend_rendering.py` — TerminalFrontend
- `test_rendering.py` — Change detection and output

**CLI & REPL:**
- `test_main.py`, `test_cli_subcommands.py` — CLI entry point
- `test_repl.py`, `test_repl_completion.py` — REPL commands

**Discovery & inspection:**
- `test_discovery.py`, `test_inspector.py` — Machine scanning and inspection

**Integration & quality:**
- `test_integration.py`, `test_end_to_end.py` — Full pipeline
- `test_concurrency.py`, `test_error_paths.py` — Robustness
- `test_api_contract.py`, `test_version_check.py` — API stability

# Autoresearch Context — Self-Improving flatmachines_cli

> **Purpose**: Static reference for resuming after compaction. Read this FIRST, then autoresearch.md.
> **Last updated**: Run #4, score 400/400, 1062 tests passing.

## Goal

Convert `sdk/python/flatmachines_cli/` into a **coding machine with self-improvement mode**.
- Must work with any coding agent adapter (claude_code, codex_cli, coding_machine_cli, coding_agent_cli)
- Must be able to self-improve without external references (HyperAgents, pi-autoresearch)
- Benchmark: when flatmachines_cli can run an improvement loop on itself, we're done

## Current Status: 400/400 — All Phases Complete

| Phase | Score | What it measures |
|-------|-------|-----------------|
| 1. Presence | 100/100 | Modules exist, importable, correct API surface |
| 2. Quality | 100/100 | E2E experiment loop, persistence, error handling, hooks |
| 3. Readiness | 100/100 | Agent configs, integration tests, self-benchmark, docs |
| 4. Autonomous | 100/100 | Git commit/revert, confidence scoring, robustness |

## Architecture (current — 4687 LOC, 14 source files, 76 test files, 1062 passing)

```
flatmachines_cli/
├── __init__.py       (108L)  — public API exports, version="2.5.0"
├── main.py           (495L)  — CLI entry: list/inspect/validate/context/run/improve subcommands
├── backend.py        (269L)  — CLIBackend: orchestrates processors, DataBus, events
├── hooks.py          (172L)  — CLIHooks(MachineHooks): bridges flatmachines → event pipeline
├── bus.py            (372L)  — DataBus: UDP-like latest-value slots, subscribe/diff/persist
├── processors.py     (608L)  — Status/Token/Tool/Content/Error processors, Hz-capped
├── events.py         (150L)  — Event types + constructor functions (plain dicts)
├── protocol.py       (122L)  — Frontend ABC + ActionHandler registry
├── frontend.py       (294L)  — TerminalFrontend: simple line-based output
├── inspector.py      (308L)  — Machine config pretty-printer (inspect/validate/context)
├── discovery.py      (202L)  — MachineIndex: finds machine.yml configs in project
├── repl.py           (606L)  — Interactive REPL + improve/experiment commands
├── experiment.py     (550L)  — NEW: ExperimentTracker with run/log/git/confidence/persist
└── improve.py        (245L)  — NEW: SelfImprover + SelfImproveHooks action handlers

config/
├── self_improve.yml           — 8-state FlatMachine improvement loop
└── agents/
    ├── analyzer.yml           — Analysis agent (read + bash tools, profile-based model)
    └── implementer.yml        — Implementation agent (all 4 coding tools)

tests/ (76 files, 1062 tests)
├── test_experiment.py         — 37 tests: tracker API, run, log, persist, metrics
├── test_experiment_git.py     — 15 tests: git commit/revert, auto on keep/discard
├── test_experiment_confidence.py — 9 tests: confidence scoring
├── test_improve.py            — 24 tests: SelfImprover, hooks, config
└── test_self_improve_integration.py — 24 tests: full loop, adapter compat, config structure
```

## Key New Modules

### experiment.py — ExperimentTracker
```python
tracker = ExperimentTracker(
    name="optimize-X", metric_name="score", direction="higher",
    log_path="experiments.jsonl", working_dir=".", git_enabled=True,
)
tracker.init()
result = tracker.run("bash benchmark.sh")           # Runs command, parses METRIC lines
entry = tracker.log(result, status="keep", ...)      # Persists to JSONL, auto-commits
tracker.best_metric()                                # Best kept metric value
tracker.confidence_score()                           # Improvement / noise floor ratio
tracker.git_commit("message")                        # Stage all + commit
tracker.git_revert()                                 # Reset + checkout + clean
ExperimentTracker.from_file("log.jsonl")             # Resume from persisted log
```

### improve.py — SelfImprover
```python
improver = SelfImprover(
    target_dir="./my_project", benchmark_command="bash bench.sh",
    metric_name="score", direction="higher", git_enabled=True,
)
result = improver.run_benchmark()                    # Run benchmark command
evaluation = improver.evaluate(result)               # Compare to best
improver.log_improvement(result, "keep", "description")

# SelfImproveHooks for FlatMachine integration:
hooks = SelfImproveHooks(improver)
ctx = hooks.on_action("evaluate_improvement", ctx)   # Run + evaluate
ctx = hooks.on_action("archive_result", ctx)         # Log as keep
ctx = hooks.on_action("revert_changes", ctx)         # Log as discard
```

### config/self_improve.yml — FlatMachine States
```
start → analyze (agent:analyzer, tool_loop) → check_budget → implement (agent:implementer, tool_loop)
  → evaluate (action:evaluate_improvement) → archive_keep/archive_discard → back to analyze
  → done (final, when max_iterations or consecutive_failures reached)
```

## Event Pipeline (unchanged from original)
```
flatmachines hooks → events (dicts) → processors (async, Hz-capped) → DataBus (slots) → frontend
```

## Agent Adapters (examples that must work)
All agent configs use `model: default` — profile-based, swappable via profiles.yml:
1. **coding_machine_cli** — FlatMachine with tool_loop, CLIToolProvider
2. **coding_agent_cli** — Same + standalone ToolLoopAgent mode  
3. **claude_code_adapter** — Claude Code specific hooks
4. **codex_cli_adapter** — OpenAI Codex specific hooks

## HyperAgents Self-Improvement Core (extracted patterns)

### Key Abstractions We Adopted
- **MetaAgent pattern** → Our analyze + implement states with coding tools
- **Archive pattern** → ExperimentTracker JSONL persistence with keep/discard
- **Staged evaluation** → check_budget state, consecutive_failures counter
- **Parent selection** → Not adopted (single-branch), noted for future

### Key Differences
- No Docker isolation (runs in same process)
- No multi-branch evolution (single improvement track)
- Git commit/revert instead of diff-based lineage
- Profile-based model selection instead of hardcoded

## pi-autoresearch Self-Improvement Core (extracted patterns)

### Key Abstractions We Adopted
- **METRIC line parsing** → `parse_metrics()` regex, same format
- **init/run/log lifecycle** → ExperimentTracker mirrors init_experiment/run_experiment/log_experiment
- **keep/discard/crash statuses** → Same semantics, auto-commit/revert
- **Confidence scoring** → `confidence_score()` = improvement / noise_floor
- **ASI pattern** → notes dict on ExperimentEntry (structured diagnostics)

### Key Differences
- No pi-specific tooling dependency
- JSONL format is simpler (no segment tracking)
- No dashboard/widget integration
- Git operations are optional (git_enabled flag)

## Constraints (from user)
- Production quality changes only in `sdk/python/flatmachines_cli/`
- Tiny QOL changes OK in flatmachines/flatagents if directly related
- Prefer shimming in flatmachines_cli, note TODOs in todos.txt
- Don't overfit to benchmarks, don't cheat
- Focus on high impact

## What to Work On Next (see autoresearch.ideas.md)

### Benchmark Ceiling Reached
The benchmark is at 400/400 across 4 phases. To continue improving:
1. **Add Phase 5** checks for deeper capability (e.g., profiles.yml for self-improvement, validate machine config loads with FlatMachine, stress-test persistence)
2. **Or** shift focus to code quality improvements that don't need new benchmark phases (refactoring, edge case handling, documentation)

### High-Value Remaining Ideas
- Profiles.yml for self-improvement (default config that works out of box)
- validate_self_improve_config() API function
- `improve run` REPL command that actually starts the loop
- Improve CLI subcommand with `--run` flag for full loop execution

## Test Infrastructure
```bash
# Run all tests (from repo root)
sdk/python/flatmachines_cli/.venv/bin/python -m pytest sdk/python/flatmachines_cli/tests/ -q --tb=line

# Run only new self-improvement tests
sdk/python/flatmachines_cli/.venv/bin/python -m pytest sdk/python/flatmachines_cli/tests/ -k "experiment or improve or self_improve or git or confidence" -q

# Checks script (run by autoresearch automatically)
bash autoresearch.checks.sh
```

## Files Off Limits
- sdk/python/flatmachines/ (core SDK — shim in CLI, note in todos.txt)
- sdk/python/flatagents/ (core SDK — shim in CLI, note in todos.txt)
- Existing test files (don't modify, only add new ones)

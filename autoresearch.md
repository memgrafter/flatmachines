# Autoresearch: Self-Improving flatmachines_cli

> **Context**: Read `autoresearch.context.md` first for full architecture, reference patterns, and static analysis.

## Objective

Add self-improvement capabilities to `sdk/python/flatmachines_cli/` so it can:
1. Run experiments on itself (analyze, hypothesize, implement, evaluate, archive)
2. Work with any coding agent adapter (claude_code, codex_cli, coding_machine_cli, coding_agent_cli)
3. Operate without external references (HyperAgents, pi-autoresearch)

The self-improvement loop is a FlatMachine config that the CLI can `run` on itself.

## Metrics

- **Primary**: `capability_score` (unitless, higher is better) — 4-phase weighted score
  - Phase 1 (100): Modules exist, importable, correct API
  - Phase 2 (100): E2E loop works, persistence, error handling
  - Phase 3 (100): Agent configs, integration tests, self-benchmark, docs
  - Phase 4 (100): Git commit/revert, confidence scoring, robustness
- **Secondary**: `test_count` — total passing tests, `source_loc` — lines of code

## How to Run

`./autoresearch.sh` — outputs `METRIC` lines. Score = sum of all phase checks.

## Files in Scope

| File | Purpose |
|------|---------|
| `flatmachines_cli/experiment.py` | Experiment tracking (run, log, metrics, git, confidence, persist) |
| `flatmachines_cli/improve.py` | Self-improvement orchestration (SelfImprover + SelfImproveHooks) |
| `flatmachines_cli/__init__.py` | Package exports |
| `flatmachines_cli/main.py` | CLI entry (includes improve subcommand) |
| `flatmachines_cli/repl.py` | REPL (includes improve/experiment commands) |
| `config/self_improve.yml` | FlatMachine config for improvement loop |
| `config/agents/analyzer.yml` | Analysis agent (read + bash) |
| `config/agents/implementer.yml` | Implementation agent (read + bash + write + edit) |
| `tests/test_experiment.py` | Tracker unit tests (37) |
| `tests/test_experiment_git.py` | Git integration tests (15) |
| `tests/test_experiment_confidence.py` | Confidence scoring tests (9) |
| `tests/test_improve.py` | SelfImprover + hooks tests (24) |
| `tests/test_self_improve_integration.py` | Full loop + config validation + adapter tests (24) |

## Off Limits

- sdk/python/flatmachines/ and sdk/python/flatagents/ (shim in CLI, note in todos.txt)
- Existing test files (don't modify, only add new)

## Constraints

- All existing tests must continue passing (currently 1062 total)
- No new external dependencies
- Production quality code
- No HyperAgents or pi-autoresearch runtime dependencies
- Self-improvement config must validate as real FlatMachine

## What's Been Tried

### Run 1 — Baseline (score: 10/100)
- Starting from 0: no experiment tracking, no self-improvement config
- Only self-contained checks passed (no external deps)

### Run 2 — Full infrastructure (score: 100/100 old → 200/200 new)
- Created experiment.py: ExperimentTracker with run/log/metrics/archive/noise_floor/persist
- Created improve.py: SelfImprover + SelfImproveHooks action handlers
- Created config/self_improve.yml: 8-state FlatMachine (analyze→implement→evaluate→archive loop)
- Added CLI improve subcommand and REPL improve/experiment commands
- 59 new tests (37 experiment, 22 improve)

### Run 3 — Real-world readiness (score: 300/300)
- Created config/agents/analyzer.yml and implementer.yml (profile-based, adapter-agnostic)
- Created test_self_improve_integration.py: 24 tests for full loop, config validation, adapter compat
- Updated todos.txt with upstream shim notes
- Expanded benchmark to Phase 3 (agent configs, integration tests, self-benchmark, docs)

### Run 4 — Autonomous loop features (score: 400/400)
- Added git_commit(), git_revert() to ExperimentTracker
- Added git_enabled flag: auto-commit on keep, auto-revert on discard/crash
- Added confidence_score(): improvement / noise_floor ratio
- Created test_experiment_git.py (15 tests) and test_experiment_confidence.py (9 tests)
- All 4 phases pass, 1062 tests passing, 0 failures

### What's Left (see autoresearch.ideas.md)
- Benchmark ceiling reached at 400/400
- Add Phase 5 for deeper capability or shift to code quality improvements
- High-value: profiles.yml for self-improvement, validate_self_improve_config(), improve --run

# Autoresearch: Self-Improving flatmachines_cli

> **Context**: Read `autoresearch.context.md` first for full architecture, reference patterns, and static analysis.

## Objective

Add self-improvement capabilities to `sdk/python/flatmachines_cli/` so it can:
1. Run experiments on itself (analyze, hypothesize, implement, evaluate, archive)
2. Work with any coding agent adapter (claude_code, codex_cli, coding_machine_cli, coding_agent_cli)
3. Operate without external references (HyperAgents, pi-autoresearch)

The self-improvement loop is a FlatMachine config that the CLI can `run` on itself.

## Metrics

- **Primary**: `capability_score` (unitless, higher is better) — weighted score of self-improvement features present and tested
- **Secondary**: `test_count` — total passing tests, `source_loc` — lines of code in scope

## How to Run

`./autoresearch.sh` — outputs `METRIC` lines. Checks for:
1. Experiment tracking module exists and is importable
2. Self-improvement machine config exists and validates
3. Experiment tracker has core features (run, log, archive, metrics)
4. Machine config has required states (analyze, implement, evaluate, archive)
5. Integration with existing CLI (subcommand or REPL command)
6. Tests exist and pass for new modules
7. No external tool dependencies (HyperAgents, pi-autoresearch)

## Files in Scope

| File | Purpose |
|------|---------|
| `flatmachines_cli/experiment.py` | NEW — experiment tracking (run, log, metrics, archive) |
| `flatmachines_cli/improve.py` | NEW — self-improvement orchestration helpers |
| `flatmachines_cli/__init__.py` | Update exports |
| `flatmachines_cli/main.py` | Add improve subcommand |
| `flatmachines_cli/repl.py` | Add improve REPL command |
| `tests/test_experiment.py` | NEW — experiment tracker tests |
| `tests/test_improve.py` | NEW — self-improvement tests |
| `tests/test_self_improve_integration.py` | NEW — integration tests |
| `config/self_improve.yml` | NEW — FlatMachine config for improvement loop |

## Off Limits

- sdk/python/flatmachines/ (core SDK — shim in CLI)
- sdk/python/flatagents/ (core SDK — shim in CLI)
- Existing test files (don't modify, only add new ones)
- autoresearch.sh benchmark internals

## Constraints

- All existing 952 tests must continue passing
- No new external dependencies
- Production quality code
- Must not require HyperAgents or pi-autoresearch at runtime
- Self-improvement config must validate as a real FlatMachine

## What's Been Tried

(Updated as experiments accumulate)

### Round 1 — Establishing baseline
- Starting from 0: no experiment tracking, no self-improvement config
- Baseline capability_score = 0

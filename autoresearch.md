# Autoresearch: Self-Improving flatmachines_cli

> **Context**: Read `autoresearch.context.md` for analysis of HyperAgents and pi-autoresearch patterns.

## Objective

Convert `sdk/python/flatmachines_cli/` into a coding machine that can self-improve, working with any coding agent adapter (claude_code, codex_cli, coding_machine_cli, coding_agent_cli).

**Success criterion**: flatmachines_cli can self-improve on all dimensions without pi-autoresearch and without HyperAgents as a reference repo.

## Key Insight (from source analysis)

Both HyperAgents and pi-autoresearch share the same architecture: **the LLM is the loop**. Neither has orchestration code for analyze→implement→evaluate. They give the LLM tools (bash, edit, experiment tracking) and context (eval results, code), and the LLM figures out what to improve.

## Metrics

- **Primary**: `capability_score` (unitless, higher is better) — multi-phase weighted score
- **Secondary**: `test_count` — total passing tests, `source_loc` — lines of code

## How to Run

`./autoresearch.sh` — outputs `METRIC` lines. Score = sum of all phase checks.

## Files in Scope

| File | Purpose |
|------|---------|
| `flatmachines_cli/experiment.py` | Experiment tracking (run, log, metrics, git, confidence, persist, export) |
| `flatmachines_cli/improve.py` | SelfImprover, SelfImproveHooks, ImprovementRunner, validate, scaffold |
| `flatmachines_cli/__init__.py` | Package exports |
| `flatmachines_cli/main.py` | CLI entry (improve, validate subcommands) |
| `flatmachines_cli/repl.py` | REPL (improve status/history/validate) |
| `config/self_improve.yml` | FlatMachine config for improvement loop |
| `config/agents/analyzer.yml` | Analysis agent (read + bash) |
| `config/agents/implementer.yml` | Implementation agent (read + bash + write + edit) |
| `config/profiles.yml` | Model profiles for adapter flexibility |

## Off Limits

- sdk/python/flatmachines/ and sdk/python/flatagents/ (shim in CLI, note in todos.txt)
- Existing test files (don't modify, only add new)

## Constraints

- All existing tests must continue passing
- No new external dependencies
- Production quality code
- No HyperAgents or pi-autoresearch runtime dependencies

## What's Been Tried

### Runs 1-4 — Core Infrastructure (score: 0→400)
- experiment.py: ExperimentTracker with run/log/metrics/archive/noise_floor/persist
- improve.py: SelfImprover + SelfImproveHooks action handlers
- config/self_improve.yml: 8-state FlatMachine
- Agent configs, git integration, confidence scoring
- 110 new tests

### Runs 5-6 — Production Polish (score: 400→600)
- profiles.yml with 3 profiles for adapter flexibility
- validate_self_improve_config() API
- Tracker enhancements: best/worst/diff/export_csv/get_entry
- CLI validate --self-improve
- Stress persistence tests

### Runs 7-8 — Evaluation Loop (score: 600→800)
- ImprovementRunner: programmatic evaluate→archive loop
- CLI improve --run/--git/--init flags
- REPL improve status/history/validate subcommands
- JSONL corruption recovery, export_markdown()
- scaffold_self_improve(), on_before_eval callback

### Run 9 — Honest Assessment
- Analyzed actual HyperAgents source (meta_agent.py, generate_loop.py, task_agent.py, tools/)
- Analyzed actual pi-autoresearch source (index.ts, SKILL.md)
- **Finding**: Both systems use "LLM is the loop" pattern — no orchestration code
- **Gap**: Our SelfImprover/ImprovementRunner/SelfImproveHooks are over-engineered orchestration
- **What's actually needed**: experiment.py exposed as agent-callable tools in a tool_loop
- Updated context doc with real analysis (previous version was fabricated)

### What's Left
- Expose experiment tracking as tools (like HyperAgents bash.py/edit.py)
- Update self_improve.yml to use tool_loop pattern
- Test with actual FlatMachine.execute()

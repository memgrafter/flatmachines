# Handoff: Model-Driven Parent Selection + Program.md Pattern + No Truncation

**Date:** 2026-04-07  
**Branch:** `flatmachines-cli-autoimproving`

## Summary

Self-improvement is now aligned with the intended architecture:

1. **Agent-owned lifecycle** (autoresearch-style):
   - Agent decides/creates benchmark
   - Agent runs benchmark, edits code, verifies, commit/revert
   - Agent writes `.self_improve/score.json`

2. **Model-driven parent selection** (HyperAgents-style outer loop):
   - Dedicated parent selector agent chooses parent from archive context
   - Plain-text contract (not JSON) between model stages
   - Deterministic parser + fallback to heuristic `best`

3. **No truncation in runtime/CLI logs and summaries**:
   - Full bash commands and content shown
   - Removed command/content/result truncation in major display/log paths

4. **REPL/CLI alignment + generation behavior**:
   - `improve` in REPL runs loop (not just status)
   - `--generations 0` means unlimited
   - `--generations N` respected by machine context (fixed)

---

## Key Changes

### A) Self-improve machine flow
**File:** `sdk/python/flatmachines_cli/config/self_improve.yml`

New outer-loop sequence:
- `select_parent` (prepare context action)
- `select_parent_model` (parent selector agent)
- `apply_parent_selection` (parser/action)
- `setup_worktree`
- `improve` (coder agent, full lifecycle)
- `archive_generation`
- `cleanup_worktree`
- `outer_budget_check`

Other updates:
- `max_generations` now comes from input template (`{{ input.max_generations | default(0) }}`)
- default `parent_selection` is `model`
- coder input includes `host_working_dir`

### B) New parent selector agent
**File:** `sdk/python/flatmachines_cli/config/agents/parent_selector.yml`

Plain text output contract:
- `PARENT_ID: <int|none>`
- `REASON: <text>`

No JSON schema in model-to-model handoff.

### C) Parent selection hooks
**File:** `sdk/python/flatmachines_cli/flatmachines_cli/improve.py`

Added:
- `prepare_parent_selection_context`
- `apply_parent_selection`
- parser for plain-text selector output
- fallback behavior on bad/unknown output

### D) Agent prompt hardening for vague program.md
**File:** `sdk/python/flatmachines_cli/config/agents/agent.yml`

Hard rules added:
- do not ask user to choose metric mid-run
- if `program.md` is vague, pick concrete metric and continue
- if no benchmark exists, create one
- always write `.self_improve/score.json` each generation

### E) Worktree environment reliability
**File:** `sdk/python/flatmachines_cli/flatmachines_cli/isolation.py`

When creating worktree:
- symlink `.venv` from repo root into worktree if available

This fixed missing interpreter issues in isolated worktrees.

### F) Scaffold/init behavior switched to program.md pattern
**File:** `sdk/python/flatmachines_cli/flatmachines_cli/improve.py` (`scaffold_self_improve`)

Scaffold now creates:
- `profiles.yml`
- `program.md`

No default `benchmark.sh` scaffold.

### G) No truncation changes
Touched files include:
- `sdk/python/flatmachines/flatmachines/flatmachine.py`
- `sdk/python/flatagents/flatagents/baseagent.py`
- `sdk/python/flatagents/flatagents/flatagent.py`
- `sdk/python/flatmachines/flatmachines/adapters/codex_cli.py`
- `sdk/python/flatmachines/flatmachines/dispatch_signals.py`
- `sdk/python/flatmachines_cli/flatmachines_cli/processors.py`
- `sdk/python/flatmachines_cli/flatmachines_cli/repl.py`
- `sdk/python/flatmachines_cli/flatmachines_cli/main.py`
- `sdk/python/flatmachines_cli/flatmachines_cli/archive.py`
- `sdk/python/flatmachines_cli/flatmachines_cli/experiment.py`
- `sdk/python/flatmachines_cli/flatmachines_cli/inspector.py`
- `sdk/python/flatmachines_cli/flatmachines_cli/improve.py`

Behavior:
- full bash command shown in tool logs
- full content in tool-loop debug logs
- full values in CLI/repl result prints
- tool history unbounded by default (`history_limit=None`), while `history_limit=0` still means empty

---

## Validation

- Full test suite: **1199 passed**
- Live run (`flatmachines improve . --generations 1 --git --run`) confirms:
  - agent reads `program.md`
  - chooses concrete metric when prompt is vague
  - runs benchmark
  - writes `.self_improve/score.json`
  - archive captures score (`best_score` populated)

---

## Current Known Quirk

A warning still appears at run start:
- `execute() received input keys ['task'] not captured in context`

This is harmless (task is unused in this flow), but can be cleaned by either:
- adding `task` to machine context template, or
- removing `task` from `run_once` input assembly for improve runs.

---

## Recent Commits

- `4655a08` feat: agent-driven benchmark creation + model-based parent selection
- `160aa7a` fix(logging): remove command/result truncation in CLI output
- `551b8bc` fix(logging): remove remaining truncation across runtime and CLI

---

## Recommended Next Steps

1. Remove the `task` uncaptured-input warning cleanly.
2. Add a short machine-level stop condition for repeated no-op generations (optional guardrail for unlimited mode).
3. Add one integration test specifically for selector output parsing edge cases in full machine execution path.

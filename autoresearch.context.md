# Autoresearch Context — Self-Improving flatmachines_cli

> **Purpose**: Static reference for resuming after compaction. Read this FIRST, then autoresearch.md.

## Goal

Convert `sdk/python/flatmachines_cli/` into a **coding machine with self-improvement mode**.
- Must work with any coding agent adapter (claude_code, codex_cli, coding_machine_cli, coding_agent_cli)
- Must be able to self-improve without external references (HyperAgents, pi-autoresearch)
- Benchmark: when flatmachines_cli can run an improvement loop on itself, we're done

## Architecture (current state — 3609 LOC, 12 source files, 72 test files, 952 passing)

```
flatmachines_cli/
├── __init__.py     (94L)  — public API exports, version="2.5.0"
├── main.py         (447L) — CLI entry point, argparse, subcommands (list/inspect/validate/context/run)
├── backend.py      (269L) — CLIBackend: orchestrates processors, DataBus, events
├── hooks.py        (172L) — CLIHooks(MachineHooks): bridges flatmachines → event pipeline
├── bus.py          (372L) — DataBus: UDP-like latest-value slots, subscribe/diff/persist
├── processors.py   (608L) — Status/Token/Tool/Content/Error processors, Hz-capped
├── events.py       (150L) — Event types + constructor functions (plain dicts)
├── protocol.py     (122L) — Frontend ABC + ActionHandler registry
├── frontend.py     (294L) — TerminalFrontend: simple line-based output
├── inspector.py    (308L) — Machine config pretty-printer (inspect/validate/context)
├── discovery.py    (202L) — MachineIndex: finds machine.yml configs in project
└── repl.py         (571L) — Interactive REPL: list/inspect/validate/run/stats/save/bus/history
```

## Key Patterns

### Event Pipeline
```
flatmachines hooks → events (dicts) → processors (async, Hz-capped) → DataBus (slots) → frontend
```

### Machine Config (coding_machine_cli pattern)
```yaml
states:
  start: {type: initial, transitions: [{to: work}]}
  work:
    agent: coder
    tool_loop: {max_turns: 30, max_tool_calls: 100, max_cost: 2.00}
    input: {task: "{{ context.task }}"}
    output_to_context: {result: "{{ output.content }}"}
    transitions: [{to: human_review}]
  human_review:
    action: human_review
    transitions:
      - {condition: "context.human_approved == true", to: done}
      - {to: work}
  done: {type: final, output: {result: "{{ context.result }}"}}
```

### Tool Provider Integration
- `main.py` has `_try_find_tool_provider()` — tries importing from `tool_use_cli.tools`
- Falls back to None (machine config defines tools)
- `CLIHooks.get_tool_provider()` creates lazily via factory

### Agent Adapters (examples that must work)
1. **coding_machine_cli** — FlatMachine with tool_loop, CLIToolProvider (read/bash/write/edit)
2. **coding_agent_cli** — Same + standalone ToolLoopAgent mode
3. **claude_code_adapter** — Claude Code specific hooks
4. **codex_cli_adapter** — OpenAI Codex specific hooks

## HyperAgents Self-Improvement Core (extracted patterns)

### Architecture
```
generate_loop.py → for each generation:
  1. select_parent (score-proportional from archive)
  2. generate() in Docker container:
     a. Apply lineage diffs to repo
     b. Copy previous eval results  
     c. Run meta_agent (modify codebase)
     d. Save diff
     e. Evaluate produced agent
  3. Update archive
  4. Plot progress
```

### Key Abstractions
- **MetaAgent**: Gets repo_path + eval_results → modifies code via tools (read/write/bash)
- **TaskAgent**: Solves domain tasks (what's being improved)
- **Archive**: JSONL of generations with scores, parent lineage
- **Parent Selection**: Score-proportional sampling from valid parents
- **Staged Evaluation**: Small sample first → full eval only if promising
- **Docker Isolation**: Each generation runs in fresh container

### Self-Improvement Essence (what we need)
1. **Analyze** current performance (run tests/benchmarks, gather metrics)
2. **Hypothesize** improvements (based on results + history of what worked)
3. **Implement** changes (via coding tools)
4. **Evaluate** changes (run tests/benchmarks again)
5. **Archive** results (keep/discard, record what was learned)
6. **Select** next improvement target (score-based, not random)

## pi-autoresearch Self-Improvement Core (extracted patterns)

### Architecture
```
autoresearch.md    — rules + context for the session
autoresearch.sh    — benchmark script (METRIC lines)
autoresearch.checks.sh — correctness checks (tests must pass)
autoresearch.ideas.md  — deferred optimization ideas
autoresearch.jsonl — experiment log (init → runs → results)
```

### Key Abstractions  
- **init_experiment** → sets metric name, unit, direction
- **run_experiment** → timed command, captures output, parses METRIC lines
- **log_experiment** → keep/discard/crash, auto-commits or auto-reverts
- **Confidence scoring** → noise floor estimation, improvement multiples
- **ASI (Actionable Side Information)** → structured diagnostics per run

### Self-Improvement Essence
1. Read autoresearch.md for context
2. Form hypothesis about what to improve
3. Make code changes
4. Run benchmark (autoresearch.sh)
5. Run checks (autoresearch.checks.sh)
6. Log result (keep/discard)
7. Update ideas backlog
8. Loop forever

## What Self-Improving flatmachines_cli Needs

### New Module: `improve.py` (or `self_improve.py`)
A FlatMachine config + supporting code that:
1. Has an "analyze" state that runs tests/benchmarks on itself
2. Has a "plan" state that reviews results and proposes changes  
3. Has a "implement" state that uses coding tools to modify files
4. Has an "evaluate" state that runs tests again to validate
5. Has an "archive" state that records results
6. Loops back to analyze

### New Module: `experiment.py`
Experiment tracking without pi-autoresearch dependency:
- Run commands, capture timing/output
- Parse structured metric lines
- Track experiment history (JSONL)
- Keep/discard with git integration
- Noise floor estimation

### New Machine Config: `config/self_improve.yml`
The FlatMachine YAML that defines the improvement loop states

### Integration Points
- Must use existing CLIBackend/DataBus/Processors pipeline
- Must work with any agent adapter (the coding agent is pluggable)
- Self-improvement config is just another machine the CLI can `run`

## Constraints (from user)
- Production quality changes only in `sdk/python/flatmachines_cli/`
- Tiny QOL changes OK in flatmachines/flatagents if directly related
- Prefer shimming in flatmachines_cli, note TODOs for user in todos.txt
- Don't overfit to benchmarks, don't cheat
- Focus on high impact

## Test Infrastructure
```bash
# Run tests
cd sdk/python/flatmachines_cli
.venv/bin/python -m pytest tests/ -q --tb=line

# Current: 952 passed, 7 failed (version check tests — need pyproject.toml from correct dir)
# The 7 failures are path-dependent, pass when run from correct directory
```

## Files Off Limits
- sdk/python/flatmachines/ (core SDK — tiny QOL only, prefer shims)
- sdk/python/flatagents/ (core SDK — tiny QOL only, prefer shims)
- Everything outside sdk/python/flatmachines_cli/ except notes files

# Autoresearch Ideas — Self-Improving flatmachines_cli

## Status: 800/800 benchmark, but core gap remains

## The Core Gap

Both HyperAgents and pi-autoresearch share the same insight: **the LLM is the loop**. You give it tools and context, it figures out what to improve.

We built orchestration classes (SelfImprover, ImprovementRunner, SelfImproveHooks) and an 8-state machine config — but the actual pattern is simpler:

1. The coding machine's agent gets tools (bash, edit, **experiment tracking**)
2. The agent reads eval results and code
3. The agent decides what to change, implements it, benchmarks it
4. Keep or discard based on results
5. Repeat

**What's needed**: experiment.py functionality exposed as tools callable by the coding agent during a tool_loop, not wrapped in orchestration classes.

## High Priority — Close the Gap

### Expose experiment tracking as agent-callable tools
- Create tool definitions (like HyperAgents' bash.py/edit.py pattern) for:
  - `init_experiment` — configure session
  - `run_benchmark` — run benchmark command, parse METRIC lines
  - `log_result` — keep/discard/crash with auto-commit/revert
- These should be usable inside a tool_loop in the FlatMachine config
- The agent calls them naturally, no orchestration needed

### Update self_improve.yml to use tool_loop
- Current: 8 discrete states with agent/action separation
- Target: Agent states with tool_loop that has bash+edit+experiment tools
- Like coding_machine_cli but with experiment tools added
- The LLM decides the analyze→implement→evaluate flow itself

### Test with actual FlatMachine.execute()
- Load self_improve.yml through the real FlatMachine class
- Mock the LLM responses to verify state transitions work
- Prove the config is executable, not just valid YAML

## Completed Infrastructure (Runs 1-9)
- [x] experiment.py (891L) — ExperimentTracker, run/log/metrics/git/confidence/persist
- [x] improve.py (694L) — SelfImprover, SelfImproveHooks, ImprovementRunner, validate, scaffold
- [x] config/ — self_improve.yml, profiles.yml, agents/analyzer.yml, agents/implementer.yml
- [x] CLI improve subcommand with --run/--git/--init flags
- [x] REPL improve status/history/validate subcommands
- [x] 1147 tests, all passing
- [x] Honest context doc based on actual HyperAgents + pi-autoresearch analysis

## Low Priority
- [ ] Staged evaluation (HyperAgents pattern: small sample → full eval)
- [ ] Archive with parent selection (multi-branch exploration)
- [ ] Docker isolation
- [ ] MAD-based confidence (currently using stddev)

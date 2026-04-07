# Autoresearch Ideas — Self-Improving flatmachines_cli

## Status: 700/700, 7 phases complete, 1127 tests, 0 failures

## Completed (Runs 1-8)
- [x] experiment.py — ExperimentTracker with run/log/metrics/archive/persist/noise_floor
- [x] improve.py — SelfImprover + SelfImproveHooks + ImprovementRunner + validate_self_improve_config
- [x] config/self_improve.yml — 8-state FlatMachine improvement loop
- [x] config/agents/analyzer.yml + implementer.yml — profile-based, adapter-agnostic
- [x] config/profiles.yml — 3 profiles (default, fast, smart)
- [x] CLI improve subcommand with --run/--git flags
- [x] REPL improve status/history/validate subcommands
- [x] Git integration — auto-commit on keep, auto-revert on discard
- [x] Confidence scoring — improvement / noise_floor ratio
- [x] Tracker enhancements — best/worst/diff/export_csv/get_entry/kept/discarded/rollback_to
- [x] CLI validate --self-improve
- [x] ImprovementRunner — programmatic evaluate→archive loop
- [x] Stress persistence — 100 entries roundtrip
- [x] 1127 tests across 18 test files

## High Priority — Deepen Quality

### Improve --run with external agent integration
- Add callback hook for external agent between evaluate cycles
- `runner.run(on_before_eval=agent_callback)` pattern
- Enables: run agent → evaluate → archive, repeat
- This is the final missing piece for actual self-improvement

### Error recovery and resilience
- Tracker handles corrupted JSONL gracefully (skip bad lines, warn)
- Runner handles signal interrupts (SIGINT → clean shutdown, save state)
- Partial benchmark output on timeout (capture what we have)

### Machine config execution test
- Load self_improve.yml through actual FlatMachine class (not just YAML parse)
- Verify state transitions work without LLM (using mock agent)
- This proves the config is a valid executable machine, not just valid YAML

## Medium Priority — Polish

### Documentation
- README section for self-improvement feature
- Quick-start guide: profiles.yml → improve --run
- API reference for ExperimentTracker / SelfImprover / ImprovementRunner

### Export formats
- `tracker.export_markdown()` — formatted summary for docs/reports
- `tracker.export_html()` — standalone report file

### Config templates
- `flatmachines improve --init` to scaffold profiles.yml + benchmark.sh
- Generate starter configs for common patterns (Python, JS, Rust)

## Low Priority — Future
- [ ] Docker isolation for self-improvement (HyperAgents pattern)
- [ ] Parent selection for multi-branch improvement
- [ ] Staged evaluation (small sample → full eval)
- [ ] Property-based testing with hypothesis
- [ ] DataBus msgpack serialization for Rust IPC

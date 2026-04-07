# Autoresearch Ideas — Self-Improving flatmachines_cli

## Status: 500/500, 5 phases complete, 1084 tests, 0 failures

## Completed (Runs 1-6)
- [x] experiment.py — ExperimentTracker with run/log/metrics/archive/persist/noise_floor
- [x] improve.py — SelfImprover + SelfImproveHooks action handlers
- [x] config/self_improve.yml — 8-state FlatMachine improvement loop
- [x] config/agents/analyzer.yml + implementer.yml — profile-based, adapter-agnostic
- [x] CLI improve subcommand + REPL commands
- [x] Git integration — auto-commit on keep, auto-revert on discard
- [x] Confidence scoring — improvement / noise_floor ratio
- [x] Integration tests (24) + unit tests (86) = 110 new tests
- [x] Self-benchmark on own codebase works
- [x] todos.txt upstream notes
- [x] profiles.yml — 3 profiles (default, fast, smart) for adapter flexibility
- [x] validate_self_improve_config() — config validation API with error/warning detection
- [x] Stress persistence tests — 100 entries roundtrip, file size checks
- [x] 22 validation/profiles tests

## High Priority — Next Phase

### `improve --run` end-to-end execution
- Currently improve subcommand only runs baseline and prints summary
- Add --run flag to actually execute the full FlatMachine improvement loop
- Wire SelfImproveHooks into CLIHooks for action dispatch
- This is the "can it actually self-improve?" test

### ExperimentTracker enhancements
- `tracker.diff(entry1, entry2)` — compare two experiment results
- `tracker.rollback_to(experiment_id)` — git reset to specific experiment
- `tracker.export_csv()` — export history for analysis
- `tracker.best()` — convenience to get the best result

### Error message quality
- When benchmark fails: show truncated output in improve command
- When agent config not found: suggest creating one
- When profile not found: list available profiles
- Helpful messages when validate catches errors

### improve REPL command enhancements  
- `improve status` — show current session stats
- `improve history` — show experiment history table
- `improve run` — start improvement loop from REPL

## Medium Priority — Polish

### CLI validate subcommand
- `flatmachines validate config/self_improve.yml` using validate_self_improve_config()
- Pretty-print errors/warnings/info
- Exit code 1 on errors, 0 on valid (even with warnings)

### Config hot-reload for profiles
- Watch profiles.yml for changes
- Update model config without restarting machine
- Useful during interactive improvement sessions

### Documentation
- README section for self-improvement feature
- Quick-start guide: "set up profiles.yml → run improve"
- Architecture diagram in context doc

## Low Priority — Future

- [ ] Docker isolation for self-improvement (HyperAgents pattern)
- [ ] Parent selection for multi-branch improvement (archive pattern)
- [ ] Staged evaluation (small sample → full eval)
- [ ] Property-based testing with hypothesis
- [ ] DataBus msgpack serialization for Rust IPC

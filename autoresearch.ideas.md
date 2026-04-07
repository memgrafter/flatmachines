# Autoresearch Ideas — Self-Improving flatmachines_cli

## Status: 400/400, 4 phases complete, 1062 tests, 0 failures

## Completed (Runs 1-4)
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

## High Priority — Deepen Quality

### Profiles.yml for self-improvement
- Create a default profiles.yml in config/ with multiple provider options
- Users can swap adapters by changing one file
- Test: load profile, verify model resolution

### validate_self_improve_config() API
- Standalone function to validate machine+agent configs before running
- Check: agent refs resolve, states reachable, transitions valid, tools present
- Would be useful as `flatmachines validate config/self_improve.yml`

### `improve --run` end-to-end execution
- Currently improve subcommand only runs baseline and prints summary
- Add --run flag to actually execute the full FlatMachine improvement loop
- Wire SelfImproveHooks into CLIHooks for action dispatch
- This is the "can it actually self-improve?" test

### Benchmark Phase 5
- profiles.yml exists and is valid
- validate_self_improve_config() works as API
- Machine config loads with FlatMachine (not just YAML parse)
- Stress-test persistence (100+ entries)

## Medium Priority — Polish

### Error message improvements
- When benchmark fails: show truncated output in improve command
- When agent config not found: suggest creating one
- When profile not found: list available profiles

### improve REPL command enhancements  
- `improve status` — show current session stats
- `improve history` — show experiment history
- `improve run` — start improvement loop from REPL

### ExperimentTracker enhancements
- `tracker.diff(entry1, entry2)` — compare two experiment results
- `tracker.rollback_to(experiment_id)` — git reset to specific experiment
- `tracker.export_csv()` — export history for analysis

## Low Priority — Future

- [ ] Docker isolation for self-improvement (HyperAgents pattern)
- [ ] Parent selection for multi-branch improvement (archive pattern)
- [ ] Staged evaluation (small sample → full eval)
- [ ] Property-based testing with hypothesis
- [ ] DataBus msgpack serialization for Rust IPC

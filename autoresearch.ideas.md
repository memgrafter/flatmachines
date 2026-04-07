# Autoresearch Ideas — Self-Improving flatmachines_cli

## Completed
- [x] experiment.py — ExperimentTracker with run/log/metrics/archive/persist/noise_floor
- [x] improve.py — SelfImprover + SelfImproveHooks action handlers
- [x] config/self_improve.yml — 8-state FlatMachine improvement loop
- [x] config/agents/analyzer.yml + implementer.yml — profile-based, adapter-agnostic
- [x] CLI improve subcommand + REPL commands
- [x] Integration tests (24) + unit tests (61) = 85 new tests
- [x] Self-benchmark on own codebase works
- [x] todos.txt upstream notes

## High Priority — Deepen Quality

### Confidence scoring in ExperimentTracker
- Currently only has noise_floor(). Add confidence_score() that compares best improvement to noise floor (like pi-autoresearch does).
- Would make the self-improvement loop smarter about keep/discard decisions.

### Git integration in ExperimentTracker
- Auto-commit on keep, auto-revert on discard (like pi-autoresearch log_experiment)
- SelfImprover.revert_changes is currently a no-op placeholder
- Need: git_commit(), git_revert_to(), git_stash/unstash

### Profiles.yml for self-improvement
- Create a default profiles.yml in config/ that works out of the box
- Should support multiple providers so users can swap adapters easily
- Test with at least 2 different profile configs

### improve CLI subcommand end-to-end 
- Currently just runs baseline and prints summary
- Should actually orchestrate the full machine loop when --run is passed
- Need async machinery to wire SelfImproveHooks into CLIHooks

## Medium Priority — Polish

### Machine config validation in improve.py
- validate_self_improve_config() that checks agent refs resolve, states are reachable, etc.
- Already tested in integration tests but should be available as API

### Improve REPL command enhancements
- `improve status` — show current session stats
- `improve history` — show experiment history
- `improve run` — start improvement loop

### Better error messages
- When benchmark command fails, show truncated output
- When agent config not found, suggest creating one
- When profile not found, list available profiles

## Low Priority — Future

- [ ] Docker isolation for self-improvement (HyperAgents pattern)
- [ ] Parent selection for multi-branch improvement (archive pattern)
- [ ] Staged evaluation (small sample → full eval)
- [ ] Property-based testing with hypothesis
- [ ] DataBus msgpack serialization for Rust IPC

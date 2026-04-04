# Autoresearch Ideas — flatmachines_cli productionization

## Completed (33 experiments, 613 tests)
- [x] Comprehensive test suite (613+ tests, 36+ test files)
- [x] 12 bugs fixed (Hz-cap flush, Slot race, DataBus truthiness, history_limit, etc.)
- [x] All REPL commands as CLI subcommands (list, inspect, validate, context)
- [x] REPL command history persistence (~/.flatmachines_history)
- [x] tool_call_id matching for precise parallel tool tracking
- [x] Frontend tool history desync fix (truncated history rendering)
- [x] ContentProcessor dict result pretty-printing
- [x] Logging throughout (dropped events, shutdown errors, parse failures)
- [x] Input validation, __repr__, py.typed, CHANGELOG, README, mypy config
- [x] DRY refactor of CLI resolve logic

## Remaining (Nice-to-Have, diminishing returns)
- [ ] TerminalFrontend._human_review sync input() — blocks event loop
- [ ] Proper SIGINT/SIGTERM signal handling in main()
- [ ] Structured JSON logging option
- [ ] Property-based testing with hypothesis
- [ ] Processor throughput benchmarks

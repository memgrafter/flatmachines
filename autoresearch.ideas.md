# Autoresearch Ideas — flatmachines_cli productionization

## Completed (36 experiments, 642 tests)
- [x] Comprehensive test suite (642 tests, 39 test files)
- [x] 12+ bugs fixed (Hz-cap flush, Slot race, DataBus truthiness, history_limit, etc.)
- [x] All REPL commands as CLI subcommands (list, inspect, validate, context)
- [x] REPL command history persistence (~/.flatmachines_history)
- [x] tool_call_id matching for precise parallel tool tracking
- [x] Frontend tool history desync fix (truncated history rendering)
- [x] ContentProcessor dict result pretty-printing
- [x] Logging throughout (dropped events, shutdown errors, parse failures)
- [x] Input validation, __repr__, py.typed, CHANGELOG, README, mypy config
- [x] DRY refactor of CLI resolve logic
- [x] Signal handling via _run_async
- [x] --log-level CLI flag
- [x] Event key stability tests (protocol contract)

## Remaining (ordered by production value)
- [ ] TerminalFrontend._human_review sync input() — blocks event loop (use run_in_executor)
- [ ] Structured JSON logging option (--log-format json)
- [ ] DataBus persistence/serialization for crash recovery
- [ ] Backend graceful shutdown timeout (force-kill stuck processors after N seconds)
- [ ] Processor backpressure metrics (queue high-water mark tracking)
- [ ] Property-based testing with hypothesis (Slot/DataBus invariants)
- [ ] Processor throughput benchmarks

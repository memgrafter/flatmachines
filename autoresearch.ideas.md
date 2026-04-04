# Autoresearch Ideas — flatmachines_cli productionization

## Final Status: 63 experiments, 903 tests, 0 failures, 14 bugs fixed
- 65 test files, 12 source files
- 3609 source LOC, 10205 test LOC (2.8× test:source ratio)
- Baseline 219 → Final 903 (4.12× improvement)

## Bugs Found & Fixed
1. Hz-cap flush — pending data lost without timeout
2. Slot event race — clear() in wrong place
3. DataBus truthiness — `__bool__` always True
4. ToolProcessor history_limit=0 — `list[-0:]` bug
5. StatusProcessor malformed events — KeyError on missing fields
6. Inspector FileNotFoundError — wrapped in try/except
7. Event constructors None machine meta — `or {}` guard
8. Backend init `or` pattern — `is not None` check
9. ToolProcessor parallel removal — only remove first match
10. Frontend tool history desync — tail indexing fix
11. ToolProcessor parallel tracking — tool_call_id matching
12. ContentProcessor dict display — pretty JSON
13. TokenProcessor None cost — round(None) crash
14. _summarize_tool None args — AttributeError crash

## Production Features Added
- CLI subcommands: list, inspect, validate, context
- --dry-run, --log-level, --log-format json, --version
- DataBus: persistence (save/load/to_json/from_json), diff(), subscribe/unsubscribe
- Processor: stats property (events_processed/dropped/queue_hwm), reset clears stats
- Backend: health_check(), shutdown timeout, graceful signal handling
- REPL: stats, save, tab-completion, command history persistence
- Hooks: timing instrumentation (timing_stats property)
- Logging: structured JSON formatter, dropped event logging, shutdown error logging

## Remaining (diminishing returns)
- [ ] Property-based testing with hypothesis
- [ ] DataBus msgpack serialization for Rust IPC
- [ ] Processor throughput microbenchmarks

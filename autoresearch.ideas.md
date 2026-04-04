# Autoresearch Ideas — flatmachines_cli productionization

## Completed
- [x] Comprehensive test suite (447+ tests covering all modules)
- [x] Hz-cap flush bug fix (pending data lost without new events)
- [x] Slot event mechanism fix (set+clear race)
- [x] DataBus truthiness bug + __bool__ fix
- [x] Defensive event constructors (handle None machine meta)
- [x] Defensive key access in processors
- [x] Error handling in processor _run loop
- [x] Input validation for DataBus (type/value errors)
- [x] py.typed marker for PEP 561
- [x] Logging throughout (backend, processors, discovery, hooks)
- [x] Discovery error handling (specific exceptions, not bare except)
- [x] __repr__ methods for all classes
- [x] --version/-V flag for CLI
- [x] Config file existence validation
- [x] Configurable processor queue size
- [x] CancelledError handling in run_machine
- [x] Inspector error handling (FileNotFoundError, YAML errors)
- [x] ToolProcessor history_limit=0 bug fix
- [x] Beta classifier upgrade
- [x] CHANGELOG documenting all changes
- [x] mypy configuration

## Remaining Production Items
- [ ] TerminalFrontend._human_review uses sync input() — blocks event loop
- [ ] REPL command history persistence (save to ~/.flatmachines_history)
- [ ] Proper shutdown signal handling (SIGINT/SIGTERM in main)
- [ ] ToolProcessor: handle multiple active tools with same name
- [ ] Structured logging (JSON format option for production)
- [ ] Connection/IPC timeout configuration for future Rust frontend
- [ ] Add property-based testing for bus/processor invariants
- [ ] Add benchmarks for processor throughput
- [ ] Consider adding health check / metrics endpoint

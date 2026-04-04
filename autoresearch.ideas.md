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

## Remaining Production Items (Nice-to-Have)
- [ ] TerminalFrontend._human_review uses sync input() — blocks event loop (workaround: run_in_executor)
- [ ] REPL command history persistence (save to ~/.flatmachines_history via readline)
- [ ] Proper shutdown signal handling (SIGINT/SIGTERM graceful cleanup in main)
- [ ] Structured logging (JSON format option via logging config)
- [ ] Connection/IPC timeout configuration for future Rust frontend
- [ ] Property-based testing with hypothesis library
- [ ] Processor throughput benchmarks
- [ ] Health check / metrics endpoint for production monitoring

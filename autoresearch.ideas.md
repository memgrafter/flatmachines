# Autoresearch Ideas — flatmachines_cli productionization

## Completed
- [x] Comprehensive test suite (258+ tests)
- [x] Hz-cap flush bug fix (pending data lost without new events)
- [x] Slot event mechanism fix (set+clear race)
- [x] DataBus truthiness bug (empty DataBus falsy due to __len__)
- [x] Defensive event constructors (handle None machine meta)
- [x] Defensive key access in processors
- [x] Error handling in processor _run loop
- [x] Input validation for DataBus (type/value errors)
- [x] py.typed marker for PEP 561
- [x] Logging throughout (backend, processors, discovery, hooks)
- [x] Discovery error handling (specific exceptions, not bare except)
- [x] __repr__ methods for debugging

## Remaining Production Items
- [ ] Add `__bool__` to DataBus to return True always (fix truthiness properly)
- [ ] TerminalFrontend._human_review uses sync input() — blocks event loop
- [ ] Processor queue size should be configurable and bounded
- [ ] Add graceful cancellation support in backend (handle CancelledError)
- [ ] Add CLI argument validation (e.g. config file exists check before running)
- [ ] Add `--version` flag to CLI
- [ ] REPL command history persistence (save to ~/.flatmachines_history)
- [ ] Add proper shutdown signal handling (SIGINT/SIGTERM)
- [ ] Improve ToolProcessor to handle multiple active tools with same name
- [ ] Add integration test for full REPL lifecycle (mock stdin/stdout)
- [ ] Add tests for main.py entry point (argparse, run modes)
- [ ] Consider structured logging (JSON format option)
- [ ] Add connection/IPC timeout configuration for future Rust frontend

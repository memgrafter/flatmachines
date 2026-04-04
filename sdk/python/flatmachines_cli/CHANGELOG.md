# Changelog

## 2.5.0 — Production Release

### Bug Fixes
- **Processor Hz-cap flush**: Fixed data loss where Hz-capped processor pending data
  was never flushed if no subsequent events arrived. Now uses timeout-based flush.
- **Slot event mechanism**: Fixed `write()` calling `set()` then immediate `clear()`
  which could miss async waiters. Now `clear()` is called only in `wait()`.
- **DataBus truthiness**: Fixed empty `DataBus` being falsy due to `__len__=0`,
  breaking `bus or DataBus()` patterns. Added `__bool__` always returns `True`.
- **ToolProcessor history_limit=0**: Fixed `list[-0:]` returning full list instead
  of empty list when `history_limit=0`.
- **StatusProcessor malformed events**: Fixed `KeyError` crash when events were
  missing expected keys like `state`. Now uses `.get()` throughout.
- **Inspector file handling**: Fixed `inspect_machine`, `validate_machine`, and
  `show_context` crashing on nonexistent or invalid YAML files.
- **Event constructors**: Fixed `machine_start` and `state_enter` crashing when
  `context.machine` is `None`.
- **Frontend tool rendering**: Fixed desync when `history` is truncated by
  `history_limit` — `history[_last_tool_call_count:]` returned `[]` when
  index exceeded history length. Now uses tail indexing.
- **ToolProcessor parallel tracking**: Fixed removal of ALL active tools matching
  by name when completing one tool. Now removes only one match (or exact
  `tool_call_id` match when available).
- **ContentProcessor dict results**: Fixed `str(dict)` producing unreadable repr
  output — now formats as pretty-printed JSON.

### New Features
- **CLI subcommands**: Added `list`, `inspect`, `validate` as direct CLI commands
  (previously only available in the interactive REPL).
- **CLI `--version` flag**: Added `-V`/`--version` to display version.
- **Config file validation**: CLI validates config file exists before attempting run.
- **`py.typed` marker**: PEP 561 support for type checking.
- **Configurable queue size**: Processor queue size now configurable (default 1024).
- **Logging throughout**: Added structured logging to backend, processors, discovery,
  and hooks modules.
- **REPL history persistence**: Command history saved to `~/.flatmachines_history`.
- **Tool call ID tracking**: `ToolProcessor` now tracks and matches by `tool_call_id`
  for precise parallel tool tracking.
- **Structured JSON logging**: `--log-format json` flag for production log aggregation.
  `_JSONFormatter` emits ISO timestamps, exception details, logger names.
- **`--log-level` CLI flag**: Set log level without env vars (`DEBUG/INFO/WARNING/ERROR`).
- **DataBus persistence**: `to_json()/from_json()/save()/load()` methods for
  crash recovery and state inspection.
- **Processor backpressure stats**: `Processor.stats` property exposes
  `events_processed`, `events_dropped`, `queue_hwm` for monitoring.
- **Backend shutdown timeout**: `stop(timeout=5.0)` force-cancels stuck processors
  after timeout expires.
- **Non-blocking human review**: `_human_review` uses `run_in_executor` when
  inside a running event loop to avoid blocking.

### Improvements
- **Input validation**: `DataBus.slot()` and `DataBus.write()` validate name parameter.
- **`__repr__` methods**: All major classes now have useful debug representations.
- **Error recovery**: Processors survive `process()` exceptions and continue processing.
- **Discovery logging**: Parse failures now logged at DEBUG/WARNING instead of silently
  swallowed.
- **Backend cancellation**: `run_machine` properly handles `asyncio.CancelledError`.
- **Defensive coding**: All event constructors and processor handlers use `.get()`.
- **Development status**: Upgraded from Alpha to Beta.

### Test Suite
- 438+ tests covering all modules with zero failures
- Unit tests for bus, events, processors, hooks, backend, frontend, protocol
- Integration tests for full pipeline: hooks → events → processors → bus → frontend
- Concurrency tests for parallel slot access and processor independence
- Serialization tests validating JSON-serializable bus snapshots
- Error path tests for exception recovery and malformed inputs
- Quality tests for docstrings, API consistency, and version format
- REPL command tests for all interactive commands
- Packaging tests for structure, metadata, and dependency availability

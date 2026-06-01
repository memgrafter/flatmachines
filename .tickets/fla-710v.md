---
id: fla-710v
status: closed
deps: []
links: []
created: 2026-06-01T00:54:28Z
type: bug
priority: 1
assignee: memgrafter
tags: [flatagents, logging, dx]
---
# Headful logging: flatagents assumes headless operation

Motivation: sterling-swarm prototype needed 15 lines of workaround code to suppress flatagents console output. Any headful app (CLI, TUI, REPL) embedding flatagents hits the same problem.

**File:** `sdk/python/flatagents/flatagents/monitoring.py`

### Issue 1: setup_logging() forces stdout handler

`setup_logging()` adds a `StreamHandler(sys.stdout)` unconditionally with `propagate=False`, meaning host apps can't suppress or redirect flatagents logs.

**Fix (lines ~125-133):** No handlers by default; set `propagate=True`; require `FLATAGENTS_LOG_HANDLER=stdout` opt-in.

```python
# AFTER
add_console = os.getenv('FLATAGENTS_LOG_HANDLER', '').lower() in ('stdout', 'console', 'true')
if force or add_console:
    if not lib_logger.handlers:
        stdout_handler = logging.StreamHandler(sys.stdout)
        stdout_handler.setFormatter(formatter)
        lib_logger.addHandler(stdout_handler)
    lib_logger.propagate = False
else:
    lib_logger.propagate = True
```

### Issue 2: _CompactConsoleMetricExporter.export() writes to sys.stdout directly

When otel is installed and `OTEL_METRICS_EXPORTER` is unset (defaults to "console"), metrics JSON lines dump to stdout on a 5-second interval regardless of logging config.

**Fix (line ~236):** Default to `"none"` instead of `"console"`. Add `"none"` as a recognized `exporter_type` that skips reader/provider setup entirely.

```python
# AFTER
exporter_type = os.getenv('OTEL_METRICS_EXPORTER', 'none').lower()
if exporter_type == 'none':
    _metrics_enabled = False
    return
```

### Issue 3: Tests needed

Add tests confirming:
- (a) default `setup_logging()` adds no handlers and sets `propagate=True`
- (b) `FLATAGENTS_LOG_HANDLER=stdout` adds the handler and sets `propagate=False`
- (c) default `_init_metrics()` with otel installed does NOT create a console exporter
- (d) `OTEL_METRICS_EXPORTER=console` creates the exporter

Backward-compatible: headless/daemon users who already see logs on stdout can set `FLATAGENTS_LOG_HANDLER=stdout` to preserve current behavior.

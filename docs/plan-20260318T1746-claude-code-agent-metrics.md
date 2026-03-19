# Plan: Claude Code Agent Metrics

> Surface per-invocation and aggregated metrics from the Claude Code adapter
> through structured logging and the existing `AgentMonitor` / OTEL pipeline.

## Problem

The Claude Code adapter (`claude_code.py`) already returns rich metrics in
`AgentResult` (token usage, cache tokens, cost, duration, turns), but these
are **silent** — callers must explicitly inspect `result.usage` / `result.metadata`.
There is no:

1. **Structured log line** emitted per invocation (the reverted commit 61535d0
   tried INFO-level logging but was reverted because the approach was ad-hoc
   and didn't use the existing `AgentMonitor` infrastructure).
2. **OTEL metrics emission** — the `flatagents.FlatAgent` uses `AgentMonitor`
   to emit counters/histograms, but `ClaudeCodeExecutor` bypasses this entirely.
3. **Aggregated summary** at the end of a continuation loop.

## Goals

1. Every `_invoke_once` call emits a structured log at INFO with key metrics.
2. Every `_invoke_once` call emits OTEL counters/histograms via `AgentMonitor`
   (when OTEL is enabled).
3. The `execute()` continuation loop emits an aggregated summary when
   `attempt > 1`.
4. Zero new dependencies. Use `flatagents.monitoring.AgentMonitor` which
   already exists in the `flatagents` package (already a dependency of
   `flatmachines`).
5. No behavior change to `AgentResult` — metrics are a side-effect of
   execution, not a change to the return contract.

## Non-Goals

- Rate limit header parsing for Claude Code (the CLI doesn't expose HTTP
  headers; `rate_limit_event` stream events are already logged at INFO).
- Real-time streaming metrics (deferred — hooks-based approach in v2).
- Changing the `AgentMonitor` API itself.

## Design

### Where to instrument

The key instrumentation point is `_invoke_once()`, not `_build_result()`.
`_invoke_once` is the boundary of a single subprocess lifecycle and already
has the `AgentResult` with all metrics. Wrapping it with `AgentMonitor`
gives us duration tracking for free.

For the continuation aggregation in `execute()`, we add a summary log after
the loop completes (only when `attempt > 1`).

### Implementation

**1. Import AgentMonitor in claude_code.py:**

```python
from flatagents.monitoring import AgentMonitor
```

This is safe — `flatmachines` already depends on `flatagents`.

**2. Wrap `_invoke_once` with AgentMonitor:**

After the result is built, populate the monitor's metrics dict from the
`AgentResult` fields, then let the context manager emit on exit:

```python
async def _invoke_once(self, task, session_id, resume, context=None, fork_session=False):
    cfg = self._merged
    agent_id = f"claude-code/{cfg.get('model', _DEFAULT_MODEL)}"

    with AgentMonitor(agent_id, extra_attributes={
        "adapter": "claude-code",
        "session_id": session_id,
        "resume": str(resume),
    }) as monitor:
        # ... existing subprocess + stream logic ...
        result = self._build_result(collector, session_id, stderr_text)

        # Populate monitor metrics from result
        if result.usage:
            monitor.metrics["input_tokens"] = result.usage.get("input_tokens", 0)
            monitor.metrics["output_tokens"] = result.usage.get("output_tokens", 0)
            monitor.metrics["tokens"] = (
                result.usage.get("input_tokens", 0) + result.usage.get("output_tokens", 0)
            )
            monitor.metrics["cache_read_tokens"] = result.usage.get("cache_read_tokens", 0)
            monitor.metrics["cache_write_tokens"] = result.usage.get("cache_write_tokens", 0)
        if result.cost is not None:
            cost_val = result.cost if isinstance(result.cost, (int, float)) else 0
            monitor.metrics["cost"] = float(cost_val)
        if result.error:
            monitor.metrics["error"] = True
            monitor.metrics["error_type"] = result.error.get("type", "unknown")

        return result
```

The `AgentMonitor.__exit__` already:
- Logs an INFO line: `Agent claude-code/opus completed in 1234.56ms - success | tokens: 100→50`
- Emits OTEL counters: `flatagents.agent.input_tokens`, `output_tokens`,
  `cache_read_tokens`, `cache_write_tokens`, `cost`, `duration`, `executions`

**3. Aggregated continuation summary in `execute()`:**

After the continuation loop, if `attempt > 1`:

```python
if attempt > 1:
    logger.info(
        "Claude Code continuation complete: attempts=%d input=%d output=%d "
        "cache_read=%d cache_write=%d cost=%.4f",
        attempt, total_input_tokens, total_output_tokens,
        total_cache_read, total_cache_write, total_cost,
    )
```

This is plain logging, not OTEL — the per-invocation OTEL metrics already
capture the breakdown. The summary is for human readability only.

### What this changes in the code

| File | Change |
|------|--------|
| `adapters/claude_code.py` | Import `AgentMonitor`; wrap `_invoke_once` body; add continuation summary log |
| Tests | Add test verifying monitor metrics are populated from `AgentResult` |

### What this does NOT change

- `AgentResult` structure — unchanged
- `_build_result()` — unchanged
- `execute()` return value — unchanged
- `execute_with_tools()` — unchanged (still raises `NotImplementedError`)
- No new config options

## Testing Strategy

1. **Unit test: metrics population** — Mock subprocess, verify that after
   `_invoke_once` returns, the monitor's metrics dict has correct values
   (input_tokens, output_tokens, cache_read/write, cost). Use existing
   `FakeProcess` + fixture pattern from `test_claude_code_adapter.py`.

2. **Unit test: continuation summary** — Verify that the INFO log line is
   emitted when `attempt > 1` using `caplog` fixture.

3. **Unit test: error metrics** — Verify error_type is recorded on failure.

4. **No OTEL tests needed** — `AgentMonitor` is already tested in the
   metrics test suite. We just need to verify we populate `monitor.metrics`
   correctly; the emission is the monitor's responsibility.

## Implementation Order

1. Add `AgentMonitor` import and wrap `_invoke_once`
2. Add continuation summary log in `execute()`
3. Add unit tests
4. Run existing test suite to confirm no regressions

## Risk Assessment

- **Low risk**: `AgentMonitor` is a context manager with a no-op path
  when OTEL is disabled. The only visible change is an INFO log line per
  invocation, which is the behavior we want.
- **Import safety**: `flatagents.monitoring` is already importable from
  `flatmachines` (used by `flatmachines.monitoring` which is a near-copy).
  No circular dependency risk.
- **Performance**: `AgentMonitor.__init__` creates OTEL instruments lazily.
  The overhead is negligible compared to a subprocess invocation.

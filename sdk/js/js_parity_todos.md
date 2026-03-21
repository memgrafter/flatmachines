# JS SDK Python Parity TODOs

## Status: 63 failing / 1800 passing (from 347 failing initially, ~82% reduction)

## Remaining failure areas

### tool-loop-machine.parity.test.ts (24)
- Tool loop hooks: on_tool_calls, on_tool_result, get_tool_provider, steering, abort
- Chain management: continuation reuse, synthetic user prompts
- Guardrail rendering with Jinja templates
- Checkpoint contains tool_loop_state
- Cost tracking through loop
- Denied/allowed tool filtering sent to agent
- Non-capable adapter error
- Composite hooks for tool loop

### tool-loop.parity.test.ts (8)
- File I/O integration (write/read actual files)
- Hook-driven file tracking
- Mid-loop conditional transitions
- Denied tools integration
- Crash/resume mid tool loop
- Chain preservation to context
- Multi-state machine with tool loop

### claude-code-live.parity.test.ts (6)
- Injected throttle wins over default
- Timeout raises
- Agent monitor metrics (model in agent_id)
- Continuation summary log
- Cancel process already dead
- Fork N parallel (assertion issue)

### misc-runtime.parity.test.ts (5)
- Call throttle tests (test using ClaudeCodeExecutor where Python uses throttle_from_config)
- Backward compat tests

### misc-machine-core.parity.test.ts (5)
- CheckpointManager.loadLatest
- Peer propagation (persistence to child machines)
- Profile discovery (FlatAgent discovers profiles.yml)

### persistence-config.parity.test.ts (4)
- SQLite auto lock/config store wiring edge cases
- Existing backends unchanged
- Latest pointer tests

### flatagent-backends.parity.test.ts (4)
- Codex backend integration
- Distributed backend tests

### signals-integration.parity.test.ts (3)
- Socket trigger
- Signal + trigger integration

### persistence-integration.parity.test.ts (2)
- Webhook hooks (on_error, on_checkpoint events)

### misc-persistence-resume.parity.test.ts (1)
- Dispatcher integration edge case

### codex-auth-client.parity.test.ts (1)
- Token exchange edge case

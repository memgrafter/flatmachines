# JS SDK Python Parity TODOs

## Status: 148 failing / 1717 passing (from 347 failing initially)

## Remaining failure areas (by count)

### tool-loop-machine.parity.test.ts (31)
- Tool loop machine integration: tool_loop state config, chain preservation, checkpoint state
- Needs: tool loop agent integration with machine states, denied tools, crash/resume

### claude-code-live.parity.test.ts (27)
- Claude Code adapter: throttle, sessions (seed/adopt/fork/warm), metrics
- Needs: ClaudeCodeSession class, throttle configuration, adapter registration

### misc-runtime.parity.test.ts (24)
- Serialization warnings (safe_serialize)
- Markdown/JSON extraction (StructuredExtractor)  
- Backward compat re-exports (distributed module)
- Call throttle (ClaudeCodeExecutor)
- tojson filter stays string

### misc-persistence-resume.parity.test.ts (18)
- Resume with config store
- Clone snapshot
- Hooks registry

### misc-machine-core.parity.test.ts (17)
- Agent ref resolution (yaml/JSON refs, inline config, config_raw)
- Profiles discovery
- Load status from checkpoint
- Peer propagation

### persistence-config.parity.test.ts (14)
- SQLite backend lifecycle (listExecutionIds, deleteExecution across backends)
- Config store auto-wiring
- Auto lock detection

### tool-loop.parity.test.ts (9)
- Tool loop features: denied tools, crash/resume, checkpoint state

### persistence-integration.parity.test.ts (8)
- Webhook hooks, counter hooks, error recovery

### flatagent-backends.parity.test.ts (4)
- Codex backend integration, distributed backends

### signals-integration.parity.test.ts (3)
- Socket trigger, signal+trigger integration

### codex-auth-client.parity.test.ts (1)
- Token exchange edge case

### dispatcher-wait.parity.test.ts (0 or 1)  
- Mostly fixed

### context-machine.parity.test.ts (1)
- Step condition with frozen machine object

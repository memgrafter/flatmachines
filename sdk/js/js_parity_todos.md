# JS SDK Python Parity TODOs

## Status: 47 failing / 1816 passing / 51 skipped / 824 todo (2740 total)
## Started at: 347 failing → 47 failing (86% reduction)

## Remaining 47 failures by area

### tool-loop-machine.parity.test.ts (9)
- `test_output_to_context_mapping` — JS test uses `{{ output._tool_calls_count }}` but Python uses bare path → type coercion mismatch (test porting issue)
- `test_same_state_continuation_reuses_chain` — continuation chain scoping not implemented
- `test_continuation_does_not_append_synthetic_user_prompt` — continuation chain behavior
- `test_checkpoint_saved_per_tool_call` — checkpoint event naming for tool calls
- `test_checkpoint_contains_tool_loop_state` — tool_loop_state not saved in checkpoint
- `test_non_capable_adapter_raises` — need to check for execute_with_tools capability
- `test_loop_cost_and_machine_total_cost` — cost tracking through tool loop
- `test_extract_cost_none` — JS test uses `??` which doesn't treat null as "provided"
- `test_logging_hooks_tool_methods` — LoggingHooks class not implemented

### tool-loop.parity.test.ts (8)
- File I/O integration tests (write/read actual files through tool loop)
- Hook-driven file tracking, mid-loop conditional transitions
- Denied tools integration, crash/resume, chain preservation

### claude-code-live.parity.test.ts (6)
- Injected throttle wins, timeout raises, agent monitor metrics
- Cancel process, fork_n parallel assertion

### misc-runtime.parity.test.ts (5)
- Call throttle tests (test uses ClaudeCodeExecutor where Python uses throttle_from_config)
- Serialised gate, backward compat

### misc-machine-core.parity.test.ts (4)
- Peer propagation, profile discovery

### persistence-config.parity.test.ts (4)
- SQLite auto wiring edge cases, latest pointer

### flatagent-backends.parity.test.ts (4)
- Codex backend, distributed backend tests

### signals-integration.parity.test.ts (3)
- Socket trigger tests

### persistence-integration.parity.test.ts (2)
- Webhook hooks (on_error, on_checkpoint)

### misc-persistence-resume.parity.test.ts (1)
- Dispatcher integration edge case

### codex-auth-client.parity.test.ts (1)
- Token exchange edge case

## Notes
- Many remaining failures are test porting issues (JS uses `{{ }}` where Python uses bare paths)
- Tool loop integration tests require complex file I/O providers
- Some helper methods need `this` binding for standalone extraction
- The SDK split (flatagents/flatmachines packages) is not started yet

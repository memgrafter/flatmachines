# JS SDK Python Parity TODOs

## Status: 31 failing / 1834 passing / 51 skipped / 824 todo (2740 total)
## Started at: 347 failing → 31 failing (91% reduction)

## Summary of what was done

### New modules created
- `src/monitoring_providers.ts` — Provider-specific rate limit classes (Cerebras, Anthropic, OpenAI)
- `src/dispatch_signals.ts` — run_once/run_listen + CLI parser
- `src/providers/codex_login.ts` — OAuth login flow
- `src/adapters/claude_code_sessions.ts` — SessionHoldback pattern

### Major SDK changes
- Converted agent_response interfaces to constructable classes
- Python-compatible template rendering (True/False/None/list/dict via nunjucks patch)
- Bare path vs template resolution matching Python's _render_template behavior
- FlatAgent helper methods (_extract_cache_tokens, _calculate_cost, _extract_finish_reason, etc.)
- FlatMachine helper methods (_render_guardrail, _build_assistant_message, _extract_cost, etc.)
- Full tool-loop hooks (on_tool_calls, on_tool_result, get_tool_provider, steering, skip)
- Agent ref resolution at construction time
- Config hash/store support for resume
- Auto-wiring of SQLiteLeaseLock + SQLiteConfigStore + LocalFileLock
- Peer propagation (persistence, lock, configStore to child machines)
- Backward-compatible re-exports and runtime WorkPool/WorkBackend/WorkItem
- Tool loop chain preservation to context
- Tool loop checkpoints with tool_loop_state

### Remaining 31 failures

| Area | Count | Nature |
|------|-------|--------|
| tool-loop-machine | 6 | Chain scoping, test porting issues ({{ }} vs bare path), LoggingHooks |
| claude-code-live | 6 | Throttle injection, timeout, monitor metrics, cancel, fork_n |
| misc-runtime | 5 | Throttle config path mismatch, backward compat |
| flatagent-backends | 4 | Codex backend integration, distributed backends |
| misc-machine-core | 3 | Profile discovery |
| signals-integration | 3 | Socket trigger tests |
| tool-loop | 1 | Checkpoint metrics (cost tracking assertion) |
| persistence-integration | 1 | Webhook checkpoint event |
| misc-persistence-resume | 1 | Dispatcher edge case |
| codex-auth-client | 1 | Token exchange edge case |

## SDK split status
NOT started. The JS SDK remains monolithic in sdk/js/.

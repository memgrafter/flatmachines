# JS SDK Python Parity TODOs

## Status: 39 failing / 1824 passing / 51 skipped / 824 todo (2740 total)
## Started at: 347 failing → 39 failing (89% reduction)

## Summary of what was done

### New modules created
- `src/monitoring_providers.ts` — CerebrasRateLimits, AnthropicRateLimits, OpenAIRateLimits classes + extraction functions
- `src/dispatch_signals.ts` — run_once, run_listen, CLI parser (ports dispatch_signals.py)
- `src/providers/codex_login.ts` — OAuth login flow (parseAuthorizationInput, createAuthorizationFlow, etc.)
- `src/adapters/claude_code_sessions.ts` — SessionHoldback for cache-warm fork pattern

### Major changes
- Converted agent_response.ts interfaces to constructable classes (CostInfo, UsageInfo, RateLimitInfo, ErrorInfo, AgentResponse, AgentToolCall)
- Added Python-compatible template rendering (nunjucks suppressValue patch for True/False/None/list/dict)
- Fixed bare path vs template resolution to match Python's _render_template behavior
- Added FlatAgent helper methods (_extract_cache_tokens, _calculate_cost, _extract_finish_reason, _record_rate_limit_metrics)
- Added FlatMachine helper methods (_render_guardrail, _build_assistant_message, _extract_cost, _resolve_tool_definitions)
- Added tool-loop hooks (on_tool_calls, on_tool_result, get_tool_provider, steering messages, skip tools)
- Added agent ref resolution at construction time
- Added config hash/store support for resume
- Added auto-wiring of SQLiteLeaseLock + SQLiteConfigStore
- Added peer propagation (persistence, lock, configStore to child machines)
- Added backward-compatible re-exports and runtime WorkPool/WorkBackend/WorkItem

### Remaining 39 failures

#### tool-loop.parity.test.ts (8)
- File I/O integration tests requiring actual filesystem tool providers
- Chain preservation, denied tools, crash/resume mid-loop

#### tool-loop-machine.parity.test.ts (6)
- Chain scoping (continuation reuse)
- Test porting issues ({{ }} vs bare path)
- LoggingHooks class not implemented

#### claude-code-live.parity.test.ts (6)
- Injected throttle, timeout, monitor metrics, cancel, fork_n assertion

#### misc-runtime.parity.test.ts (5)
- Call throttle config tests (test uses wrong creation path)
- Serialised gate, backward compat edge cases

#### misc-machine-core.parity.test.ts (3)
- Profile discovery for FlatAgent and FlatMachine

#### flatagent-backends.parity.test.ts (4)
- Codex backend integration, distributed backends

#### signals-integration.parity.test.ts (3)
- Socket trigger tests

#### persistence-config.parity.test.ts (1)
- Local backend unchanged test

#### persistence-integration.parity.test.ts (1)
- Webhook checkpoint event

#### misc-persistence-resume.parity.test.ts (1)
- Dispatcher integration edge case

#### codex-auth-client.parity.test.ts (1)
- Token exchange edge case

## SDK split status
The JS SDK has NOT yet been split into flatagents + flatmachines packages.
The current monolithic structure in sdk/js/ contains both agent and machine code.

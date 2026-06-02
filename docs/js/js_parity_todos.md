# JS SDK Python Parity Status

## Final: 28 failing / 1837 passing / 51 skipped / 824 todo (2740 total)
## Started at: 347 failing → 28 failing (92% reduction)

## What was done

### New modules
- `monitoring_providers.ts` — CerebrasRateLimits, AnthropicRateLimits, OpenAIRateLimits
- `dispatch_signals.ts` — run_once/run_listen + CLI
- `providers/codex_login.ts` — OAuth login
- `adapters/claude_code_sessions.ts` — SessionHoldback

### Key SDK changes
- agent_response interfaces → constructable classes
- Python-compatible template rendering (nunjucks suppressValue patch)
- Bare path vs template resolution matching Python
- FlatAgent/FlatMachine helper methods
- Full tool-loop hooks + chain preservation
- Agent ref resolution, config hash/store
- Auto-wiring persistence backends
- Profile discovery separated: FlatAgent auto-discovers, FlatMachine does not

## Remaining 28 failures

| Area | Count | Nature |
|------|-------|--------|
| tool-loop-machine | 6 | Chain scoping, test porting ({{ }} vs bare path), LoggingHooks |
| claude-code-live | 6 | Throttle injection, timeout, monitor metrics, cancel, fork_n |
| misc-runtime | 5 | Throttle config mismatch, backward compat |
| flatagent-backends | 4 | Codex backend, distributed backend |
| signals-integration | 3 | Socket trigger |
| tool-loop | 1 | Checkpoint metrics |
| persistence-integration | 1 | Webhook checkpoint event |
| misc-persistence-resume | 1 | Dispatcher edge case |
| codex-auth-client | 1 | Token exchange |

## Passing test suites (0 failures)
- metrics.parity.test.ts (216/216)
- context-machine.parity.test.ts (14/14)
- dispatcher-wait.parity.test.ts (44/44)
- misc-machine-core.parity.test.ts (68/68)
- persistence-config.parity.test.ts (58/58)
- misc-unit.parity.test.ts (all)
- signals-core.parity.test.ts (all)

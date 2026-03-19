# Status Report: Claude Code Adapter

### ✅ COMPLETE

#### 1. Core Adapter Implementation

- claude_code.py — Full ClaudeCodeAdapter + ClaudeCodeExecutor with:
    - Config → CLI arg builder (model, effort, permission_mode, system_prompt, append_system_prompt, tools, max_budget_usd, claude_bin, working_dir, dangerously_skip_permissions, add_dirs)
    - NDJSON stream parsing via _StreamCollector (system, assistant, user, result, rate_limit events)
    - Tool use tracking and matching (tool_use blocks → tool_result blocks)
    - AgentResult mapping from CLI result events (usage, cost, finish_reason, session_id)
    - Subprocess lifecycle: spawn, timeout (SIGTERM → grace → SIGKILL), stderr capture, cancellation
    - AgentMonitor integration for metrics (tokens, cost, errors)
    - execute_with_tools() explicitly raises NotImplementedError (correct design — CC owns tools)
    - Error handling: process failures, missing result events, malformed NDJSON lines
    - All config keys documented in module docstring

#### 2. Adapter Registration

- Registered in adapters/__init__.py alongside flatagent, smolagents, pi-agent — type_name = "claude-code" works in YAML configs.

#### 3. Programmatic Completion Detection ("Continue Until Done") — Checklist Item #6

- Fully implemented in execute():
    - Configurable exit sentinel (<<AGENT_EXIT>> default)
    - Configurable continuation prompt
    - Configurable max_continuations safety cap (default 100)
    - Smart single-turn detection (if stop + ≤1 turn → done without sentinel)
    - Error stops loop immediately
    - Aggregated metrics across continuation attempts (tokens, cost, api_calls)

#### 4. Session Management (Core) — Checklist Item #1 (partial)

- New session: --session-id <uuid>
- Resume session: --resume <id>
- Session ID flows through output_to_context → input.resume_session
- Fork session: --fork-session flag support in _build_args()
- ✅ Cache token metrics validated live — cache_read, cache_write, input, output all populated correctly
- ✅ Session resume validated live — context recall works, cache_read > 0 on resume
- ✅ Cache is prefix-based (not session-aware) — confirmed via shared cache hits across independent sessions on same model
- ✅ Cache TTL is 1 hour (ephemeral_1h tier) — ephemeral_5m shows 0 in all measurements

#### 5. Session Holdback Pattern — Checklist Item #1 (partial)

- claude_code_sessions.py — Full SessionHoldback implementation:
    - seed() — creates holdback session
    - adopt() — adopt existing session (zero API calls)
    - fork() — single fork with --fork-session
    - fork_n() — parallel fan-out with configurable max_concurrent semaphore
    - warm() — resets API cache TTL without advancing holdback
    - Cost accumulation, stats tracking, exception handling in fork_n()
- ✅ Validated live — seed + fork with context recall and cache_read > 0

#### 6. Tool Restrictions (Exact Mode) — Checklist Item #3

- --tools (exact whitelist) is supported and used by default (not --allowed-tools)
- ✅ --tools verified live — system event reports exactly the listed tools
- --system-prompt (full replace) and --append-system-prompt supported, mutually exclusive
- System prompt wins over append when both configured
- ✅ --append-system-prompt verified live — influences response without breaking tools
- ✅ --system-prompt verified live — works with tool use, does not reduce internal overhead (~15K internal always present)
- ✅ Token cost per tool measured: ~1-1.5K tokens per tool definition

#### 7. No --json-schema by Default — Checklist Item #4

- Codified as a design rule in the module docstring
- No --json-schema arg generation anywhere in the adapter

#### 8. Unit Tests — 114 tests, all passing

- test_claude_code_adapter.py — arg builder (incl. dangerously_skip_permissions, add_dirs, throttle defaults, mcp_config), stream collector, result mapping, execute flow, continuation loop, timeout, errors, monitor metrics, registration, ordered tool tracking, structured output extraction, rate limit surfacing, cancellation
- test_claude_code_sessions.py — seed, adopt, fork, fork_n, warm, stats, build_args fork_session
- test_call_throttle.py — disabled/enabled, first call no-wait, second call waits, jitter randomness, jitter range, reset, negative clamping, serialised gate stagger, throttle_from_config
- 7 NDJSON fixture files for replay-based testing (incl. structured_output, rate_limit_session)

#### 9. Live Integration Tests — 14 tests, all passing (--live flag)

- test_claude_code_live.py — gated behind `pytest --live`:
    1. Simple task — AgentResult with content, usage, cost, session_id
    2. Tool use — Read file, verify tool_use + tool_result in stream events
    3. Session resume — two-turn context recall, cache_read > 0
    4. Concurrent sessions — two parallel, both succeed, different IDs
    5. Error recovery — resume nonexistent session → error AgentResult
    6. Permission bypass — bypassPermissions + Bash modifies file with no TTY
    7. Tool restrictions — --tools Read, system event confirms restriction
    8. Continuation loop — sentinel detection, api_calls count
    9. Stream event types — system/assistant/result all present and structured
    10. Session holdback — seed + fork with context recall and cache metrics
    11. dangerously-skip-permissions — bypassPermissions as standard mode documented
    12. Append system prompt — influences response without breaking tools
    13. Cache metrics — all cache fields populated, non-zero
    14. Minimal prompt + 4 tools — pi-style system prompt, exact tool restriction, token footprint measured

#### 10. Rate Limiting — CallThrottle (16 tests)

- call_throttle.py — Standalone async rate limiter:
    - asyncio.Lock serialised gate — concurrent callers stagger, subprocesses run concurrently
    - delay + uniform(0, 2*jitter) gap, millisecond granularity
    - Default on for Claude Code: delay=3s, jitter=±4s → [3, 11]s between calls
    - Configurable via rate_limit_delay / rate_limit_jitter config keys
    - Disabled by setting both to 0, or injecting CallThrottle() in constructor
    - 16 unit tests

#### 11. Burn-in Test Harnesses — Checklist Item #7 (partial)

- burnin_claude_code_cache.py — 3-turn sequential session (new → resume → resume), validates cache growth
- burnin_holdback_pattern.py — seed → fork×3 parallel → warm → fork, with cache metrics

#### 12. Example/Reference Implementation

- sdk/examples/claude_code_adapter/ — example machine configs (machine.yml, machine_multi_state.yml), hooks, main runner

#### 13. Reference Documentation

- claude-code-cli-reference.md — comprehensive CLI reference (flags, output formats, session storage, tools, cache behavior, error behavior, concurrency)
- claude-code-cli-adapter-analysis.md — adapter design (interface contracts, execute flow, AgentResult mapping, hook translation, process lifecycle, test strategy, TOS compliance)
- CLAUDE_CACHE_BEHAVIOR.md — measured token breakdown of system prompt, tool defs, deferred loading, --system-prompt vs --append-system-prompt, methodology

#### 14. Checklist Item #2 — Fully Automated / Non-Interactive Mode ✅

- ✅ --permission-mode bypassPermissions works headless with no TTY — validated live
- ✅ Bash tool executes and modifies files without prompting — validated live
- ✅ --dangerously-skip-permissions support added to _build_args() (config key: dangerously_skip_permissions)
- ✅ bypassPermissions documented as the standard mode for orchestration

#### 15. Config → CLI Mappings

- ✅ --add-dir support implemented (config key: add_dirs)
- ✅ --dangerously-skip-permissions support implemented (config key: dangerously_skip_permissions)
- ✅ --mcp-config support implemented (config key: mcp_config)

#### 16. Cache Behavior Investigation ✅

- ✅ Token breakdown documented: ~4K internal base + ~6K CC user prompt + ~5K for 9 non-deferred tool defs = ~15K default
- ✅ 14 of 23 tools deferred (definitions loaded on demand, not in initial prompt)
- ✅ --system-prompt replaces user portion (~6K) but not internal overhead
- ✅ Each tool definition costs ~1-1.5K tokens
- ✅ Minimum config (--system-prompt + 4 tools) = ~5K tokens
- ✅ Interactive mode ~60K vs -p mode ~15K — difference is CLAUDE.md, project context, git state, memory, full tool defs
- ✅ Session JSONL does not store system prompt — assembled fresh each invocation
- ✅ CLAUDE_CODE_SIMPLE=1 env var documented (~5K with minimal 3-line prompt)

────────────────────────────────────────────────────────────────────────────────

### ✅ NEWLY COMPLETED (productionisation pass)

#### 17. Hook Event Firing — on_tool_calls / on_tool_result ✅

- ✅ _StreamCollector now builds ordered_tool_calls and ordered_tool_results lists during stream parsing
- ✅ _build_result populates AgentResult.tool_calls from ordered_tool_calls
- ✅ _build_result populates metadata.tool_results from ordered_tool_results
- ✅ FlatMachine._execute_state fires observational on_tool_calls/on_tool_result hooks in the non-tool-loop agent path when AgentResult.tool_calls is populated
- ✅ Hooks are informational — _abort_tool_loop and _skip_tools have no effect since Claude Code owns the tool loop (documented in code comment)
- ✅ Generic implementation: any adapter that populates tool_calls/tool_results gets hooks fired (not CC-specific)

#### 18. Structured Output Extraction (StructuredOutput tool_use) ✅

- ✅ _StreamCollector detects tool_use blocks with name=="StructuredOutput" and captures the input dict
- ✅ _build_result: when StructuredOutput detected, its fields become top-level output keys (e.g. output.score, output.summary) with session_id preserved and _raw_result for the text
- ✅ Without StructuredOutput, output falls back to {result: text, session_id: ...} (backward compatible)
- ✅ New fixture: structured_output.ndjson
- ✅ 3 unit tests covering detection, result mapping, and fallback

#### 19. Rate Limit Events → AgentResult.rate_limit ✅

- ✅ _StreamCollector collects rate_limit_info from rate_limit_event(s) into rate_limit_events list
- ✅ _build_rate_limit_from_events() maps CC rate limit info to normalised RateLimitState format (windows, limited, retry_after)
- ✅ _build_result sets AgentResult.rate_limit from collected events
- ✅ None when no rate limit events observed (backward compatible)
- ✅ New fixture: rate_limit_session.ndjson
- ✅ 4 unit tests covering collection, mapping, absence, and limited detection

#### 20. --mcp-config Support ✅

- ✅ _build_args() generates --mcp-config <path> from config key mcp_config
- ✅ Config key documented in module docstring
- ✅ 2 unit tests (present / absent)

#### 21. Subprocess Cancellation ✅

- ✅ ClaudeCodeExecutor._process tracks running subprocess
- ✅ cancel() method: SIGTERM → 5s grace → SIGKILL, returns True/False
- ✅ _process cleared after _invoke_once completes
- ✅ ProcessLookupError handled gracefully
- ✅ 4 unit tests (no process, running process, already dead, ref cleared)

────────────────────────────────────────────────────────────────────────────────

### ⏳ REMAINING — Investigation / Deferred

#### Checklist Item #1 — Session Management & Cache (remaining)

- ❌ Investigate cache breakpoints — exact definition of "block," whether 4 breakpoints are configurable/exposed
- ❌ Session forking read-only semantics — can N processes --resume from same session ID simultaneously? (not tested live)
- ❌ Holdback keep-alive timing — warm() exists but optimal interval relative to 1-hour TTL is unknown
- ❌ Session expiry/lifetime — how long do local session files persist? Is there garbage collection?

#### Checklist Item #3 — Tool Restrictions (remaining)

- ❌ Declarative tool/prompt config in FlatMachine schema — config keys exist but no schema validation or documentation as part of the spec

#### Checklist Item #5 — Future: Plugins, --agent

- ❌ --plugin-dir, --agent / --agents not investigated (--mcp-config now implemented)

#### Checklist Item #7 — Experimental Validation (remaining)

- ❌ Burn-in results not documented — scripts exist and work, but output not captured in docs
- ❌ Structured output validation — StructuredOutput tool_use interception not tested live (unit-tested only)

#### Other Remaining

- ❌ FlatMachine-initiated cancellation — cancel() method exists on executor, but FlatMachine has no orchestration-level cancel signal to trigger it. Requires FlatMachine API extension.

────────────────────────────────────────────────────────────────────────────────

### Summary

**Done:** Core adapter, 114 unit tests (78 adapter + 12 session + 16 throttle + 8 new), 14 live integration tests (all passing), rate limiting, permission mode validation, tool restriction validation, cache behavior analysis with full token breakdown, --add-dir / --dangerously-skip-permissions / --mcp-config support, hook event firing (on_tool_calls/on_tool_result), structured output extraction, rate limit surfacing, subprocess cancellation, documentation.

**Remaining (investigation / deferred):**
1. Cache breakpoints investigation
2. Session forking read-only semantics
3. Holdback keep-alive timing
4. Schema validation for tool/prompt config in FlatMachine spec
5. FlatMachine-initiated cancellation (executor cancel() exists, needs FM API)
6. Burn-in test results not captured in docs
7. Live validation of StructuredOutput interception

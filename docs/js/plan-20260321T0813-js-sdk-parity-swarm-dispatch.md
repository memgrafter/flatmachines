# Plan: JS SDK Parity Completion via Swarm Workers

**Status:** draft
**Baseline:** 28 failing / 1837 passing (92% from 347 initial failures)
**Goal:** Drive remaining 28 failures to 0 using parallel swarm workers

## Analysis

The remaining 28 failures fall into 7 independent work clusters with no file overlap.
Each cluster maps to one swarm worker. Dependencies between clusters are minimal —
only the tool-loop-machine worker depends on the misc-runtime throttle fix (for the
`{{ }}` vs bare-path coercion issue shared by both).

### Why swarm is appropriate now
- Remaining tasks are well-characterized (exact error messages known)
- File ownership is clean — each cluster touches distinct source files
- Most tasks are 50-200 line changes
- No inter-task ordering constraints within stages (stage 1 is all parallel)

## Execution DAG

- **Stage 1** (parallel, 7 workers, no file overlap):
  - Worker 1: fix-call-throttle-parity
  - Worker 2: fix-claude-code-adapter-parity
  - Worker 3: fix-tool-loop-machine-remaining
  - Worker 4: fix-codex-backend-parity
  - Worker 5: fix-signals-integration
  - Worker 6: fix-persistence-webhook-checkpoint
  - Worker 7: fix-remaining-edge-cases

## Shared Baseline Context

- **Repo:** `~/code/flatagents/sdk/js/` — TypeScript SDK with vitest tests
- **Test command:** `cd ~/code/flatagents/sdk/js && npx vitest run`
- **Do NOT modify:** `sdk/python/` (reference implementation)
- **Test modification policy:** Only fix tests that are clearly wrong compared to `sdk/python/` tests (e.g., using `{{ }}` where Python uses bare paths). Check the corresponding Python test file before modifying any JS test.
- **Key reference files:**
  - `sdk/js/MACHINES.md` — spec overview
  - `sdk/js/js_parity_todos.md` — current parity status
  - `sdk/js/src/flatmachine.ts` — machine runtime (~1100 lines)
  - `sdk/js/src/adapters/claude_code_adapter.ts` — Claude CLI adapter
  - `sdk/js/src/agents.ts` — adapter registry
  - `sdk/js/src/hooks.ts` — CompositeHooks, WebhookHooks
  - `sdk/js/src/templating.ts` — nunjucks rendering with Python-compat patches
- **Python reference for parity:** `sdk/python/flatagents/` and `sdk/python/flatmachines/`
- **Template rendering rule:** bare paths (`context.foo`) preserve native types; `{{ }}` templates render to strings. Booleans render as `True`/`False`, null as `None`, lists/dicts as JSON. This matches Python Jinja2 behavior.
- **Done signal:** Emit `<<SWARM_TASK_DONE>>` when all assigned tests pass.

---

## Worker: fix-call-throttle-parity

**Objective:** Fix 5 failing call throttle tests in `misc-runtime.parity.test.ts`.

**Owned files:**
- `sdk/js/src/adapters/claude_code_adapter.ts` (CallThrottle class, throttle_from_config)
- `sdk/js/tests/parity/misc-runtime.parity.test.ts` (only if clearly wrong vs Python)

**Refs:**
- `sdk/python/flatmachines/flatmachines/adapters/call_throttle.py` (Python reference)
- `sdk/python/tests/unit/test_call_throttle.py` (Python test reference)

**Dependencies:** none

**Failing tests (5):**
1. `TestCallThrottle.test_second_call_waits` — throttle wait timing
2. `TestCallThrottle.test_jitter_adds_randomness` — jitter verification
3. `TestSerialisedGate.test_concurrent_calls_stagger` — concurrent serialization
4. `TestThrottleFromConfig.test_empty_config` — empty config → disabled
5. `TestThrottleFromConfig.test_delay_only` — delay without jitter

**Root cause:** The JS test `createThrottle()` helper constructs a `ClaudeCodeExecutor` and extracts `executor.throttle`. This applies executor defaults (delay=3, jitter=4). But the Python tests use `throttle_from_config({})` which creates a CallThrottle directly without defaults. The JS test should use `throttle_from_config` from `claude_code_adapter.ts` instead of routing through ClaudeCodeExecutor. Check the Python test at `sdk/python/tests/unit/test_call_throttle.py` to confirm, then fix the JS test's `createThrottle` helper to match Python's `throttle_from_config` path. Also verify the timing tests — `test_second_call_waits` expects the second call to wait ~50ms; ensure the throttle wait() returns elapsed seconds (not ms) and the first call sets lastCall correctly.

**Validation:** `npx vitest run tests/parity/misc-runtime.parity.test.ts`

```text
Fix 5 call throttle parity tests in misc-runtime.parity.test.ts.

The tests use a createThrottle() helper that incorrectly routes through ClaudeCodeExecutor (which applies default delay=3.0/jitter=4.0). Python tests use throttle_from_config({}) directly.

Steps:
1. Read sdk/python/tests/unit/test_call_throttle.py to understand the Python test structure.
2. Read the JS test's createThrottle helper in tests/parity/misc-runtime.parity.test.ts.
3. Fix createThrottle to use throttle_from_config from src/adapters/claude_code_adapter.ts instead of constructing a ClaudeCodeExecutor.
4. Verify CallThrottle.wait() returns seconds (not ms) and first call returns 0.
5. Run: npx vitest run tests/parity/misc-runtime.parity.test.ts

Only modify tests if they are clearly wrong compared to Python tests.
```

---

## Worker: fix-claude-code-adapter-parity

**Objective:** Fix 6 failing Claude Code adapter tests in `claude-code-live.parity.test.ts`.

**Owned files:**
- `sdk/js/src/adapters/claude_code_adapter.ts` (ClaudeCodeExecutor, ClaudeCodeAdapter)
- `sdk/js/src/adapters/claude_code_sessions.ts` (SessionHoldback.fork_n)
- `sdk/js/src/monitoring.ts` (AgentMonitor)

**Refs:**
- `sdk/python/flatmachines/flatmachines/adapters/claude_code.py`
- `sdk/python/flatmachines/flatmachines/adapters/claude_code_sessions.py`
- `sdk/python/tests/unit/test_claude_code_adapter.py`
- `sdk/python/tests/unit/test_claude_code_sessions.py`

**Dependencies:** none

**Failing tests (6):**
1. `TestThrottleDefaults.test_injected_throttle_wins` — executor should accept injected throttle via config
2. `TestExecute.test_timeout_raises` — timeout should reject promise, not resolve
3. `TestAgentMonitorMetrics.test_monitor_agent_id_uses_model` — monitor.agentId should include model name
4. `TestAgentMonitorMetrics.test_continuation_summary_log` — continuation tracking
5. `TestCancel.test_cancel_process_already_dead` — cancel on dead process should not throw
6. `TestForkN.test_fork_n_parallel` — fork_n instanceof check failing

**Root causes:**
- test_injected_throttle_wins: Executor config should support a `throttle` key that replaces the auto-created one.
- test_timeout_raises: The spawn timeout path resolves instead of rejecting. Need to throw/reject on timeout.
- test_monitor_agent_id_uses_model: ClaudeCodeExecutor should set a monitor agent_id like `claude-code/<model>`.
- test_cancel_process_already_dead: The cancel() method throws ProcessLookupError when process is already dead. Should catch and ignore.
- test_fork_n_parallel: `instanceof` check on ForkResult failing because it's an interface not a class. Make ForkResult a class or fix the check.

**Validation:** `npx vitest run tests/parity/claude-code-live.parity.test.ts`

```text
Fix 6 Claude Code adapter parity tests in claude-code-live.parity.test.ts.

Read the corresponding Python tests first:
- sdk/python/tests/unit/test_claude_code_adapter.py
- sdk/python/tests/unit/test_claude_code_sessions.py

Fixes needed:
1. test_injected_throttle_wins: Add support for config.throttle in ClaudeCodeExecutor constructor to override the auto-created CallThrottle.
2. test_timeout_raises: Ensure the executor rejects the promise when timeout is exceeded during spawn. Check how Python raises TimeoutError.
3. test_monitor_agent_id_uses_model: Add _monitor property to ClaudeCodeExecutor with agentId = `claude-code/${model}`.
4. test_continuation_summary_log: Track continuation count and log summary.
5. test_cancel_process_already_dead: Wrap process.kill() in try/catch to handle ESRCH.
6. test_fork_n_parallel: Make ForkResult a class (not just interface) in claude_code_sessions.ts so instanceof works.

Run: npx vitest run tests/parity/claude-code-live.parity.test.ts
```

---

## Worker: fix-tool-loop-machine-remaining

**Objective:** Fix 6 failing tool-loop-machine tests + 1 tool-loop test.

**Owned files:**
- `sdk/js/src/flatmachine.ts` (executeToolLoop method, chain management)
- `sdk/js/src/hooks.ts` (LoggingHooks class)
- `sdk/js/tests/parity/tool-loop-machine.parity.test.ts` (only if clearly wrong vs Python)
- `sdk/js/tests/parity/tool-loop.parity.test.ts` (only if clearly wrong vs Python)

**Refs:**
- `sdk/python/flatmachines/flatmachines/flatmachine.py` (_execute_tool_loop method)
- `sdk/python/tests/unit/test_tool_loop_machine.py`
- `sdk/python/tests/integration/tool_use/test_tool_loop_integration.py`

**Dependencies:** none (but shares thematic overlap with throttle worker)

**Failing tests (7):**
1. `TestBasicMachineToolLoop.test_output_to_context_mapping` — `{{ output._tool_calls_count }}` renders as string "1" not number 1
2. `TestToolLoopChainScoping.test_same_state_continuation_reuses_chain` — continuation should reuse existing chain, not recreate input
3. `TestToolLoopChainScoping.test_continuation_does_not_append_synthetic_user_prompt` — chain should have 3 messages (user + assistant + tool), not 2
4. `TestToolLoopCheckpoints.test_checkpoint_contains_tool_loop_state` — checkpoint tool_loop_state needs cost field
5. `TestHelperMethods.test_extract_cost_none` — JS test `makeAgentResult({ cost: null })` uses `??` which doesn't treat null as provided
6. `TestHookSubclasses.test_logging_hooks_tool_methods` — LoggingHooks class not implemented
7. `TestCheckpointToolLoopState.test_checkpoint_has_chain_and_metrics` (tool-loop.parity) — checkpoint metrics missing cost

**Root causes:**
- Tests 1 and 5 are JS test porting issues: they use `{{ }}` where Python uses bare paths, or `??` where `!== undefined` is needed. Check corresponding Python test and fix JS test if clearly wrong.
- Test 2/3: The tool loop resets chain on each execution. When a state loops back to itself, the chain from the previous iteration should be preserved. Store chain on context and restore on re-entry.
- Test 4/7: The tool_loop_state checkpoint needs a `cost` field alongside `chain`/`turns`/`tool_calls_count`.
- Test 6: Create a `LoggingHooks` class that implements `on_tool_calls` and `on_tool_result` with console.log.

**Validation:** `npx vitest run tests/parity/tool-loop-machine.parity.test.ts tests/parity/tool-loop.parity.test.ts`

```text
Fix 7 tool-loop parity tests across tool-loop-machine.parity.test.ts and tool-loop.parity.test.ts.

Read the Python tests first:
- sdk/python/tests/unit/test_tool_loop_machine.py
- sdk/python/tests/integration/tool_use/test_tool_loop_integration.py

Steps:
1. For test_output_to_context_mapping: check Python test — if it uses bare path (no {{ }}), fix the JS test config.
2. For test_extract_cost_none: check Python test — AgentResult() defaults cost to None. The JS test uses ?? which treats null as undefined. Fix the JS test's makeAgentResult to use `options.cost !== undefined ? options.cost : { total: 0.001 }`.
3. For chain scoping: when a tool-loop state transitions back to itself, preserve _tool_loop_chain from context.
4. For continuation: ensure chain includes user prompt, assistant message, and tool result.
5. Add `cost` field to checkpoint tool_loop_state (it's already being tracked as loopCost).
6. Create LoggingHooks class in src/hooks.ts with on_tool_calls and on_tool_result methods.

Run: npx vitest run tests/parity/tool-loop-machine.parity.test.ts tests/parity/tool-loop.parity.test.ts
```

---

## Worker: fix-codex-backend-parity

**Objective:** Fix 4 failing codex/distributed backend tests + 1 codex auth test.

**Owned files:**
- `sdk/js/src/flatagent.ts` (backend routing for codex)
- `sdk/js/src/providers/codex_client.ts`
- `sdk/js/src/providers/codex_login.ts`
- `sdk/js/src/actions.ts` (SubprocessInvoker)

**Refs:**
- `sdk/python/flatagents/flatagents/flatagent.py` (codex backend routing)
- `sdk/python/tests/unit/test_flatagent_codex_backend.py`
- `sdk/python/tests/integration/codex/test_codex_backend_integration.py`
- `sdk/python/tests/integration/distributed/test_distributed.py`

**Dependencies:** none

**Failing tests (5):**
1. `test_flatagent_codex_backend_end_to_end` — FlatAgent with backend: codex
2. `test_subprocess_support_imports` — SubprocessInvoker importable
3. `test_flatagent_accepts_backend_codex_from_model_config` — backend field routing
4. `test_call_llm_routes_to_codex_client_when_backend_is_codex` — call routing
5. `test_login_openai_codex_saves_auth_file_without_email_prompt` (codex-auth) — login flow

**Root causes:**
- FlatAgent doesn't check `model.backend === 'codex'` to route calls through CodexClient instead of VercelAI.
- SubprocessInvoker needs to be importable from the SDK index.
- codex_login exchangeAuthorizationCode mock doesn't match expected call pattern.

**Validation:** `npx vitest run tests/parity/flatagent-backends.parity.test.ts tests/parity/codex-auth-client.parity.test.ts`

```text
Fix 5 codex/distributed backend parity tests.

Read the Python tests first:
- sdk/python/tests/unit/test_flatagent_codex_backend.py
- sdk/python/tests/integration/codex/test_codex_backend_integration.py
- sdk/python/tests/integration/distributed/test_distributed.py

Steps:
1. Add backend routing to FlatAgent: when resolvedModelConfig.backend === 'codex', route calls through CodexClient instead of VercelAIBackend.
2. Ensure SubprocessInvoker is exported from src/index.ts and importable.
3. Check codex_login test — the exchangeAuthorizationCode mock may need adjustment for how fetch is called.
4. Run tests to verify.

Run: npx vitest run tests/parity/flatagent-backends.parity.test.ts tests/parity/codex-auth-client.parity.test.ts
```

---

## Worker: fix-signals-integration

**Objective:** Fix 3 failing signals integration tests.

**Owned files:**
- `sdk/js/src/signals.ts` (SocketTrigger)
- `sdk/js/src/dispatcher.ts`
- `sdk/js/src/dispatch_signals.ts`

**Refs:**
- `sdk/python/flatmachines/flatmachines/signals.py`
- `sdk/python/flatmachines/flatmachines/dispatch_signals.py`
- `sdk/python/tests/integration/signals/test_dispatch_integration.py`
- `sdk/python/tests/integration/signals/test_socket_trigger.py`

**Dependencies:** none

**Failing tests (3):**
1. `test_dispatch_multiple_channels` — dispatcher should resume same execution on multiple channels
2. `test_socket_trigger_creates_listener` — SocketTrigger should create a UDS listener (times out)
3. `test_socket_trigger_receives_notification` — SocketTrigger notification (times out)

**Root causes:**
- test_dispatch_multiple_channels: The dispatcher resumes the same execution ID for both channels but the test expects it twice in the result list.
- Socket trigger tests: The SocketTrigger uses `dgram` with `unix_dgram` which may not work. Need to implement a proper Unix domain socket listener using `net.createServer` with `{ path: socketPath }`.

**Validation:** `npx vitest run tests/parity/signals-integration.parity.test.ts`

```text
Fix 3 signals integration parity tests.

Read Python tests first:
- sdk/python/tests/integration/signals/test_dispatch_integration.py
- sdk/python/tests/integration/signals/test_socket_trigger.py

Steps:
1. For test_dispatch_multiple_channels: check if the dispatcher correctly handles the same execution waiting on multiple channels. Read the Python dispatch integration test.
2. For socket trigger: implement SocketTrigger using Node.js net.createServer with a Unix domain socket path. The trigger should:
   - Create a UDS listener on construction
   - Accept connections and read channel names
   - Have a close() method
   - notify() should connect and send channel name
3. Ensure proper cleanup (unlink socket file, close server).

Run: npx vitest run tests/parity/signals-integration.parity.test.ts
```

---

## Worker: fix-persistence-webhook-checkpoint

**Objective:** Fix 1 failing webhook checkpoint event test + 1 dispatcher edge case.

**Owned files:**
- `sdk/js/src/hooks.ts` (WebhookHooks)
- `sdk/js/src/flatmachine.ts` (checkpoint hook integration)
- `sdk/js/src/dispatcher.ts`

**Refs:**
- `sdk/python/tests/integration/persistence/test_webhooks.py`
- `sdk/python/tests/unit/test_resume.py`

**Dependencies:** none

**Failing tests (2):**
1. `test_webhooks.py::test_on_checkpoint_fires` — webhook should fire 'checkpoint' event
2. `test_resume.py::TestDispatcherIntegration.test_legacy_resume_fn_still_works` — resume_fn callback

**Root causes:**
- test_on_checkpoint_fires: The FlatMachine checkpoint method needs to call a hook when checkpointing. Add an `onCheckpoint` hook to MachineHooks and fire it from the checkpoint method. WebhookHooks should send a 'checkpoint' event.
- test_legacy_resume_fn: The run_once function needs to pass resume_fn correctly to the dispatcher when called with positional args.

**Validation:** `npx vitest run tests/parity/persistence-integration.parity.test.ts tests/parity/misc-persistence-resume.parity.test.ts`

```text
Fix 2 persistence/webhook parity tests.

Steps:
1. For test_on_checkpoint_fires:
   - Add onCheckpoint?(state, context, snapshot) to MachineHooks interface in types.ts
   - Call this.hooks?.onCheckpoint() from the FlatMachine checkpoint method after saving
   - Add onCheckpoint to WebhookHooks that sends a 'checkpoint' event
   - Add onCheckpoint to CompositeHooks chaining

2. For test_legacy_resume_fn_still_works:
   - Read the Python test to understand expected behavior
   - Check run_once in dispatch_signals.ts — ensure resumeFn is correctly passed when using positional args

Run: npx vitest run tests/parity/persistence-integration.parity.test.ts tests/parity/misc-persistence-resume.parity.test.ts
```

---

## Scheduling

**Mode:** `parallel` (all 7 workers in Stage 1, no dependencies between them)
**Max parallel:** 7
**Budget per worker:** $2.00
**Expected duration:** 10-20 minutes per worker

## Risk assessment

| Risk | Mitigation |
|------|-----------|
| File conflict between workers | Owned files lists are disjoint; changeset protection prevents overlap |
| Test modification disagreements | Each worker checks Python test before modifying JS test |
| Chain dependency on throttle fix | tool-loop-machine worker handles its own `{{ }}` vs bare path fix independently |
| Socket trigger platform issues | Worker can skip/mark as platform-specific if UDS not available |

## Acceptance criteria

All 28 failing tests pass:
```bash
cd ~/code/flatagents/sdk/js && npx vitest run 2>&1 | grep "Tests "
# Expected: Tests  0 failed | 1865 passed | 51 skipped | 824 todo (2740)
```

No regressions in currently passing tests (1837 must remain passing).

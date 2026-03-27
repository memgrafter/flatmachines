# Plan: JS SDK Parity with Python

**Status:** Draft  
**Created:** 2026-03-19  
**Scope:** `sdk/js/`  
**Goal:** Bring the JavaScript SDK to feature parity with the Python SDK (`sdk/python/flatagents` + `sdk/python/flatmachines`).

---

## Executive Summary

The JS SDK has the core primitives (FlatAgent, FlatMachine, profiles, expression engine, hooks, persistence, execution types, MCP) but is missing ~60% of the Python SDK's surface area. The gaps fall into 7 tiers, ordered by dependency and user impact.

---

## Current State Comparison

### What JS SDK Already Has ✅

| Feature | JS Module | Python Equivalent |
|---------|-----------|-------------------|
| FlatAgent (single LLM call) | `flatagent.ts` | `flatagent.py` |
| FlatMachine (state machine) | `flatmachine.ts` | `flatmachine.py` |
| Profile resolution | `profiles.ts` | `profiles.py` |
| Simple expression engine | `expression.ts` | `expressions/simple.py` |
| Execution strategies (default/retry/parallel/MDAP) | `execution.ts` | `execution.py` |
| Hooks (Webhook, Composite, Registry) | `hooks.ts` | `hooks.py` |
| Persistence (Memory, LocalFile) | `persistence.ts` | `persistence.py` (partial) |
| Locking (NoOp, LocalFile) | `locking.ts` | `locking.py` (partial) |
| Result backend (in-memory) | `results.ts` | `backends.py` (partial) |
| MCP tool provider | `mcp.ts` | `baseagent.py` MCPToolProvider |
| LLM backend (Vercel AI SDK) | `llm/vercel.ts` | N/A (uses litellm/aisuite) |
| Mock LLM backend | `llm/mock.ts` | N/A |
| Template rendering (Nunjucks) | `templating.ts` | Jinja2 |

### What JS SDK Is Missing ❌

| # | Feature | Python Module(s) | Priority | Complexity |
|---|---------|-------------------|----------|------------|
| **Tier 1 — Core Agent Gaps** | | | | |
| 1 | Structured AgentResponse type (usage, cost, rate_limit, finish_reason, error) | `baseagent.py` (AgentResponse, UsageInfo, CostInfo, etc.) | P0 | M |
| 2 | Agent response extraction (free, structured, tools, regex extractors) | `baseagent.py` (Extractor protocol + 5 impls) | P1 | M |
| 3 | Backend auto-detection & codex backend | `flatagent.py`, `providers/*` | P1 | L |
| 4 | Tool loop (multi-turn tool calling) | `tool_loop.py`, `tools.py` | P0 | L |
| 5 | Monitoring / observability (logger, metrics, AgentMonitor) | `monitoring.py` (both packages) | P2 | M |
| 6 | Config validation (JSON Schema) | `validation.py` (both packages) | P2 | S |
| **Tier 2 — Machine Orchestration Gaps** | | | | |
| 7 | Agent adapter registry (pluggable agent types) | `agents.py`, `adapters/*` | P0 | L |
| 8 | Built-in adapters: FlatAgent, SmolagentsAdapter, PiAgentBridge, ClaudeCode | `adapters/flatagent.py`, `claude_code.py`, etc. | P1 | XL |
| 9 | CEL expression engine | `expressions/cel.py` | P2 | M |
| 10 | Tool loop in machine states (`tool_loop: true`) | `flatmachine.py` `_execute_tool_loop` | P0 | L |
| 11 | `wait_for` / signal states | `flatmachine.py` WaitingForSignal | P1 | L |
| 12 | `action` states (hook-driven) | `flatmachine.py` + `actions.py` | P1 | M |
| 13 | Machine invoker abstraction (InlineInvoker, SubprocessInvoker, QueueInvoker) | `actions.py` | P1 | M |
| 14 | `context.machine` metadata injection | `flatmachine.py` `_inject_machine_metadata` | P2 | S |
| 15 | Jinja2 finalize/fromjson filter equivalents | `flatmachine.py` `_json_finalize` | P2 | S |
| **Tier 3 — Persistence & Storage** | | | | |
| 16 | SQLite persistence backend | `persistence.py` SQLiteCheckpointBackend | P0 | L |
| 17 | SQLite lease lock | `locking.py` SQLiteLeaseLock | P1 | M |
| 18 | Content-addressed ConfigStore (Memory, LocalFile, SQLite) | `persistence.py` ConfigStore + impls | P1 | M |
| 19 | `config_hash` in snapshots for cross-SDK resume | `persistence.py` `config_hash()` | P1 | S |
| 20 | `clone_snapshot` utility | `persistence.py` | P2 | S |
| 21 | `tool_loop_state` and `waiting_channel` in MachineSnapshot | `persistence.py` MachineSnapshot | P1 | S |
| **Tier 4 — Signals & Triggers** | | | | |
| 22 | Signal backend (Memory, SQLite) | `signals.py` | P1 | L |
| 23 | Trigger backends (NoOp, File, Socket) | `signals.py` | P2 | M |
| 24 | Signal dispatcher | `dispatcher.py` | P2 | M |
| 25 | `send_and_notify` helper | `signals_helpers.py` | P2 | S |
| **Tier 5 — Resume & Recovery** | | | | |
| 26 | MachineResumer ABC + ConfigStoreResumer + ConfigFileResumer | `resume.py` | P1 | M |
| 27 | Resume from snapshot with signal data | `flatmachine.py` execute() resume path | P1 | M |
| **Tier 6 — Distributed Workers** | | | | |
| 28 | RegistrationBackend (Memory, SQLite) | `distributed.py` | P2 | L |
| 29 | WorkBackend / WorkPool (Memory, SQLite) | `work.py` | P2 | L |
| 30 | DistributedWorkerHooks | `distributed_hooks.py` | P2 | L |
| **Tier 7 — Cloud Backends** | | | | |
| 31 | GCP Firestore backend | `gcp/firestore.py` | P3 | M |
| 32 | DynamoDB backends (would be new for JS) | N/A in Python yet | P3 | L |

**Size key:** S = <100 LOC, M = 100–400 LOC, L = 400–1000 LOC, XL = 1000+ LOC

---

## Implementation Plan

### Phase 1: Agent Foundation (P0 — ~2 weeks)

**Goal:** Make FlatAgent produce rich responses and support tool loops.

#### 1.1 Structured AgentResponse (#1)
- Add types: `AgentResponse`, `UsageInfo`, `CostInfo`, `RateLimitInfo`, `ErrorInfo`, `FinishReason`, `ToolCall`
- Update `FlatAgent.call()` to return `AgentResponse` instead of `{ content, output }`
- Extract usage/cost/rate-limit from Vercel AI SDK response
- **Breaking change** — bump minor version, document migration

#### 1.2 Tool Loop (#4)
- Port `tool_loop.py` → `src/tool_loop.ts`
- Port `tools.py` → `src/tools.ts` (ToolProvider protocol, SimpleToolProvider, ToolResult)
- Guardrails: max_turns, max_tool_calls, tool_timeout, total_timeout, max_cost
- StopReason enum
- Tests: mock LLM with tool calls, guardrail enforcement

#### 1.3 Response Extractors (#2)
- Port extractor protocol + FreeExtractor, StructuredExtractor, ToolsExtractor, RegexExtractor, FreeThinkingExtractor
- Wire into FlatAgent as configurable extraction mode

### Phase 2: Machine Agent System (P0 — ~2 weeks)

**Goal:** Pluggable agent adapters, tool loop states, SQLite persistence.

#### 2.1 Agent Adapter Registry (#7)
- Port `agents.py` → `src/agents.ts` (AgentExecutor, AgentResult, AgentRef, AgentAdapter, AgentAdapterRegistry, AgentAdapterContext)
- `normalize_agent_ref()`, `coerce_agent_result()`
- Rate-limit helpers: `build_rate_limit_windows`, `build_rate_limit_state`

#### 2.2 FlatAgent Adapter (#8 partial)
- Port `adapters/flatagent.py` → `src/adapters/flatagent.ts`
- Integrates existing FlatAgent class with new AgentExecutor interface
- Supports `execute_with_tools` for machine-driven tool loops

#### 2.3 Tool Loop in Machine States (#10)
- Port `_execute_tool_loop()` into `flatmachine.ts`
- Wire `tool_loop: true` state field
- Checkpoint integration with `tool_loop_state`
- Hook calls: `on_tool_calls`, `on_tool_result`

#### 2.4 SQLite Persistence Backend (#16)
- `src/persistence_sqlite.ts` using `better-sqlite3`
- SQLiteCheckpointBackend: save/load/list/delete with WAL mode
- Add `tool_loop_state` and `waiting_channel` to MachineSnapshot type (#21)

### Phase 3: Signals, Wait-For & Resume (P1 — ~2 weeks)

**Goal:** Pause/resume machines via signals, durable cross-process resume.

#### 3.1 Wait-For States (#11)
- Port `WaitingForSignal` exception pattern
- Update `executeInternal()` to handle `wait_for` state field
- Checkpoint with `waiting_channel`

#### 3.2 Signal Backends (#22)
- `src/signals.ts`: Signal type, SignalBackend protocol
- MemorySignalBackend (testing)
- SQLiteSignalBackend (durable local)

#### 3.3 Trigger Backends (#23)
- NoOpTrigger, FileTrigger (launchd/systemd), SocketTrigger (UDS)

#### 3.4 Signal Dispatcher (#24)
- `src/dispatcher.ts`: dispatch_all(), poll mode, UDS listener

#### 3.5 Machine Resumer (#26)
- ABC + ConfigStoreResumer + ConfigFileResumer
- Wire into FlatMachine.resume() and dispatcher

#### 3.6 ConfigStore (#18, #19)
- MemoryConfigStore, LocalFileConfigStore, SQLiteConfigStore
- `config_hash()` for content-addressed storage
- Auto-wire from SQLite persistence

#### 3.7 Action States & Invokers (#12, #13)
- Port `Action`, `HookAction`, `MachineInvoker`, `InlineInvoker`, `SubprocessInvoker`, `QueueInvoker`
- Update machine to call `action` states through hook dispatch

#### 3.8 SQLite Lease Lock (#17)
- `SQLiteLeaseLock` with owner_id, phase, TTL, heartbeat

### Phase 4: Polish & Advanced Features (P2 — ~2 weeks)

**Goal:** Monitoring, validation, additional adapters, expression engines.

#### 4.1 Monitoring (#5)
- `src/monitoring.ts`: structured logger, JSON formatter, AgentMonitor context manager pattern
- Optional OpenTelemetry metrics (via `@opentelemetry/api`)

#### 4.2 Config Validation (#6)
- `src/validation.ts`: validate configs against bundled JSON schemas
- Validation warnings (non-blocking)

#### 4.3 Context Machine Metadata (#14)
- `context.machine` injection: execution_id, machine_name, step, etc.

#### 4.4 Template Enhancements (#15)
- Nunjucks `fromjson` filter
- JSON auto-serialization for lists/dicts in template output

#### 4.5 CEL Expression Engine (#9)
- Optional `cel-js` dependency
- `expression_engine: "cel"` support

#### 4.6 Clone Snapshot (#20)
- Utility to clone + modify snapshots

#### 4.7 `send_and_notify` (#25)
- Helper to write signal + fire trigger in one call

### Phase 5: Distributed Workers (P2–P3 — ~2 weeks)

**Goal:** Port the distributed worker pattern for JS environments.

#### 5.1 Registration Backend (#28)
- WorkerRegistration, WorkerRecord, WorkerFilter
- MemoryRegistrationBackend, SQLiteRegistrationBackend

#### 5.2 Work Backend (#29)
- WorkItem, WorkPool, WorkBackend
- MemoryWorkBackend, SQLiteWorkBackend

#### 5.3 DistributedWorkerHooks (#30)
- Port all standard actions (get_pool_state, claim_job, complete_job, spawn_workers, etc.)

### Phase 6: Additional Adapters (P1–P3 — ongoing)

#### 6.1 Claude Code Adapter (#8)
- Port subprocess-based Claude Code CLI adapter
- CallThrottle for rate limiting
- Session management (claude_code_sessions.py equivalent)

#### 6.2 Smolagents / Pi-Agent Adapters
- Port if/when there's JS demand

#### 6.3 Cloud Backends (#31, #32)
- Firestore backend (if demand)
- DynamoDB backends (if demand)

---

## Dependency Graph

```
Phase 1 (Agent Foundation)
  ├── 1.1 AgentResponse types
  ├── 1.2 Tool Loop  ← depends on 1.1
  └── 1.3 Extractors ← depends on 1.1

Phase 2 (Machine Agent System)
  ├── 2.1 Adapter Registry       ← depends on 1.1
  ├── 2.2 FlatAgent Adapter      ← depends on 2.1 + 1.1
  ├── 2.3 Tool Loop in Machine   ← depends on 1.2 + 2.1 + 2.2
  └── 2.4 SQLite Persistence     ← independent

Phase 3 (Signals & Resume)
  ├── 3.1 Wait-For States        ← depends on 2.4
  ├── 3.2 Signal Backends        ← depends on 2.4
  ├── 3.3 Trigger Backends       ← depends on 3.2
  ├── 3.4 Dispatcher             ← depends on 3.2 + 3.5
  ├── 3.5 Resumer                ← depends on 3.6
  ├── 3.6 ConfigStore            ← depends on 2.4
  ├── 3.7 Actions & Invokers     ← independent
  └── 3.8 SQLite Lease Lock      ← depends on 2.4

Phase 4 (Polish) — all independent
Phase 5 (Distributed) — depends on 2.4 (SQLite)
Phase 6 (Adapters) — depends on 2.1
```

---

## New Dependencies

| Package | Purpose | Phase |
|---------|---------|-------|
| `better-sqlite3` | SQLite persistence, signals, locks, work pools | 2 |
| `@opentelemetry/api` | Optional metrics/tracing | 4 |
| `cel-js` or similar | Optional CEL expression engine | 4 |

---

## Breaking Changes

| Change | Phase | Migration |
|--------|-------|-----------|
| `FlatAgent.call()` returns `AgentResponse` instead of `{ content, output }` | 1 | Access `.content` and `.output` on returned object; `.output` retains parsed output |
| `MachineSnapshot` type gains new fields | 2 | Additive — existing snapshots still load |
| New `MachineOptions` fields (signalBackend, triggerBackend, agentRegistry, etc.) | 3 | All optional — no breakage |

---

## Testing Strategy

Each phase includes corresponding tests:
- **Unit tests** for each new module (vitest)
- **Integration tests** for cross-module workflows (machine + persistence + signals)
- **Compliance tests** cross-validate JS behavior against Python test fixtures
- **Mock LLM** tests for agent/tool-loop without real API calls

---

## Success Criteria

1. All 32 feature items implemented and tested
2. JS SDK can execute the same YAML configs as Python SDK (excluding cloud-specific backends)
3. Checkpoints are cross-SDK compatible (JS can resume Python checkpoints and vice versa)
4. All existing JS tests continue to pass
5. `sdk/examples/` configs work with either SDK

---

## Estimated Timeline

| Phase | Duration | Cumulative |
|-------|----------|------------|
| Phase 1: Agent Foundation | 2 weeks | 2 weeks |
| Phase 2: Machine Agent System | 2 weeks | 4 weeks |
| Phase 3: Signals & Resume | 2 weeks | 6 weeks |
| Phase 4: Polish & Advanced | 2 weeks | 8 weeks |
| Phase 5: Distributed Workers | 2 weeks | 10 weeks |
| Phase 6: Additional Adapters | Ongoing | — |

**Total to functional parity (Phases 1–4): ~8 weeks**

# Plan: Codex CLI Adapter for FlatMachines

> **Status:** Draft
> **Date:** 2026-03-21
> **Branch:** `js-parity` (Python SDK only, no JS changes)
> **Prereq:** [reference-20260321T0003-codex-cli-comprehensive-reference.md](./reference-20260321T0003-codex-cli-comprehensive-reference.md)
> **Model target:** `gpt-5.3-codex` (reasoning effort: `high`)

---

## Claude Code vs Codex CLI: Key Similarities and Differences

### Architecture Comparison

Both adapters drive an external CLI as a subprocess. Neither uses the
provider's HTTP API directly -- the CLI owns authentication, tool execution,
context management, and the agentic loop. The adapter's job is to:

1. Start/resume/fork sessions
2. Stream events and map them to `AgentResult`
3. Expose session state for orchestration

| Dimension | Claude Code (`claude -p`) | Codex CLI (`codex exec --json`) |
|-----------|--------------------------|--------------------------------|
| **Subprocess model** | One process per call | One process per call (exec) OR long-lived app-server |
| **Fork mechanism** | `--fork-session` flag on exec | `thread/fork` via app-server JSON-RPC |
| **Event format** | Complex nested NDJSON (system/assistant/user/result) | Flat JSONL (6 event types) |
| **Session storage** | `~/.claude/projects/` (per-project dirs) | `~/.codex/sessions/` + `state_5.sqlite` |
| **Result extraction** | Parse `result` event, map `stop_reason` | Parse last `agent_message` from `item.completed` |
| **Tool tracking** | Adapter tracks `tool_use` → `tool_result` across events | Opaque -- codex handles tools internally, adapter sees `command_execution` items |
| **Structured output** | Not native (`StructuredOutput` tool_use detection) | Native `--output-schema` with Responses API |
| **Cache management** | Explicit: 1-hour TTL, warm() cycle needed | Implicit: Responses API caches automatically |
| **Continuation loop** | Adapter runs multi-call loop with exit sentinel | Not needed -- codex runs to completion |
| **Cost tracking** | `total_cost_usd` in result event | Not available -- token counts only |
| **Rate limit info** | `rate_limit_event` with per-resource windows | `thread/tokenUsage/updated` notification; rate limits via `account/rateLimits/updated` |

### What Gets Simpler

1. **No continuation loop.** Claude Code's adapter has a ~100 LOC continuation
   loop with exit sentinel detection, max_continuations, and prompt injection.
   Codex runs its full agentic loop in a single invocation -- the adapter just
   waits for `turn/completed`.

2. **No tool tracking.** Claude Code's `_StreamCollector` (150 LOC) indexes
   `tool_use` blocks by ID, matches them to `tool_result` blocks, detects
   `StructuredOutput`, and maintains ordered call/result lists. Codex handles
   tools internally -- the adapter only sees completed `command_execution` and
   `fileChange` items.

3. **No cache warm cycle.** `SessionHoldback.warm()` exists solely for Claude's
   1-hour cache TTL. Codex's Responses API cache is automatic -- no warm step
   needed. The method can exist as a no-op or lightweight health check.

4. **Simpler event parsing.** 6 flat event types vs Claude's nested events with
   content blocks, message roles, and type discrimination.

### What Gets Different

1. **Dual transport.** Simple calls use `codex exec --json` (subprocess per
   call). Fork-with-cache uses `codex app-server --listen stdio://` (long-lived
   JSON-RPC). The adapter needs both code paths. Claude Code uses only
   subprocess.

2. **Model pinning.** `config.toml` model migrations silently upgrade forks.
   Must always pass `model` explicitly on `thread/fork` and `thread/start`.
   Claude Code doesn't have this problem.

3. **Token usage arrives separately.** In exec mode, `turn.completed` includes
   usage inline. In app-server mode, usage comes via a separate
   `thread/tokenUsage/updated` notification. The adapter must handle both.

4. **No cost field.** Claude Code reports `total_cost_usd`. Codex does not.
   The adapter reports token counts and lets the caller compute cost.

### What Stays the Same

1. **Adapter interface.** Both implement `AgentExecutor.execute()` returning
   `AgentResult`. Neither implements `execute_with_tools()`.

2. **Session holdback pattern.** `seed() → fork() / fork_n()` with the same
   API shape. Only the transport differs.

3. **Cancellation.** Both use SIGTERM → grace → SIGKILL on the subprocess.

4. **Rate throttling.** Reuses `CallThrottle` from `call_throttle.py`.

5. **Config merging.** Per-agent config merged over global
   `settings.agent_runners.codex_cli`.

---

## File Plan

```
sdk/python/flatmachines/flatmachines/adapters/
  codex_cli.py                  # NEW — executor + adapter + app-server transport
  codex_cli_sessions.py         # NEW — session holdback (seed/fork/fork_n)
  __init__.py                   # EDIT — register CodexCliAdapter

sdk/python/tests/unit/
  test_codex_cli_adapter.py     # NEW — unit tests for executor
  test_codex_cli_sessions.py    # NEW — unit tests for holdback
```

---

## Module 1: `codex_cli.py` (~450 LOC)

### Config Keys

```python
"""
Config keys (agent config or global settings.agent_runners.codex_cli):
  model               Model slug (default: gpt-5.3-codex)
  reasoning_effort    none | minimal | low | medium | high | xhigh (default: high)
  sandbox             read-only | workspace-write | danger-full-access (default: workspace-write)
  approval_policy     untrusted | on-request | never (default: never)
  output_schema       Path to JSON Schema file for structured output
  add_dirs            List of additional writable directories
  codex_bin           Path to codex binary (default: "codex")
  working_dir         Working directory for subprocess (supports Jinja2)
  timeout             Subprocess timeout in seconds (0 = no timeout)
  skip_git_repo_check bool — allow running outside git repos
  ephemeral           bool — don't persist session to disk
  search              bool — enable web search tool
  config_overrides    Dict of -c key=value pairs
  feature_enable      List of features to enable
  feature_disable     List of features to disable
  rate_limit_delay    Base seconds between CLI calls (default: 0)
  rate_limit_jitter   ±seconds jitter (default: 0)
  use_app_server      bool — use app-server transport (required for fork)
  session_source      App-server session source tag (default: "exec")
"""
```

### Component 1a: `_ExecStreamCollector` (~60 LOC)

Collects JSONL events from `codex exec --json`. Much simpler than Claude
Code's `_StreamCollector`.

```python
class _ExecStreamCollector:
    """Collects exec --json JSONL events."""

    def __init__(self) -> None:
        self.events: List[Dict[str, Any]] = []
        self.thread_id: Optional[str] = None
        self.items: List[Dict[str, Any]] = []
        self.usage: Optional[Dict[str, Any]] = None
        self.error: Optional[Dict[str, Any]] = None
        self.final_message: Optional[str] = None

    def ingest(self, event: Dict[str, Any]) -> None:
        etype = event.get("type")
        self.events.append(event)

        if etype == "thread.started":
            self.thread_id = event.get("thread_id")

        elif etype == "item.completed":
            item = event.get("item", {})
            self.items.append(item)
            if item.get("type") == "agent_message":
                self.final_message = item.get("text")

        elif etype == "item.started":
            pass  # Track for observability if needed

        elif etype == "turn.completed":
            self.usage = event.get("usage")

        elif etype == "turn.failed":
            self.error = event.get("error")

        elif etype == "error":
            self.error = {"message": event.get("message", "Unknown error")}
```

### Component 1b: `CodexAppServerTransport` (~180 LOC)

JSON-RPC multiplexer over stdin/stdout to `codex app-server`. Manages
subprocess lifecycle, request/response correlation, notification dispatch.

```python
class CodexAppServerTransport:
    """Manages codex app-server subprocess with JSON-RPC over stdio."""

    def __init__(self, codex_bin, cwd, model, session_source): ...

    async def start(self) -> None:
        """Spawn app-server, initialize protocol."""
        # subprocess_exec("codex", "app-server", "--listen", "stdio://", ...)
        # rpc("initialize", {"clientInfo": {"name": "flatmachines", "version": ...}})

    async def stop(self) -> None:
        """Terminate app-server subprocess."""

    async def _request(self, method, params) -> dict:
        """Send JSON-RPC request, await correlated response."""

    async def _read_loop(self) -> None:
        """Read stdout, dispatch responses and notifications."""

    def on_notification(self, cb) -> None: ...

    # Typed methods
    async def thread_start(self, cwd, model, sandbox, approval_policy, ephemeral) -> dict: ...
    async def thread_fork(self, thread_id, model, **overrides) -> dict: ...
    async def thread_resume(self, thread_id, **overrides) -> dict: ...
    async def thread_read(self, thread_id) -> dict: ...
    async def turn_start(self, thread_id, text, output_schema=None) -> dict: ...
    async def turn_interrupt(self, thread_id) -> dict: ...
```

### Component 1c: `CodexCliExecutor` (~180 LOC)

The main executor. Two code paths: exec subprocess and app-server.

```python
class CodexCliExecutor(AgentExecutor):

    def __init__(self, config, config_dir, settings, throttle=None):
        self._merged = {**settings, **config}
        self._throttle = throttle or throttle_from_config(self._merged)
        self._transport: Optional[CodexAppServerTransport] = None
        self._process: Optional[asyncio.subprocess.Process] = None

    async def execute(self, input_data, context=None) -> AgentResult:
        task = input_data.get("task") or input_data.get("prompt", "")
        resume_session = input_data.get("resume_session")

        if self._merged.get("use_app_server"):
            return await self._execute_app_server(task, resume_session, context)
        else:
            return await self._execute_exec(task, resume_session, context)

    async def _execute_exec(self, task, resume_session, context) -> AgentResult:
        """Run via codex exec --json subprocess."""
        args = self._build_exec_args(task, resume_session)
        # Spawn subprocess, stream JSONL into _ExecStreamCollector
        # Build AgentResult from collector state
        ...

    async def _execute_app_server(self, task, resume_session, context) -> AgentResult:
        """Run via app-server transport."""
        transport = await self._ensure_transport()
        if resume_session:
            await transport.thread_resume(resume_session)
        else:
            resp = await transport.thread_start(...)
            thread_id = resp["thread"]["id"]
        # turn_start, collect notifications, build AgentResult
        ...

    async def _ensure_transport(self) -> CodexAppServerTransport:
        """Lazy-init the app-server transport."""
        if self._transport is None:
            self._transport = CodexAppServerTransport(...)
            await self._transport.start()
        return self._transport

    def _build_exec_args(self, task, resume_session) -> List[str]:
        """Build CLI argument list for codex exec."""
        args = [codex_bin, "exec", "--json", "--model", model, "--full-auto"]
        if resume_session:
            args = [codex_bin, "exec", "resume", "--json", "--model", model,
                    "--full-auto", resume_session, task]
        # ... sandbox, output-schema, add-dirs, config overrides, features
        return args

    def _build_result_from_exec(self, collector, stderr) -> AgentResult:
        """Map _ExecStreamCollector state to AgentResult."""
        ...

    def _build_result_from_turn(self, items, usage, thread_id, error) -> AgentResult:
        """Map app-server turn notifications to AgentResult."""
        ...

    async def execute_with_tools(self, ...):
        raise NotImplementedError("Codex CLI owns its tool loop")

    async def cancel(self) -> bool:
        """SIGTERM → grace → SIGKILL."""
        ...
```

### Component 1d: `CodexCliAdapter` (~30 LOC)

```python
class CodexCliAdapter(AgentAdapter):
    type_name = "codex-cli"

    def create_executor(self, *, agent_name, agent_ref, context) -> AgentExecutor:
        config = agent_ref.config or {}
        settings = context.settings.get("agent_runners", {}).get("codex_cli", {})
        return CodexCliExecutor(config=config, config_dir=context.config_dir, settings=settings)
```

---

## Module 2: `codex_cli_sessions.py` (~150 LOC)

Mirrors `claude_code_sessions.py` but simpler: no warm cycle needed,
fork uses app-server `thread/fork` with explicit model pinning.

```python
@dataclass
class ForkResult:
    """Result from a forked session."""
    thread_id: str
    task: str
    result: AgentResult
    cached_input_tokens: int = 0

@dataclass
class CodexSessionHoldback:
    """Frozen session for cache-warm parallel fan-out via app-server.

    Usage:
        holdback = CodexSessionHoldback(executor)
        await holdback.seed("Read the codebase.")
        results = await holdback.fork_n(["task A", "task B", "task C"])
    """
    executor: CodexCliExecutor
    model: str = "gpt-5.3-codex"
    thread_id: Optional[str] = None
    _seeded: bool = False
    _fork_count: int = 0
    _total_input_tokens: int = 0
    _total_cached_tokens: int = 0

    async def seed(self, task, context=None) -> AgentResult:
        """Create holdback thread via app-server, run seed prompt."""
        transport = await self.executor._ensure_transport()
        resp = await transport.thread_start(
            cwd=..., model=self.model, sandbox=..., approval_policy="never",
        )
        self.thread_id = resp["thread"]["id"]
        result = await self._run_turn(task)
        self._seeded = True
        return result

    async def adopt(self, thread_id) -> None:
        """Adopt existing thread as holdback (no API call)."""
        self.thread_id = thread_id
        self._seeded = True

    async def fork(self, task, context=None) -> ForkResult:
        """Fork from holdback, run task on child. Model pinned."""
        assert self._seeded
        transport = await self.executor._ensure_transport()
        fork_resp = await transport.thread_fork(self.thread_id, model=self.model)
        child_id = fork_resp["thread"]["id"]
        self._fork_count += 1
        result = await self._run_turn_on(child_id, task)
        return ForkResult(thread_id=child_id, task=task, result=result, ...)

    async def fork_n(self, tasks, max_concurrent=4) -> List[ForkResult]:
        """Fork N children in parallel with semaphore."""
        sem = asyncio.Semaphore(max_concurrent)
        async def _limited(t):
            async with sem:
                return await self.fork(t)
        results = await asyncio.gather(*[_limited(t) for t in tasks], return_exceptions=True)
        # Convert exceptions to ForkResult with error
        return [...]

    async def warm(self, context=None) -> AgentResult:
        """No-op health check. Codex cache is automatic, no TTL to reset.
        Kept for API parity with Claude Code SessionHoldback."""
        assert self._seeded
        # Optionally: fork + minimal prompt to verify connectivity
        ...

    @property
    def stats(self) -> Dict[str, Any]:
        return {
            "thread_id": self.thread_id,
            "seeded": self._seeded,
            "fork_count": self._fork_count,
            "total_input_tokens": self._total_input_tokens,
            "total_cached_tokens": self._total_cached_tokens,
        }
```

---

## Module 3: `__init__.py` change (+6 LOC)

```python
    try:
        from .codex_cli import CodexCliAdapter
        registry.register(CodexCliAdapter())
    except ImportError:
        pass
```

---

## Module 4: Tests

### `test_codex_cli_adapter.py` (~120 LOC)

Mock the subprocess to emit canned JSONL, verify AgentResult mapping.

```python
class TestExecStreamCollector:
    def test_simple_message(self):
        # Feed thread.started + turn.started + item.completed(agent_message) + turn.completed
        # Verify: thread_id, final_message, usage, no error

    def test_tool_using_turn(self):
        # Feed item.started(command_execution) + item.completed(command_execution)
        # + item.completed(agent_message) + turn.completed
        # Verify: items list has both command and message

    def test_error_turn(self):
        # Feed error + turn.failed
        # Verify: error captured

class TestBuildExecArgs:
    def test_simple(self):
        # Verify: codex exec --json --model gpt-5.3-codex --full-auto "task"

    def test_resume(self):
        # Verify: codex exec resume --json --model ... --full-auto <id> "task"

    def test_output_schema(self):
        # Verify: --output-schema path included

    def test_sandbox_modes(self):
        # Verify: --sandbox read-only, workspace-write, danger-full-access

    def test_config_overrides(self):
        # Verify: -c key=value pairs

    def test_model_always_pinned(self):
        # Verify: --model always present, never omitted

class TestCodexCliExecutor:
    async def test_execute_simple(self):
        # Mock subprocess with canned JSONL, verify AgentResult

    async def test_execute_resume(self):
        # Verify resume_session flows to exec resume subcommand

    async def test_execute_timeout(self):
        # Verify SIGTERM + SIGKILL on timeout

    async def test_cancel(self):
        # Verify cancel sends SIGTERM then SIGKILL
```

### `test_codex_cli_sessions.py` (~100 LOC)

Mirror `test_claude_code_sessions.py` structure.

```python
class TestSeed:
    async def test_seed_creates_thread(self): ...
    async def test_seed_single_call(self): ...
    async def test_seed_with_provided_thread_id(self): ...

class TestAdopt:
    async def test_adopt_sets_thread(self): ...
    async def test_adopt_no_api_call(self): ...

class TestFork:
    async def test_fork_uses_thread_fork(self): ...
    async def test_fork_pins_model(self): ...
    async def test_fork_not_seeded_raises(self): ...

class TestForkN:
    async def test_fork_n_parallel(self): ...
    async def test_fork_n_concurrency_limit(self): ...
    async def test_fork_n_handles_exceptions(self): ...

class TestStats:
    def test_initial_stats(self): ...
```

---

## Implementation Task List

### Phase 1: Exec Transport (can be used immediately, no app-server)

- [ ] **1.1** Create `sdk/python/flatmachines/flatmachines/adapters/codex_cli.py`
  - [ ] 1.1.1 Write module docstring with config key reference
  - [ ] 1.1.2 Implement `_ExecStreamCollector` (ingest 6 event types)
  - [ ] 1.1.3 Implement `CodexCliExecutor._build_exec_args()` (all flags)
  - [ ] 1.1.4 Implement `CodexCliExecutor._execute_exec()` (subprocess spawn, JSONL streaming, stderr capture)
  - [ ] 1.1.5 Implement `CodexCliExecutor._build_result_from_exec()` (AgentResult mapping)
  - [ ] 1.1.6 Implement `CodexCliExecutor.cancel()` (SIGTERM → grace → SIGKILL)
  - [ ] 1.1.7 Implement `CodexCliAdapter` (type_name = "codex-cli", create_executor)
  - [ ] 1.1.8 Wire `execute()` to dispatch to `_execute_exec()` (app-server path stubbed)

- [ ] **1.2** Register adapter in `__init__.py`
  - [ ] 1.2.1 Add `CodexCliAdapter` import + registration block

- [ ] **1.3** Write exec transport unit tests
  - [ ] 1.3.1 `TestExecStreamCollector` (simple message, tool turn, error)
  - [ ] 1.3.2 `TestBuildExecArgs` (simple, resume, output-schema, sandbox, config overrides, model pinning)
  - [ ] 1.3.3 `TestCodexCliExecutor` with mocked subprocess (execute, resume, timeout, cancel)

- [ ] **1.4** Verify exec transport end-to-end
  - [ ] 1.4.1 Run a live `codex exec --json` invocation through the adapter
  - [ ] 1.4.2 Verify `AgentResult` fields: content, usage, thread_id in metadata, no error
  - [ ] 1.4.3 Verify resume: second call with `resume_session` gets cache hits

### Phase 2: App-Server Transport (required for fork)

- [ ] **2.1** Implement `CodexAppServerTransport` in `codex_cli.py`
  - [ ] 2.1.1 `start()`: spawn subprocess, initialize JSON-RPC (`clientInfo` required)
  - [ ] 2.1.2 `stop()`: terminate subprocess, cancel reader task
  - [ ] 2.1.3 `_request()`: send JSON-RPC, correlate response by ID
  - [ ] 2.1.4 `_read_loop()`: read stdout, dispatch responses and notifications
  - [ ] 2.1.5 Typed methods: `thread_start`, `thread_fork`, `thread_resume`, `thread_read`
  - [ ] 2.1.6 Typed methods: `turn_start`, `turn_interrupt`
  - [ ] 2.1.7 Notification callback registration (`on_notification`)
  - [ ] 2.1.8 Error handling: RPC errors, subprocess crashes, read timeouts

- [ ] **2.2** Wire app-server path in executor
  - [ ] 2.2.1 Implement `_ensure_transport()` (lazy init + start)
  - [ ] 2.2.2 Implement `_execute_app_server()` (thread_start/resume → turn_start → collect notifications → AgentResult)
  - [ ] 2.2.3 Implement `_build_result_from_turn()` (map notifications to AgentResult)
  - [ ] 2.2.4 Handle `thread/tokenUsage/updated` (usage arrives separately from `turn/completed`)
  - [ ] 2.2.5 Handle `turn/failed` with error extraction
  - [ ] 2.2.6 Implement transport cleanup in executor destructor / context manager

- [ ] **2.3** Write app-server transport unit tests
  - [ ] 2.3.1 Mock stdin/stdout pipe, verify JSON-RPC request/response correlation
  - [ ] 2.3.2 Verify notification dispatch to callbacks
  - [ ] 2.3.3 Verify `thread_fork` always includes model parameter
  - [ ] 2.3.4 Verify RPC error handling

### Phase 3: Session Holdback

- [ ] **3.1** Create `sdk/python/flatmachines/flatmachines/adapters/codex_cli_sessions.py`
  - [ ] 3.1.1 Implement `ForkResult` dataclass
  - [ ] 3.1.2 Implement `CodexSessionHoldback.seed()` (thread_start + turn_start)
  - [ ] 3.1.3 Implement `CodexSessionHoldback.adopt()` (set state, no API call)
  - [ ] 3.1.4 Implement `CodexSessionHoldback.fork()` (thread_fork with model pin + turn_start)
  - [ ] 3.1.5 Implement `CodexSessionHoldback.fork_n()` (parallel with semaphore, exception handling)
  - [ ] 3.1.6 Implement `CodexSessionHoldback.warm()` (no-op / health check)
  - [ ] 3.1.7 Implement `CodexSessionHoldback.stats` property
  - [ ] 3.1.8 Implement `_run_turn()` helper (turn_start + notification collection + timeout)

- [ ] **3.2** Write session holdback unit tests
  - [ ] 3.2.1 `TestSeed` (creates thread, single call, with provided ID)
  - [ ] 3.2.2 `TestAdopt` (sets state, no API call)
  - [ ] 3.2.3 `TestFork` (uses thread_fork, pins model, not-seeded raises)
  - [ ] 3.2.4 `TestForkN` (parallel execution, concurrency limit, exception handling)
  - [ ] 3.2.5 `TestStats` (initial state)

### Phase 4: Integration Verification

- [ ] **4.1** Live exec test: single-shot task through adapter
- [ ] **4.2** Live exec test: resume with cache hit verification
- [ ] **4.3** Live app-server test: seed → fork → verify child has parent context
- [ ] **4.4** Live app-server test: seed → fork_n(3) → verify all children get cache hits
- [ ] **4.5** Cross-transport test: create thread via app-server, resume via `codex exec resume` CLI
- [ ] **4.6** Verify session visibility: threads from adapter appear in `codex resume --all`
- [ ] **4.7** Verify model pinning: fork with explicit model, check response `model` field

### Estimated LOC

| File | LOC |
|------|-----|
| `codex_cli.py` | ~450 |
| `codex_cli_sessions.py` | ~150 |
| `__init__.py` (diff) | +6 |
| `test_codex_cli_adapter.py` | ~120 |
| `test_codex_cli_sessions.py` | ~100 |
| **Total** | **~826** |

### Risk: App-Server Stability

The app-server protocol is used by the VS Code extension and is well-exercised,
but it's not documented as a public API. Wire format changes could break the
transport. Mitigations:

1. Pin to `codex-cli 0.116.0` for now
2. Exec transport works without app-server (no fork, but resume works)
3. JSON Schema generation (`codex app-server generate-json-schema`) provides
   a machine-readable contract we can diff against future versions
4. Integration tests catch protocol drift early

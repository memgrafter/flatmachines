# Claude Code CLI Adapter — Design Plan

> Tight v1 scope. Session management and cache fan-out deferred to v2.

## Scope

**In (v1):**
- `ClaudeCodeAdapter` + `ClaudeCodeExecutor` — new adapter type `"claude-code"`
- Single invocation: spawn `claude -p`, stream NDJSON, return `AgentResult`
- Session resume via `input.resume_session` → `--resume`
- Hook translation: stream events → `on_tool_calls` / `on_tool_result`
- Continue-until-done loop with sentinel detection
- Auto-registration in adapter registry

**Out (v2+):**
- Session fan-out / holdback pattern (cache parallelism)
- MCP / plugins / `--agent`
- `--json-schema` structured output interception

---

## 1. Adapter Registration

New file: `sdk/python/flatmachines/flatmachines/adapters/claude_code.py`

Registration in `adapters/__init__.py`:

```python
try:
    from .claude_code import ClaudeCodeAdapter
    registry.register(ClaudeCodeAdapter())
except ImportError:
    pass
```

No new dependencies — uses `asyncio.create_subprocess_exec` and stdlib
`json`. The `claude` binary must be on `$PATH` (or configured via
`config.claude_bin`).

---

## 2. Config Shape

```yaml
agents:
  coder:
    type: claude-code
    config:
      # Model
      model: opus                            # --model (default: opus)
      
      # Permissions (required for headless)
      permission_mode: bypassPermissions     # --permission-mode
      
      # Prompt control
      system_prompt: "..."                   # --system-prompt (replaces default entirely)
      append_system_prompt: "..."            # --append-system-prompt (mutually exclusive)
      
      # Tool control (exact whitelist)
      tools:                                 # --tools (exact list, not additive)
        - Bash
        - Read
        - Write
        - Edit
        - Glob
        - Grep
      
      # Cost / effort
      max_budget_usd: 0                      # --max-budget-usd (0 = disabled, default)
      effort: high                           # --effort (default: high)
      
      # Execution
      working_dir: "{{ context.working_dir }}" # cwd for subprocess
      timeout: 0                             # subprocess timeout seconds (0 = disabled, default)
      claude_bin: claude                     # path to claude binary
      
      # Continue-until-done loop
      max_continuations: 100                 # max --resume loops (default 100, -1 = unlimited, 0 = no auto-continue)
      exit_sentinel: "<<AGENT_EXIT>>"        # sentinel string in result text
      continuation_prompt: 'Continue working. When fully done, emit <<AGENT_EXIT>> on its own line.'
```

All fields optional except `permission_mode` (enforced at executor init
for headless safety — can be relaxed later).

**Defaults:**
- `model`: opus (maps to `claude-opus-4-6` — the default for serious work)
- `effort`: high
- `timeout`: 0 (disabled). Machines may wait, idle, or run long tasks.
  A default timeout is a footgun — the user opts in explicitly. 0 means
  no timeout; any positive value is seconds.
- `max_budget_usd`: 0 (disabled). Same reasoning — user opts in.
- `max_continuations`: 100. -1 means unlimited. 0 means no auto-continue.
- `exit_sentinel`: `<<AGENT_EXIT>>`

**Design rules codified:**
- `json_schema` is intentionally absent from the config schema. If
  structured extraction is needed, use a downstream FlatAgent extractor.
- `tools` uses the exact `--tools` flag, not `--allowed-tools`. Prevents
  tool creep on CLI updates.
- **No data truncation anywhere.** Stream events, result text, tool
  outputs, stderr — all captured in full. The adapter never truncates.
  If the user wants truncation, they do it in hooks or downstream. This
  is a hard rule.

---

## 3. ClaudeCodeAdapter

Mirrors `PiAgentBridgeAdapter` pattern:

```python
class ClaudeCodeAdapter(AgentAdapter):
    type_name = "claude-code"

    def create_executor(
        self,
        *,
        agent_name: str,
        agent_ref: AgentRef,
        context: AgentAdapterContext,
    ) -> AgentExecutor:
        config = agent_ref.config or {}
        
        # Resolve working_dir templates at create time won't work
        # (context not yet available). Executor resolves at execute time.
        
        return ClaudeCodeExecutor(
            config=config,
            config_dir=context.config_dir,
            settings=context.settings.get("agent_runners", {}).get("claude_code", {}),
        )
```

---

## 4. ClaudeCodeExecutor

### 4.1 `execute()` — The Core

```
async execute(input_data, context) -> AgentResult:

  1. Determine session mode:
     - input_data has "resume_session" → resume mode (--resume <id>)
     - else → new session (--session-id <uuid4>)

  2. Build CLI args from config + input:
     claude -p <task>
       --output-format stream-json
       --verbose
       --session-id <id> | --resume <id>
       --model <model>
       --permission-mode <mode>
       --system-prompt <prompt> | --append-system-prompt <prompt>
       --tools <tool1> <tool2> ...
       --max-budget-usd <budget>
       --effort <level>

  3. Resolve working_dir:
     config.working_dir → render with context → absolute path → cwd

  4. Spawn subprocess:
     asyncio.create_subprocess_exec(
       *args,
       stdout=PIPE, stderr=PIPE,
       cwd=working_dir,
       env={**os.environ}  # inherit, no mutation
     )

  5. Stream stdout line-by-line (NDJSON):
     - Parse each line as JSON, NO TRUNCATION of any field
     - Dispatch by event["type"]:
       "system"    → capture session metadata
       "assistant" → fire hooks, accumulate ALL text
       "user"      → fire hooks (tool results, full content)
       "result"    → build AgentResult, break
     - On parse error: log warning, skip line

  6. Build AgentResult from "result" event
     - All fields preserved in full — no truncation of result text,
       tool outputs, stderr, or stream events

  7. Timeout handling:
     - timeout=0 (default): no timeout, wait forever
     - timeout>0: after N seconds, SIGTERM → 5s grace → SIGKILL
     - On timeout: raise TimeoutError (not a silent AgentResult error)
     - Timeout is wall-clock from subprocess spawn to result event

  8. Continue-until-done loop (if configured):
     - If no exit_sentinel in result AND continuations remain:
       Resume with session_id, task=continuation_prompt
     - max_continuations=100 (default), -1=unlimited, 0=no auto-continue
     - If exit_sentinel found OR counter exhausted: return final result
```

### 4.2 `execute_with_tools()` — Not Implemented

Claude Code owns its tool loop. The adapter raises `NotImplementedError`.
FlatMachine states using this adapter must NOT set `tool_loop:`. This is
the same pattern as the analysis doc describes — no `tool_loop`, plain
agent call.

### 4.3 CLI Arg Builder

Private method `_build_args(task, session_id, resume, config) -> List[str]`:

```python
args = [claude_bin, "-p", task, "--output-format", "stream-json", "--verbose"]

if resume:
    args += ["--resume", session_id]
else:
    args += ["--session-id", session_id]

# Model defaults to opus
model = config.get("model", "opus")
args += ["--model", model]

if config.get("permission_mode"):
    args += ["--permission-mode", config["permission_mode"]]

if config.get("system_prompt"):
    args += ["--system-prompt", config["system_prompt"]]
elif config.get("append_system_prompt"):
    args += ["--append-system-prompt", config["append_system_prompt"]]

if config.get("tools"):
    args += ["--tools"] + config["tools"]

# max_budget_usd: 0 = disabled (default), positive = enabled
max_budget = config.get("max_budget_usd", 0)
if max_budget and max_budget > 0:
    args += ["--max-budget-usd", str(max_budget)]

# effort defaults to high
effort = config.get("effort", "high")
args += ["--effort", effort]

return args
```

### 4.4 Stream Parser

Private async method `_stream_events(proc, hooks_ctx) -> (result_event, stream_metadata)`:

Reads `proc.stdout` line by line. For each parsed JSON event:

| Event type | Action |
|-----------|--------|
| `system` | Store `session_id`, `tools`, `model` in metadata |
| `assistant` with `tool_use` blocks | Build tool_calls list, fire `hooks_ctx.on_tool_calls()` |
| `assistant` with `text` blocks | Accumulate text for display/context |
| `user` with `tool_result` blocks | Match to prior tool_use by ID, fire `hooks_ctx.on_tool_result()` |
| `result` | Return as final result |
| `rate_limit_event` | Log, store in metadata |

The hooks context is a simple dataclass passed in that holds the
`MachineHooks` ref + state_name + context. The executor doesn't import
hooks directly — it receives a callback interface.

**Hook firing problem:** The executor is called by the machine engine
which then fires hooks. But we want hooks to fire *during* streaming,
not after. The solution: the executor accepts an optional `hooks`
parameter via a protocol extension, OR the machine engine passes a
callback bag.

**Chosen approach:** Add an optional `stream_hooks` kwarg to `execute()`.
The machine engine's `_execute_state` already has access to hooks — it
passes them through. Other adapters ignore the kwarg. This is
backward-compatible since `execute()` takes `**kwargs` in practice
(Protocol doesn't enforce strictness).

Actually, simpler: the executor stores stream events and the machine
fires hooks after. Real-time display during streaming can use a
separate log/callback mechanism outside hooks. This keeps the adapter
clean and hooks composable.

**Final decision:** Store events during streaming. Return them in
`AgentResult.metadata["stream_events"]`. Provide a helper
`ClaudeCodeHooks(MachineHooks)` that reads stream events from the
result in `on_state_exit` and fires tool display. For v1 this is
sufficient. Real-time streaming hooks can be added in v2.

### 4.5 Result Mapping

```python
AgentResult(
    output={
        "result": event["result"],
        "session_id": event["session_id"],
    },
    content=event["result"],
    usage={
        "input_tokens": event["usage"]["input_tokens"],
        "output_tokens": event["usage"]["output_tokens"],
        "cache_read_tokens": event["usage"].get("cache_read_input_tokens", 0),
        "cache_write_tokens": event["usage"].get("cache_creation_input_tokens", 0),
    },
    cost=event.get("total_cost_usd"),
    finish_reason=_map_stop_reason(event.get("stop_reason")),
    error=_build_error(event) if event.get("is_error") else None,
    metadata={
        "num_turns": event.get("num_turns"),
        "duration_ms": event.get("duration_ms"),
        "session_id": event["session_id"],
        "stream_events": collected_events,  # for hook replay
    },
    provider_data=event.get("modelUsage"),
)
```

### 4.6 Error Handling

| Condition | Behavior |
|-----------|----------|
| `proc.returncode != 0` | `AgentResult(error={code: "server_error", ...})` with full stderr |
| `event.is_error == true` | `AgentResult(error={code: ..., message: event.result})` — full message, no truncation |
| Timeout (timeout > 0) | SIGTERM → 5s grace → SIGKILL. **Raises `TimeoutError`**, not a silent error result. The machine's `on_error` or `execution.retry` handles it. |
| Timeout = 0 (default) | No timeout. Process runs until completion. |
| JSON parse error on line | Log warning with full raw line, skip, continue |
| No `result` event received | `AgentResult(error={code: "server_error", message: "no result event"})` with full stderr |

---

## 5. Continue-Until-Done Loop

When a Claude Code state represents a long-running task (e.g., "implement
this feature"), Claude may stop mid-work (context limit, end_turn with
pending work). The adapter handles this transparently.

### Config

```yaml
config:
  max_continuations: 100       # default 100. -1 = unlimited. 0 = no auto-continue.
  exit_sentinel: "<<AGENT_EXIT>>"
  continuation_prompt: 'Continue working. When fully done, emit <<AGENT_EXIT>> on its own line.'
```

### Logic (in execute)

```python
attempt = 0
while True:
    result = await self._invoke_once(task, session_id, resume=(attempt > 0))
    attempt += 1
    
    if result.error:
        return result
    
    result_text = result.content or ""
    
    # Check sentinel
    if exit_sentinel in result_text:
        return result
    
    # Check natural completion (no tool use, clean end_turn)
    if result.finish_reason == "stop" and result.metadata.get("num_turns", 0) <= 1:
        return result
    
    # Check continuation limit (0 = no auto-continue, -1 = unlimited)
    if max_continuations == 0:
        return result
    if max_continuations > 0 and attempt > max_continuations:
        return result
    
    # Continue — the prompt reminds about the sentinel
    task = continuation_prompt
    resume = True

return result
```

### System Prompt Integration

The system prompt (or append) must include:

```
When you have completed the task fully, include <<AGENT_EXIT>> on its own
line in your final response. Do not include it until all work is done.
```

The `continuation_prompt` also reminds about the sentinel on every
resume, so even if the system prompt instruction fades in long contexts,
the user message reinforces it:

```
Continue working. When fully done, emit <<AGENT_EXIT>> on its own line.
```

---

## 6. Session Management (v1 — Simple)

v1 provides basic session resume via context threading. No fan-out.

### Machine Config Pattern

```yaml
states:
  plan:
    agent: coder
    input:
      task: "Plan the implementation of {{ context.feature }}"
    output_to_context:
      session_id: "{{ output.session_id }}"
      plan: "{{ output.result }}"
    transitions:
      - to: implement

  implement:
    agent: coder
    input:
      task: "Implement the plan"
      resume_session: "{{ context.session_id }}"
    output_to_context:
      result: "{{ output.result }}"
      session_id: "{{ output.session_id }}"
    transitions:
      - to: done
```

The `session_id` flows through machine context. Each state that passes
`resume_session` in input gets `--resume` instead of `--session-id`.
Cache stays warm.

---

## 7. Helper Hooks — ClaudeCodeHooks

Optional hooks class for CLI-style display (like existing `CLIToolHooks`):

```python
class ClaudeCodeHooks(MachineHooks):
    """Display hooks for Claude Code adapter states."""
    
    def on_state_exit(self, state_name, context, output):
        # Replay stream events for display
        events = (output or {}).get("_stream_events", [])
        for event in events:
            if event["type"] == "assistant":
                for block in event.get("message", {}).get("content", []):
                    if block["type"] == "tool_use":
                        print(f"  ✓ {block['name']}: {_summarize(block['input'])}")
        return output
```

---

## 8. File Layout

```
sdk/python/flatmachines/flatmachines/adapters/
  __init__.py                    # Add ClaudeCodeAdapter registration
  claude_code.py                 # ClaudeCodeAdapter + ClaudeCodeExecutor
  claude_code_sessions.py        # SessionHoldback for cache-warm fan-out

sdk/examples/claude_code_adapter/
  config/
    machine.yml                  # Example machine config
    profiles.yml                 # Example profiles
  python/
    src/claude_code_example/
      __init__.py
      main.py                    # CLI runner
      hooks.py                   # ClaudeCodeHooks
    pyproject.toml
    README.md
```

---

## 9. Session Holdback (Cache-Warm Fan-Out)

Implemented in `claude_code_sessions.py`. Empirically validated.

### How It Works

```python
holdback = SessionHoldback(executor)
await holdback.seed("Read the codebase...")   # new session + auto-warm
results = await holdback.fork_n(["task1", "task2", "task3"])  # parallel, all hit cache
```

- `seed()` creates the holdback session. Cache is available immediately.
- `fork()` uses `--resume <holdback_id> --fork-session` — gets a new session
  ID but sees the full holdback conversation. Holdback is never advanced.
- `fork_n()` runs N forks in parallel with optional concurrency limit.
- `warm()` sends a minimal fork ("test") to reset the 1-hour cache TTL.
  Only needed if holdback has been idle for close to 1 hour.
- `adopt()` takes an existing session ID as holdback. No API call.

### Cache Findings

Cache is available immediately after seed returns. Validated with
truly cold prefixes (UUID in system prompt to bust all cached state):

| Pattern | cache_read | cache_write | Notes |
|---------|-----------|-------------|-------|
| Seed (cold) | 0 | 9,789 | Nothing cached, full write |
| Parallel fork ×3 (immediate) | 9,789 | ~22 | Full cache hit, no warm needed |

Tested with 4 different ~200-token messages forked from the same
holdback (1 sequential + 3 parallel) — all got identical cache_read.
The API cache is purely prefix-based; divergent user messages after
the cached prefix do not affect cache hits.

### What the Cache Covers

- **System prompt** (~6.5K tokens): Always cached across all sessions with
  the same tools/model config.
- **Conversation body**: Cached after seed + warm. Each fork reads it from
  cache and writes only its new user message (~20-30 tokens).
- **Cache TTL**: 1 hour on Claude Max plan. `warm()` resets it.

---

## 10. Scope Boundaries

| Feature | Status |
|---------|--------|
| Session fan-out / holdback | **Implemented.** `SessionHoldback` in `claude_code_sessions.py`. Validated with live cache metrics. |
| `--json-schema` support | Not building. Design rule: no structured output on CLI adapter. Use extractor agents. |
| MCP / plugins / `--agent` | Future investigation (checklist §5). |
| Real-time streaming hooks | v1 stores events, replays in `on_state_exit`. Real-time adds complexity to hook contract. |
| `execute_with_tools()` | Not building. Claude Code owns its tool loop. `NotImplementedError`. |
| `--input-format stream-json` | Not building. Bidirectional piping is experimental. `--resume` is simpler and proven. |

---

## 11. Testing Strategy

### Unit Tests (no claude binary needed)

- `test_build_args`: config → CLI args mapping
- `test_parse_stream_event`: NDJSON line → parsed event
- `test_result_mapping`: CLI result JSON → AgentResult
- `test_continuation_logic`: sentinel detection, counter exhaustion
- `test_session_mode`: new vs resume based on input
- `test_config_validation`: required fields, mutual exclusion

### Integration Tests (requires claude binary)

- `test_simple_invocation`: `claude -p "what is 2+2"` → AgentResult with content
- `test_session_resume`: new session → resume → verify cache_read_tokens increases
- `test_stream_events`: verify NDJSON parsing against live output
- `test_machine_execution`: full machine config → execute → verify context flow

### Mock Strategy

For unit tests, mock `asyncio.create_subprocess_exec` to return
canned NDJSON streams. Fixture files in `tests/fixtures/claude_code/`:
- `simple_result.ndjson`
- `tool_use_session.ndjson`
- `error_result.ndjson`
- `multi_turn.ndjson`

---

## 12. Implementation Order

1. **`claude_code.py`** — Adapter + Executor skeleton with `_build_args`
2. **Stream parser** — NDJSON reader + event dispatch
3. **Result mapping** — CLI result → AgentResult
4. **Continue loop** — Sentinel + counter logic
5. **Registration** — Wire into `adapters/__init__.py`
6. **Unit tests** — Against mock streams
7. **Example** — `sdk/examples/claude_code_adapter/`
8. **Integration tests** — Against live `claude` binary

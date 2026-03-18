# Claude Code CLI Adapter Analysis

> How to integrate Claude Code CLI as a FlatMachines agent adapter.
>
> Prerequisite: [claude-code-cli-reference.md](./claude-code-cli-reference.md)
> for the full CLI surface, output formats, and session behavior.

## Context

Claude Code has disallowed proxying to its subscription API. The CLI remains
the supported interface. This analysis covers how to wrap the CLI as a
FlatMachines agent adapter, following the patterns established by the existing
adapters.

## Adapter Interface Contracts

These are the interfaces the adapter must implement. Copied from the
FlatMachines SDK source (`flatmachines/agents.py`, `flatmachines/hooks.py`).

### AgentExecutor (Protocol)

```python
class AgentExecutor(Protocol):
    async def execute(
        self,
        input_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> AgentResult:
        ...

    @property
    def metadata(self) -> Dict[str, Any]:
        ...
```

`execute_with_tools()` also exists on the protocol but does **not apply** to
this adapter. Claude Code CLI manages its own tools internally.

### AgentResult (Dataclass)

```python
@dataclass
class AgentResult:
    output: Optional[Dict[str, Any]] = None      # Structured output dict
    content: Optional[str] = None                 # Text content
    raw: Any = None                               # In-process only
    usage: Optional[Dict[str, Any]] = None        # Token usage
    cost: Optional[Union[Dict, float]] = None     # Cost info
    metadata: Optional[Dict[str, Any]] = None     # Extra metadata
    finish_reason: Optional[str] = None           # "stop", "length", "error", etc.
    error: Optional[Dict[str, Any]] = None        # Error info (None = success)
    rate_limit: Optional[Dict[str, Any]] = None   # Rate limit state
    provider_data: Optional[Dict[str, Any]] = None  # Provider-specific data
    tool_calls: Optional[List[Dict]] = None       # Not used for this adapter
```

### AgentAdapter (Protocol)

```python
class AgentAdapter(Protocol):
    type_name: str  # e.g., "claude-code"

    def create_executor(
        self,
        *,
        agent_name: str,
        agent_ref: AgentRef,         # AgentRef(type="claude-code", ref=None, config={...})
        context: AgentAdapterContext, # config_dir, settings, machine_name, profiles
    ) -> AgentExecutor:
        ...
```

### AgentRef & AgentAdapterContext

```python
@dataclass
class AgentRef:
    type: str                              # "claude-code"
    ref: Optional[str] = None              # Not used for CLI adapter
    config: Optional[Dict[str, Any]] = None  # CLI flags as config

@dataclass
class AgentAdapterContext:
    config_dir: str                        # Directory containing machine YAML
    settings: Dict[str, Any]               # Machine settings
    machine_name: str
    profiles_file: Optional[str] = None
    profiles_dict: Optional[Dict[str, Any]] = None
```

### Hook Methods (from MachineHooks)

The adapter doesn't implement hooks directly — it fires them by writing
events into the context or calling the hooks object. The relevant hook
signatures are:

```python
def on_tool_calls(
    self,
    state_name: str,
    tool_calls: list,       # [{id, name, arguments}, ...]
    context: Dict[str, Any],
) -> Dict[str, Any]:
    """Called BEFORE tool execution. Can set _abort_tool_loop or _skip_tools."""

def on_tool_result(
    self,
    state_name: str,
    tool_result: Dict[str, Any],  # {tool_call_id, name, arguments, content, is_error}
    context: Dict[str, Any],
) -> Dict[str, Any]:
    """Called AFTER each tool execution."""
```

## Adapter Registration

New adapters are registered in the `AgentAdapterRegistry`. The built-in
adapters are registered in `flatmachines/adapters/__init__.py`:

```python
def register_builtin_adapters(registry: AgentAdapterRegistry) -> None:
    try:
        from .flatagent import FlatAgentAdapter
        registry.register(FlatAgentAdapter())       # type_name = "flatagent"
    except ImportError:
        pass
    try:
        from .smolagents import SmolagentsAdapter
        registry.register(SmolagentsAdapter())      # type_name = "smolagents"
    except ImportError:
        pass
    try:
        from .pi_agent_bridge import PiAgentBridgeAdapter
        registry.register(PiAgentBridgeAdapter())   # type_name = "pi-agent"
    except ImportError:
        pass
```

The Claude Code adapter adds a new entry:

```python
    try:
        from .claude_code import ClaudeCodeAdapter
        registry.register(ClaudeCodeAdapter())      # type_name = "claude-code"
    except ImportError:
        pass
```

This enables YAML configs to reference it:

```yaml
agents:
  coder: { type: "claude-code", config: { model: "sonnet" } }
```

## The Integration Pattern

Claude Code CLI is a **monolithic coding agent** — it owns the LLM call, tool
execution, and conversation loop internally. The adapter wraps it as a single
`execute()` call. FlatMachine's `tool_loop` state config does **not** apply.

### Machine YAML

```yaml
agents:
  coder:
    type: claude-code
    config:
      model: sonnet
      permission_mode: bypassPermissions
      append_system_prompt: "Focus on test coverage."
      allowed_tools: ["Bash", "Read", "Edit", "Write", "Grep", "Glob"]
      max_budget_usd: 2.00
      timeout: 300

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
      cost: "{{ output.total_cost_usd }}"
    transitions:
      - to: done
```

No `tool_loop: true`. The CLI runs its full agentic loop internally.

### Session ID Flows Through Context

When `input.resume_session` is present, the adapter passes `--resume <id>`
instead of `--session-id <new-uuid>`. This preserves the full conversation
history and Anthropic's prompt cache.

## Config → CLI Arg Mapping

| Config Key | CLI Flag |
|------------|----------|
| `model` | `--model` |
| `effort` | `--effort` |
| `permission_mode` | `--permission-mode` |
| `system_prompt` | `--system-prompt` |
| `append_system_prompt` | `--append-system-prompt` |
| `allowed_tools` | `--allowed-tools` (space-separated) |
| `disallowed_tools` | `--disallowed-tools` (space-separated) |
| `max_budget_usd` | `--max-budget-usd` |
| `json_schema` | `--json-schema` (JSON string) |
| `add_dirs` | `--add-dir` (repeated) |
| `timeout` | subprocess timeout (not a CLI flag) |
| `working_dir` | `cwd` for `subprocess.Popen` |
| `mcp_config` | `--mcp-config` |

Special input keys:
| Input Key | Behavior |
|-----------|----------|
| `task` | The prompt text (positional arg to `claude -p`) |
| `resume_session` | If present, use `--resume <value>` instead of `--session-id <new-uuid>` |

## Execute Flow

```
async def execute(input_data, context):
    task = input_data["task"]
    resume_id = input_data.get("resume_session")

    # 1. Build CLI args
    args = ["claude", "-p", task,
            "--output-format", "stream-json", "--verbose"]

    if resume_id:
        args += ["--resume", resume_id]
    else:
        session_id = str(uuid.uuid4())
        args += ["--session-id", session_id]

    args += self._config_to_flags()  # model, permission_mode, etc.

    # 2. Spawn subprocess
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=self._working_dir,
    )

    # 3. Stream stdout line by line
    result_event = None
    tool_context = {}  # maps tool_use_id -> {name, arguments}

    async for raw_line in proc.stdout:
        line = raw_line.decode().strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue  # skip malformed lines

        etype = event.get("type")

        if etype == "assistant":
            for block in event.get("message", {}).get("content", []):
                if block.get("type") == "tool_use":
                    tool_id = block["id"]
                    tool_context[tool_id] = {
                        "name": block["name"],
                        "arguments": block.get("input", {}),
                    }
                    # Fire on_tool_calls hook if hooks available
                    # hooks.on_tool_calls(state_name, [block], context)

        elif etype == "user":
            for block in event.get("message", {}).get("content", []):
                if block.get("type") == "tool_result":
                    tool_id = block.get("tool_use_id")
                    tc = tool_context.get(tool_id, {})
                    tool_result = {
                        "tool_call_id": tool_id,
                        "name": tc.get("name", ""),
                        "arguments": tc.get("arguments", {}),
                        "content": block.get("content", ""),
                        "is_error": block.get("is_error", False),
                    }
                    # Fire on_tool_result hook if hooks available
                    # hooks.on_tool_result(state_name, tool_result, context)

        elif etype == "result":
            result_event = event

    # 4. Wait for process exit
    await proc.wait()

    # 5. Handle errors
    if proc.returncode != 0 and result_event is None:
        stderr = (await proc.stderr.read()).decode().strip()
        return AgentResult(
            error={"code": "process_error", "message": stderr,
                   "status_code": proc.returncode, "retryable": False},
            finish_reason="error",
        )

    # 6. Build AgentResult from result event
    return self._build_result(result_event, session_id or resume_id)
```

## AgentResult Mapping

| CLI Result Field | AgentResult Field | Notes |
|-----------------|-------------------|-------|
| `result` | `content` | Human-readable text |
| `total_cost_usd` | `cost` | Float |
| `usage.input_tokens` | `usage["input_tokens"]` | |
| `usage.output_tokens` | `usage["output_tokens"]` | |
| `usage.cache_read_input_tokens` | `usage["cache_read_tokens"]` | |
| `usage.cache_creation_input_tokens` | `usage["cache_write_tokens"]` | |
| `session_id` | `output["session_id"]` | Forwarded via `output_to_context` |
| `num_turns` | `metadata["num_turns"]` | |
| `duration_ms` | `metadata["duration_ms"]` | |
| `stop_reason` | `finish_reason` | Map `"end_turn"` → `"stop"` |
| `is_error` | `error` | If true: `{"code": "session_error", "message": result}` |
| `modelUsage` | `provider_data` | Pass through as-is |
| (StructuredOutput tool_use) | `output` | See below |

### Structured Output Extraction

When `json_schema` is configured and a `StructuredOutput` tool_use block
appears in the stream, extract its `input` field as `AgentResult.output`:

```python
if block.get("name") == "StructuredOutput":
    structured_output = block.get("input", {})
    # Later: result.output = structured_output
```

This means `output_to_context` can reference `output.languages[0].name` etc.

## Hook Event Translation

The stream events map directly to the existing hook signatures used by
`coding_machine_cli`:

### `assistant` with `tool_use` → `on_tool_calls`

```python
# CLI stream:
{"type": "assistant", "message": {"content": [
    {"type": "tool_use", "id": "toolu_01X", "name": "Bash",
     "input": {"command": "ls", "description": "List files"}}
]}}

# Hook call:
hooks.on_tool_calls("work", [
    {"id": "toolu_01X", "name": "Bash",
     "arguments": {"command": "ls", "description": "List files"}}
], context)
```

### `user` with `tool_result` → `on_tool_result`

```python
# CLI stream:
{"type": "user", "message": {"content": [
    {"tool_use_id": "toolu_01X", "type": "tool_result",
     "content": "file1.py\nfile2.py", "is_error": false}
]}}

# Hook call (enriched with tool_use info from earlier):
hooks.on_tool_result("work", {
    "tool_call_id": "toolu_01X",
    "name": "Bash",
    "arguments": {"command": "ls", "description": "List files"},
    "content": "file1.py\nfile2.py",
    "is_error": False,
}, context)
```

This gives the same real-time visibility as the existing examples — the
`CLIToolHooks` pattern (`✓ bash: ls`, `✓ edit: src/main.py`) works
unchanged.

## Process Lifecycle

### Spawning

```python
proc = await asyncio.create_subprocess_exec(
    *args,
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
    cwd=working_dir,
)
```

### Timeout

The adapter enforces a timeout via `asyncio.wait_for` or by monitoring
elapsed time. On timeout:

1. Send `SIGTERM` to the process
2. Wait 5 seconds
3. Send `SIGKILL` if still running
4. Return `AgentResult(error={"code": "timeout", "message": "...", "retryable": True})`

Note: a killed CLI process produces no `result` event. The adapter must
handle incomplete streams gracefully — any events received before the kill
are still valid for hook callbacks.

### Stderr

Stderr is captured but only read on non-zero exit when no `result` event
was received. During normal execution, stderr may contain debug/warning
output that is ignored.

### Malformed Lines

Non-JSON lines in stdout are silently skipped. The NDJSON stream is
line-delimited; partial lines (from process kill) are caught by the
`json.JSONDecodeError` handler.

### Cancellation

If the FlatMachine is cancelled (e.g., via abort signal), the adapter sends
`SIGTERM` to the subprocess, waits briefly, then `SIGKILL`.

## Human Review Loop

The `coding_machine_cli` human review pattern works unchanged:

```yaml
states:
  work:
    agent: coder
    input:
      task: "{{ context.task }}"
      resume_session: "{{ context.session_id }}"
    output_to_context:
      result: "{{ output.result }}"
      session_id: "{{ output.session_id }}"
    transitions:
      - to: human_review

  human_review:
    action: human_review
    transitions:
      - condition: "context.human_approved == true"
        to: done
      - to: work
```

When the human provides feedback, the `human_review` hook sets
`context.task` to the feedback text. The next `work` iteration uses
`--resume` to continue the conversation. The Claude Code session maintains
full history, so the model sees the prior work plus the new instruction.

## Reference: Existing PiAgentBridgeAdapter

The Claude Code adapter follows the same structure as
`PiAgentBridgeAdapter` (`flatmachines/adapters/pi_agent_bridge.py`).
Key differences:

| Aspect | PiAgentBridgeAdapter | ClaudeCodeAdapter |
|--------|---------------------|-------------------|
| Transport | stdin JSON → stdout JSON | CLI args → stdout NDJSON |
| Duration | Short-lived (~seconds) | Long-running (~minutes) |
| Streaming | None (wait for completion) | Line-by-line NDJSON |
| Session | Stateless | Stateful (`--resume`) |
| Tools | External (caller defines) | Internal (CLI built-ins) |
| Output | Single JSON blob | Event stream + final result |
| Hook events | None | tool_calls + tool_result from stream |

Structurally, both adapters:
1. Have an `Adapter` class with `type_name` and `create_executor()`
2. Have an `Executor` class holding config, implementing `execute()`
3. Spawn a subprocess with specific args
4. Parse stdout into `AgentResult`

The Claude Code adapter adds stream parsing and session management.

## Comparison with Existing Examples

### vs. `coding_agent_cli` (standalone ToolLoopAgent)

| Aspect | ToolLoopAgent | Claude Code Adapter |
|--------|--------------|---------------------|
| LLM control | FlatAgent via litellm | Claude Code CLI |
| Tool control | Python ToolProvider | CLI built-in tools |
| Loop control | ToolLoopAgent | CLI internal loop |
| Tool impls | Python functions (tools.py) | CLI built-ins |
| Guardrails | Guardrails dataclass | `--max-budget-usd`, `--allowed-tools` |
| Steering | SteeringProvider callback | Not available mid-session |
| Cost tracking | AggregateUsage | CLI `total_cost_usd` |

### vs. `coding_machine_cli` (FlatMachine with tool_loop)

| Aspect | Machine tool_loop | Claude Code Adapter |
|--------|------------------|---------------------|
| State config | `tool_loop: { max_turns: 30 }` | No tool_loop (plain agent call) |
| Hook: on_tool_calls | Machine's internal loop | CLI stream parsing |
| Hook: on_tool_result | Machine's internal loop | CLI stream parsing |
| Human review | `action: human_review` | Same pattern, uses `--resume` |
| Message chain | `_tool_loop_chain` in context | CLI session (server-side) |

## Cache Economics

| Turn | Operation | cache_read | cache_create | Cost |
|------|-----------|-----------|-------------|------|
| 1 | `--session-id` (new) | ~14,180 | ~958 | $0.0132 |
| 2 | `--resume` | ~14,180 | ~972 | $0.0134 |
| 3+ | `--resume` | ~14,180 | ~1K | ~$0.013 |

Without resume (new session each state): each turn pays ~$0.013+ for cache
creation. With resume: cache read is free (90% discount on cached tokens).
For a 5-state machine, resume saves roughly 4× the cache creation cost.

**Important:** Sessions are stored **locally** as JSONL files at
`~/.claude/projects/<cwd-slug>/<session-id>.jsonl`. They are NOT persisted
server-side. If the file is deleted, `--resume` fails. This means:

- Sessions cannot be resumed from a different machine unless the JSONL file
  is copied over.
- `--no-session-persistence` disables file creation (the session works for
  one invocation but can't be resumed).
- The adapter must ensure the working directory is consistent across states
  so the session file lands in the same `projects/<cwd-slug>/` directory.

## Concurrency

Multiple `claude -p` processes run safely in parallel with different session
IDs. Tested with 2 concurrent processes — both completed successfully with
independent results and no file locking conflicts.

## Test Strategy

### Unit Tests (no CLI needed)

- **Arg builder:** Config dict → CLI args array. Cover all config keys,
  resume vs new session, working_dir, json_schema serialization.
- **Stream parser:** Feed recorded NDJSON lines → verify hook calls and
  final AgentResult. Use captured streams from real sessions as fixtures.
- **Result mapper:** CLI result JSON → AgentResult fields. Cover success,
  error, structured output, rate limit info.
- **Error handling:** Non-zero exit + stderr → AgentResult with error.
  Malformed JSON lines → skipped. Timeout → SIGTERM/SIGKILL sequence.

### Integration Tests (requires `claude` binary)

- **Simple task:** `claude -p "say hi"` → AgentResult with content.
- **Tool use:** `claude -p "read /tmp/test.txt"` → verify on_tool_calls
  and on_tool_result hooks fire.
- **Session resume:** Turn 1 sets name, Turn 2 recalls → verify context.
- **Structured output:** `--json-schema` → verify `output` dict populated.
- **Concurrent sessions:** Two simultaneous executions → both succeed.
- **Error recovery:** Resume nonexistent session → AgentResult with error.

### Mock Strategy

Record NDJSON streams from real CLI sessions into fixture files. Replay
them in unit tests by replacing the subprocess with a line-by-line reader
over the fixture file. No need for a mock `claude` binary.

## TOS Compliance

This adapter drives the Claude Code CLI as a subprocess — the same way a
human would use it, but automated. It does **not**:

- Proxy API calls through Claude's subscription
- Extract or reuse API keys from the CLI
- Bypass authentication or billing

It **does**:
- Invoke the installed `claude` binary with documented CLI flags
- Parse the documented output formats (`--output-format json/stream-json`)
- Use session management (`--session-id`, `--resume`) as documented
- Respect permission modes and cost controls

# Tool Use Implementation Handoff

> **Design doc:** [TOOL_USE.md](./TOOL_USE.md) — read this first for full context  
> **Branch with prototype:** `origin/tool-use-flatagent` — cherry-pick from here  
> **Date:** 2026-03-01

---

## What You're Building

A machine-driven tool loop that works across agent adapters (FlatAgent, pi-agent, smolagents). The machine calls the agent, gets back tool_calls, executes tools via a `ToolProvider`, feeds results back, and repeats — with a checkpoint, hook, and conditional transition evaluation after **every individual tool call**.

Two layers:
1. **flatagents standalone** — `ToolProvider` protocol + `ToolLoopAgent` convenience wrapper (branch has most of this)
2. **flatmachines orchestrated** — `_execute_tool_loop` in `FlatMachine` with per-tool-call hooks/checkpoints/transitions

---

## Implementation Steps

### Step 1: ToolProvider protocol in flatagents

**Create** `sdk/python/flatagents/flatagents/tools.py`

This is the shared tool execution interface used by both layers. Contains:
- `ToolResult` dataclass (`content: str`, `is_error: bool`)
- `ToolProvider` protocol (`execute_tool()`, `get_tool_definitions()`)
- `SimpleToolProvider` class — wraps `List[Tool]` into a `ToolProvider`

The `ToolResult` here replaces the one in `tool_loop.py` on the branch. Same shape, single source.

**Reference:** Design doc § "ToolProvider Protocol (lives in flatagents)"

**Export from** `sdk/python/flatagents/flatagents/__init__.py`

---

### Step 2: Cherry-pick FlatAgent.call() changes from branch

**Branch:** `origin/tool-use-flatagent`  
**Commits:** `4d2f73c` and `7265e65`

Changes to cherry-pick into these files on `main`:

**`sdk/python/flatagents/flatagents/baseagent.py`** (line 667: `class AgentResponse`)
- Add `rendered_user_prompt: Optional[str] = None` field to `AgentResponse`

**`sdk/python/flatagents/flatagents/flatagent.py`** (line 647: `async def call(`)
- Add `tools: Optional[List[Dict[str, Any]]] = None` parameter to `call()`
- When `tools` is provided: skip MCP discovery, skip `tools_prompt` rendering, pass tools directly to LLM params, skip JSON mode (`response_format`)
- Set `rendered_user_prompt` on the returned `AgentResponse`
- Same changes to `call_sync()` at bottom of file

The branch diff is surgical — look at the `git diff` for `flatagent.py`, it's clean and shows exactly what changed. The key logic fork:

```python
if tools is not None:
    _external_tools = tools
    _mcp_tools = []
    tools_prompt = ""
else:
    _mcp_tools = self._discover_tools()
    _external_tools = None
    tools_prompt = self._render_tool_prompt(_mcp_tools)
```

---

### Step 3: Bring over ToolLoopAgent from branch

**Branch file:** `sdk/python/flatagents/flatagents/tool_loop.py` (398 lines)  
**Branch test:** `sdk/python/tests/unit/test_tool_loop.py` (625 lines)

Bring these over as-is, then adapt:
- Import `ToolResult` from `flatagents.tools` instead of defining it locally
- `ToolLoopAgent.__init__` should accept both `tools: List[Tool]` (convenience, wraps in `SimpleToolProvider`) and `tool_provider: ToolProvider` (direct)
- Keep `Tool` dataclass as a convenience — it has `execute` callable on it
- `ToolLoopAgent._execute_tool` delegates to the provider

The test file is comprehensive — 625 lines covering: complete loops, guardrails (max_turns, max_tool_calls, timeout, cost), denied/allowed tools, error handling (tool exceptions, tool timeout, unknown tools, LLM errors), steering injection, usage aggregation, and call argument verification.

**Export from** `sdk/python/flatagents/flatagents/__init__.py` — the branch already has the export additions.

---

### Step 4: Add tool_calls and rendered_user_prompt to AgentResult

**File:** `sdk/python/flatmachines/flatmachines/agents.py` (line 79: `class AgentResult`)

Add two fields:

```python
@dataclass
class AgentResult:
    # ... existing fields ...
    tool_calls: Optional[List[Dict[str, Any]]] = None      # NEW
    rendered_user_prompt: Optional[str] = None               # NEW
```

`tool_calls` format: `[{"id": "call_abc", "name": "read_file", "arguments": {"path": "x"}}, ...]`  
Plain dicts — JSON-serializable, cross-process safe.

Also update `coerce_agent_result` (same file) to map these fields from dicts.

---

### Step 5: Add execute_with_tools to AgentExecutor and implement in FlatAgentExecutor

**File:** `sdk/python/flatmachines/flatmachines/agents.py` (line 125: `class AgentExecutor`)

Add method to protocol:

```python
class AgentExecutor(Protocol):
    async def execute(self, input_data, context=None) -> AgentResult: ...

    async def execute_with_tools(
        self,
        input_data: Dict[str, Any],
        tools: List[Dict[str, Any]],
        messages: Optional[List[Dict[str, Any]]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> AgentResult:
        raise NotImplementedError
```

**File:** `sdk/python/flatmachines/flatmachines/adapters/flatagent.py` (line 57: `class FlatAgentExecutor`)

Implement `execute_with_tools`:

```python
async def execute_with_tools(self, input_data, tools, messages=None, context=None):
    response = await self._agent.call(tools=tools, messages=messages, **input_data)
    # Same mapping logic as execute(), plus:
    # - Map response.tool_calls → AgentResult.tool_calls (list of dicts)
    # - Map response.rendered_user_prompt → AgentResult.rendered_user_prompt
```

The tool_calls mapping needs to convert `ToolCall` objects (from `baseagent.py` line 551) to plain dicts:
```python
tool_calls = None
if response.tool_calls:
    tool_calls = [
        {"id": tc.id, "name": tc.tool, "arguments": tc.arguments}
        for tc in response.tool_calls
    ]
```

**Important:** Factor out the shared response→AgentResult mapping from `execute()` into a helper method. `execute_with_tools` uses the same mapping plus the two new fields.

**Future adapters** (not in this PR):
- `PiAgentBridgeExecutor` (`sdk/python/flatmachines/flatmachines/adapters/pi_agent_bridge.py`) — extend JSON protocol with `"mode": "single_call"`, `"tools"`, `"messages"`
- `SmolagentsExecutor` (`sdk/python/flatmachines/flatmachines/adapters/smolagents.py`) — use lower-level smolagents API

---

### Step 6: Update specs

**File:** `flatagent.d.ts` — add `ToolDefinition` interface and `tools` field on `AgentData`:

```typescript
export interface AgentData {
  // ... existing fields ...
  tools?: ToolDefinition[];
}

export interface ToolDefinition {
  type: "function";
  function: {
    name: string;
    description?: string;
    parameters?: Record<string, any>;
  };
}
```

**File:** `flatmachine.d.ts` — expand `tool_loop` on `StateDefinition` and add `ToolLoopStateConfig`:

```typescript
export interface StateDefinition {
  // ... existing fields ...
  tool_loop?: boolean | ToolLoopStateConfig;  // was: tool_loop?: boolean
}

export interface ToolLoopStateConfig {
  max_tool_calls?: number;
  max_turns?: number;
  allowed_tools?: string[];
  denied_tools?: string[];
  tool_timeout?: number;
  total_timeout?: number;
  max_cost?: number;
}
```

**Also update** the copies in:
- `sdk/python/flatagents/flatagents/assets/flatagent.d.ts`
- `sdk/python/flatagents/flatagents/assets/flatmachine.d.ts`
- `sdk/python/flatmachines/flatmachines/assets/flatagent.d.ts`
- `sdk/python/flatmachines/flatmachines/assets/flatmachine.d.ts`
- `assets/flatagent.d.ts`, `assets/flatmachine.d.ts`
- `sdk/js/schemas/flatagent.d.ts`, `sdk/js/schemas/flatmachine.d.ts`

Or run the generate script if one exists: `scripts/generate-spec-assets.ts` (referenced in spec comments).

---

### Step 7: Add hooks to MachineHooks

**File:** `sdk/python/flatmachines/flatmachines/hooks.py` (line 29: `class MachineHooks`)

Add two methods with default no-op implementations:

```python
def on_tool_calls(self, state_name: str, tool_calls: List[Dict[str, Any]], context: Dict[str, Any]) -> Dict[str, Any]:
    """Before tool execution. Fires once per LLM response. Can set _abort_tool_loop or _skip_tools."""
    return context

def on_tool_result(self, state_name: str, tool_result: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """After EACH tool execution. Fires per tool call. Can set _abort_tool_loop."""
    return context
```

Note the naming: `on_tool_calls` (plural) fires once per LLM response before the batch. `on_tool_result` (singular) fires after each individual tool execution.

Also add `get_tool_provider`:

```python
def get_tool_provider(self, state_name: str) -> Optional["ToolProvider"]:
    """Return tool provider for a state. None = use machine default."""
    return None
```

**Also update:** `CompositeHooks`, `WebhookHooks`, and `LoggingHooks` in the same file to handle the new methods.

---

### Step 8: Implement _execute_tool_loop in FlatMachine

**File:** `sdk/python/flatmachines/flatmachines/flatmachine.py`

This is the core implementation. Key insertion points:

**Line 958** (`_execute_state`): Add tool_loop branch before the existing agent execution block:

```python
# In _execute_state, section "4. Handle 'agent'":
agent_name = state.get('agent')
if agent_name:
    if state.get('tool_loop'):
        context, output = await self._execute_tool_loop(state_name, state, agent_name, context)
        # Apply output_to_context (same as existing agent block)
    else:
        # ... existing single-call agent logic unchanged ...
```

**New method `_execute_tool_loop`**: ~120 lines. Full pseudocode is in the design doc § "Execution Flow Inside `_execute_state`". Key behaviors:

1. Parse guardrails from `tool_loop` config — **render through Jinja2** via `_render_guardrail` helper
2. Check adapter supports `execute_with_tools` — raise `RuntimeError` if not
3. Resolve `ToolProvider` from hooks (`get_tool_provider`) or machine constructor arg
4. Resolve tool definitions: merge `ToolProvider.get_tool_definitions()` with agent YAML `data.tools`
5. Main loop:
   - Guardrail checks (timeout, max_turns, max_cost)
   - Call `executor.execute_with_tools(input_data, tools, messages, context)`
   - On first turn: seed chain with `rendered_user_prompt`
   - Build assistant message, append to chain
   - If `finish_reason != "tool_use"`: break (natural completion)
   - Fire `on_tool_calls` hook (once, sees full batch)
   - **For each tool call individually:**
     - Skip if in `_skip_tools`
     - Execute via `ToolProvider.execute_tool()`
     - Append tool result to chain
     - Fire `on_tool_result` hook
     - Checkpoint with `tool_loop_state`
     - Evaluate conditional transitions (`_find_conditional_transition`)
     - If transition matches or `_abort_tool_loop`: break inner loop
   - Inject `_steering_messages` if set by hook
6. Build output dict with `_tool_calls_count`, `_tool_loop_turns`, `_tool_loop_cost`, `_tool_loop_stop`

**New method `_find_conditional_transition`**: Evaluates only transitions with a `condition` field. Unconditional transitions are skipped — they're the natural exit path.

```python
def _find_conditional_transition(self, state_name, context):
    for transition in self.states.get(state_name, {}).get('transitions', []):
        condition = transition.get('condition')
        if not condition:
            continue  # Skip unconditional
        if self._evaluate_condition(condition, context):
            return transition.get('to')
    return None
```

**New method `_render_guardrail`**: Renders a config value through Jinja2 if it's a string template, then casts to target type.

**New helper `_build_assistant_message`**: Builds an assistant message dict from `AgentResult` for chain continuation. Include `tool_calls` in OpenAI format if present.

**Modify `execute()` loop** (line 1182): After `_execute_state` returns, check for mid-loop transition override:

```python
if '_tool_loop_next_state' in context:
    next_state = context.pop('_tool_loop_next_state')
    context.pop('_tool_loop_stop', None)
else:
    next_state = self._find_next_state(current_state, context)
```

**Modify `__init__`**: Accept `tool_provider` constructor argument. Store as `self._tool_provider`.

**New method `_resolve_tool_provider`**: Check hooks first (`get_tool_provider`), fall back to constructor arg.

**New method `_resolve_tool_definitions`**: Merge provider definitions with agent YAML tools. Agent YAML tools come from the resolved agent config's `data.tools` field.

---

### Step 9: Add tool_loop_state to MachineSnapshot

**File:** `sdk/python/flatmachines/flatmachines/persistence.py` (line 17: `class MachineSnapshot`)

Add field:

```python
@dataclass
class MachineSnapshot:
    # ... existing fields ...
    tool_loop_state: Optional[Dict[str, Any]] = None
```

Contents when set: `{"chain": [...], "turns": int, "tool_calls_count": int, "loop_cost": float}`

The chain contains `{"role": "user"|"assistant"|"tool", "content": "...", ...}` dicts — all JSON-serializable.

**Modify `_save_checkpoint`** in `flatmachine.py` to accept and pass through `tool_loop_state`:

```python
async def _save_checkpoint(self, event, state_name, step, context,
                           output=None, waiting_channel=None,
                           tool_loop_state=None):  # NEW param
```

**Modify `_execute_tool_loop`** resume path: On resume, if `snapshot.tool_loop_state` exists, restore `chain`, `turns`, `tool_calls_count`, `loop_cost` from it and continue the loop.

---

### Step 10: Tests

**New file:** `sdk/python/tests/unit/test_tool_loop_machine.py`

Test cases needed:
- Basic tool loop: agent calls tool → gets result → responds (mock agent + mock provider)
- Multi-round: 3 rounds of tool calls before completion
- Guardrails: max_turns, max_tool_calls, max_cost, total_timeout
- Per-tool-call hooks: `on_tool_calls` fires once per LLM response, `on_tool_result` fires per tool
- Per-tool-call checkpoints: verify checkpoint saved after each tool execution
- Mid-loop conditional transition: hook sets context flag → conditional transition fires mid-batch
- Unconditional transition NOT firing mid-loop (only on natural exit)
- `_abort_tool_loop` from hook stops the loop
- `_skip_tools` from hook skips specific tool calls
- `_steering_messages` injection
- Jinja2 guardrail rendering: `max_cost: "{{ context.budget }}"` 
- `_tool_loop_next_state` override in execute loop
- Non-capable adapter → RuntimeError
- Resume from checkpoint with `tool_loop_state`
- Cost tracking: `loop_cost` local + `total_cost` machine-wide

Pattern: mock the agent with `AsyncMock`, mock the `ToolProvider`, use `MemoryBackend` for persistence. See existing test patterns in `sdk/python/tests/unit/test_helloworld_machine.py` and the branch's `test_tool_loop.py`.

---

## Key File Reference

| File | What's There | What Changes |
|------|-------------|--------------|
| `sdk/python/flatagents/flatagents/tools.py` | Does not exist | **CREATE** — ToolProvider protocol, ToolResult, SimpleToolProvider |
| `sdk/python/flatagents/flatagents/baseagent.py:667` | `AgentResponse` dataclass | Add `rendered_user_prompt` field |
| `sdk/python/flatagents/flatagents/flatagent.py:647` | `call()` method | Add `tools` param, conditional MCP skip, set `rendered_user_prompt` |
| `sdk/python/flatagents/flatagents/tool_loop.py` | Does not exist on main | **CREATE** from branch, adapt to use `ToolProvider` |
| `sdk/python/flatagents/flatagents/__init__.py` | Package exports | Add new exports |
| `sdk/python/flatmachines/flatmachines/agents.py:79` | `AgentResult` dataclass | Add `tool_calls`, `rendered_user_prompt` fields |
| `sdk/python/flatmachines/flatmachines/agents.py:125` | `AgentExecutor` protocol | Add `execute_with_tools` method |
| `sdk/python/flatmachines/flatmachines/adapters/flatagent.py:57` | `FlatAgentExecutor` | Implement `execute_with_tools`, map tool_calls |
| `sdk/python/flatmachines/flatmachines/hooks.py:29` | `MachineHooks` base class | Add `on_tool_calls`, `on_tool_result`, `get_tool_provider` |
| `sdk/python/flatmachines/flatmachines/flatmachine.py:958` | `_execute_state` | Add tool_loop branch |
| `sdk/python/flatmachines/flatmachines/flatmachine.py:572` | `_find_next_state` | Add sibling `_find_conditional_transition` |
| `sdk/python/flatmachines/flatmachines/flatmachine.py:1182` | `execute()` main loop | Handle `_tool_loop_next_state` |
| `sdk/python/flatmachines/flatmachines/persistence.py:17` | `MachineSnapshot` | Add `tool_loop_state` field |
| `flatagent.d.ts` | Spec (no tools) | Add `ToolDefinition`, `tools` on `AgentData` |
| `flatmachine.d.ts:372` | `tool_loop?: boolean` | Expand to `boolean \| ToolLoopStateConfig` |

## Branch Reference

```
origin/tool-use-flatagent
```

Two commits:
- `4d2f73c` — `ToolLoopAgent` + tool loop types + tests (the bulk)
- `7265e65` — `FlatAgent.call()` changes for cross-provider tool schemas

Key files on branch to cherry-pick / adapt:
- `sdk/python/flatagents/flatagents/tool_loop.py` (398 lines) — the standalone loop
- `sdk/python/tests/unit/test_tool_loop.py` (625 lines) — thorough test suite
- `sdk/python/flatagents/flatagents/baseagent.py` diff — `rendered_user_prompt` on `AgentResponse`
- `sdk/python/flatagents/flatagents/flatagent.py` diff — `tools` param on `call()`

---

## Critical Design Details

### Per-tool-call, not per-round

When the LLM returns `[tool_A, tool_B, tool_C]`, the machine executes them **one at a time**, with checkpoint + `on_tool_result` hook + conditional transition evaluation after each:

```
LLM response: [tool_A, tool_B, tool_C]
  ├─ on_tool_calls hook (once, sees all 3)
  ├─ execute tool_A → on_tool_result → checkpoint → evaluate transitions
  ├─ execute tool_B → on_tool_result → checkpoint → evaluate transitions
  └─ execute tool_C → on_tool_result → checkpoint → evaluate transitions
```

A hook can abort mid-batch. A transition can fire mid-batch. You can resume from any checkpoint.

### Conditional transitions only mid-loop

`_find_conditional_transition` skips transitions without a `condition` field. The unconditional fallback (`- to: done`) is the natural exit — it fires only when the loop completes (LLM stops calling tools or guardrails fire). Without this, every tool_loop state with a fallback transition would exit after the first tool call.

### Jinja2 in guardrails

All `ToolLoopStateConfig` values pass through `_render_template` at loop start. This enables `max_cost: "{{ context.approved_budget }}"`. Use a `_render_guardrail(value, variables, target_type)` helper that renders strings, casts to target type, and passes through numbers unchanged.

### Cross-adapter via execute_with_tools

`_execute_tool_loop` calls `executor.execute_with_tools()`, not FlatAgent directly. This means:
- FlatAgentExecutor works now (implements the method)
- Pi/smolagents adapters can implement later without changing the machine
- Non-capable adapters get a clear RuntimeError

Check capability with `hasattr(executor, 'execute_with_tools')` and try/except `NotImplementedError`.

### ToolProvider is in flatagents, not flatmachines

`from flatagents.tools import ToolProvider, ToolResult` — both packages use the same protocol. FlatMachine imports it from flatagents. This keeps standalone flatagents tool use complete without needing flatmachines.

### _skip_tools uses tool_call IDs or names

The `on_tool_calls` hook can set `context['_skip_tools'] = ['call_id_123']` (by ID) or `context['_skip_tools'] = ['write_file']` (by name). The loop checks both. Skipped tools get a "skipped by policy" message appended to the chain so the LLM knows.

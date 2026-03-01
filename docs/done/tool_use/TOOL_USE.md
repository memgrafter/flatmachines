# Tool Use Design — FlatAgents + FlatMachines

> **Status:** Draft  
> **Branch reference:** `origin/tool-use-flatagent` (existing prototype)  
> **Date:** 2026-03-01

## Problem

The `tool-use-flatagent` branch adds a `ToolLoopAgent` class in flatagents that runs the entire tool-call loop as an opaque inner loop. It works, but flatmachines can't observe or intervene between tool calls — no hooks fire, no checkpointing, no transition evaluation mid-loop.

We want both:
1. **FlatAgents standalone** — `pip install flatagents` gives you tool use without needing flatmachines.
2. **FlatMachines orchestrated** — the tool loop runs as state transitions inside a machine, with hooks between every tool call, checkpointing for crash recovery, transition evaluation for conditional branching (including human-in-the-loop via `wait_for`).

## Design Principle

**A tool call is a state step.** The LLM says "call these tools" → each tool executes → checkpoint → hooks fire → transitions evaluate. This maps onto the existing machine execution model without new abstractions.

Checkpointing and hooks fire after **every individual tool call**, not after each round. This gives full rewind granularity — you can resume from the exact point where tool call #7 happened, inspect the state, replay from there or let the LLM diverge.

---

## Layer 1: FlatAgents (Single-Call Primitives)

FlatAgent stays a single LLM call. No loop. But it needs to support the mechanics of tool use: accepting tool definitions, returning tool call requests, continuing from a message chain.

### ToolProvider Protocol (lives in flatagents)

`ToolProvider` is a **flatagents concept**, not a flatmachines concept. Both `ToolLoopAgent` (standalone) and `FlatMachine` (orchestrated) use the same protocol for tool execution.

```python
# flatagents/tools.py

from typing import Any, Dict, List, Protocol
from dataclasses import dataclass


@dataclass
class ToolResult:
    """Result from executing a tool."""
    content: str
    is_error: bool = False


class ToolProvider(Protocol):
    """
    Provides tool definitions and execution.
    
    Used by both ToolLoopAgent (standalone) and FlatMachine (orchestrated).
    """
    
    async def execute_tool(
        self,
        name: str,
        tool_call_id: str,
        arguments: Dict[str, Any],
    ) -> ToolResult:
        """Execute a tool and return its result."""
        ...
    
    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """
        Return tool definitions in OpenAI function-calling format.
        
        Optional — if the agent YAML already has `tools:` defined,
        this method doesn't need to return anything. If it does,
        its definitions are merged with (and override) the YAML ones.
        """
        ...


class SimpleToolProvider:
    """Build a ToolProvider from individual Tool objects."""
    
    def __init__(self, tools: List["Tool"]):
        self._tools = {t.name: t for t in tools}
    
    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in self._tools.values()
        ]
    
    async def execute_tool(self, name, tool_call_id, arguments) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(content=f"Unknown tool: {name}", is_error=True)
        return await tool.execute(tool_call_id, arguments)
```

`FlatMachine` imports `ToolProvider` from flatagents. One concept, both layers.

### Changes to `FlatAgent.call()`

```python
# flatagents/flatagent.py

async def call(
    self,
    tool_provider: Optional["MCPToolProvider"] = None,
    messages: Optional[List[Dict[str, Any]]] = None,
    tools: Optional[List[Dict[str, Any]]] = None,       # NEW
    **input_data
) -> "AgentResponse":
```

**New `tools` parameter:** A list of tool definitions in OpenAI function-calling format. When provided, these are passed directly to the LLM — MCP discovery is skipped. This is the seam that lets callers (ToolLoopAgent, FlatMachine, or user code) control what tools are available.

**Behavior changes when `tools` is provided:**
- Skip MCP tool discovery
- Skip `tools_prompt` rendering (caller's tools aren't in the MCP template)
- Pass `tools` directly in LLM call params
- Skip JSON mode (`response_format`) since tool-use and JSON mode conflict
- Parse `tool_calls` from LLM response as before (existing MCP parsing works)

**Message chain continuation (`messages` param — already exists on main):** When `messages` is provided, the call continues from that history. Combined with `tools`, this enables multi-turn tool use: the caller manages the message chain, FlatAgent handles the LLM call.

### Changes to `AgentResponse`

```python
# flatagents/baseagent.py

@dataclass
class AgentResponse:
    content: Optional[str] = None
    output: Optional[Dict[str, Any]] = None
    tool_calls: Optional[List[ToolCall]] = None    # Already exists
    raw_response: Optional[Any] = None
    usage: Optional[UsageInfo] = None
    rate_limit: Optional[RateLimitInfo] = None
    finish_reason: Optional[FinishReason] = None   # TOOL_USE already in enum
    error: Optional[ErrorInfo] = None
    rendered_user_prompt: Optional[str] = None      # NEW
```

**New `rendered_user_prompt`:** The rendered user prompt from the first call. The tool loop needs this to seed the message chain — the first turn renders templates from `input_data`, and subsequent turns pass the chain without re-rendering.

### Changes to `flatagent.d.ts` (Schema)

```typescript
export interface AgentData {
  // ... existing fields ...
  tools?: ToolDefinition[];        // NEW: static tool definitions
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

The `tools` field in the agent YAML declares what tools this agent can use. This is metadata — tool *execution* is handled by the caller (ToolLoopAgent or FlatMachine). The agent just tells the LLM these tools exist.

```yaml
# agent.yml
spec: flatagent
spec_version: "1.1.1"
data:
  name: coder
  model: { profile: "smart" }
  system: "You are a coding assistant. Use tools to read and write files."
  user: "{{ input.task }}"
  tools:
    - type: function
      function:
        name: read_file
        description: "Read a file from the filesystem"
        parameters:
          type: object
          properties:
            path: { type: string, description: "File path" }
          required: [path]
    - type: function
      function:
        name: write_file
        description: "Write content to a file"
        parameters:
          type: object
          properties:
            path: { type: string }
            content: { type: string }
          required: [path, content]
```

### `ToolLoopAgent` — Standalone Convenience

For users who want tool use without flatmachines. This is the loop from the branch, kept as a convenience wrapper.

```python
# flatagents/tool_loop.py

class ToolLoopAgent:
    """
    Runs the LLM tool-call loop without FlatMachines.
    
    Composes with FlatAgent: one FlatAgent instance handles each LLM call,
    ToolLoopAgent manages the message chain, tool execution, and guardrails.
    
    For hooks between tool calls, checkpointing, transition evaluation,
    or integration with larger workflows, use a FlatMachine with
    tool_loop on the agent state instead.
    """
    
    def __init__(
        self,
        agent: FlatAgent,
        tool_provider: ToolProvider,              # Shared protocol
        guardrails: Optional[Guardrails] = None,
        steering: Optional[SteeringProvider] = None,
    ):
        ...
    
    async def run(self, **input_data) -> ToolLoopResult:
        """Execute the tool loop to completion."""
        ...
```

**This is identical to what's on the branch**, adapted to use `ToolProvider` instead of `List[Tool]`. The `SimpleToolProvider` wraps `Tool` objects for backward compatibility. The key types (`Tool`, `ToolResult`, `Guardrails`, `StopReason`, `ToolLoopResult`, `AggregateUsage`) stay as-is. The test suite from the branch (`test_tool_loop.py`) covers it thoroughly.

The `ToolLoopAgent` constructor also accepts `List[Tool]` for convenience — it wraps them in a `SimpleToolProvider` internally.

**What ToolLoopAgent gives you:**
- Guardrails: max_turns, max_tool_calls, tool_timeout, total_timeout, max_cost
- Tool allow/deny lists
- Steering message injection between rounds
- Usage aggregation across turns
- Structured stop reasons

**What it doesn't give you (use FlatMachine for these):**
- Hooks between tool calls
- Checkpointing / crash recovery
- Transition evaluation mid-loop
- Human-in-the-loop (`wait_for`)
- Composition with other states/machines

> **Note:** The per-turn mutation callback (`on_turn` / `TurnContext`) is a proposed
> extension to `ToolLoopAgent` for internal use. See
> [tool_use_on_turn.md](./tool_use_on_turn.md) for the design.

---

## Layer 2: FlatMachines (Orchestrated Tool Loop)

A state with `agent` + `tool_loop` tells the machine to run the tool-call loop as repeated executions of that state, with the full hook suite and transition evaluation between every tool call.

### Cross-Adapter Tool Loop via `execute_with_tools`

The tool loop works across adapter boundaries. The `AgentExecutor` protocol gains a new method:

```python
# flatmachines/agents.py

@dataclass
class AgentResult:
    # ... existing fields ...
    tool_calls: Optional[List[Dict[str, Any]]] = None      # NEW
    rendered_user_prompt: Optional[str] = None               # NEW


class AgentExecutor(Protocol):
    """Protocol for running a single agent call."""

    async def execute(
        self,
        input_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> AgentResult:
        ...

    async def execute_with_tools(
        self,
        input_data: Dict[str, Any],
        tools: List[Dict[str, Any]],
        messages: Optional[List[Dict[str, Any]]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> AgentResult:
        """
        Execute a single LLM call with tool definitions and optional
        conversation chain. Used by the machine's tool loop.
        
        Args:
            input_data: Input for template rendering (first call only)
            tools: Tool definitions in OpenAI function-calling format
            messages: Conversation chain for continuation (subsequent calls)
            context: Machine context (read-only, for adapter use)
        
        Returns:
            AgentResult with tool_calls populated if LLM requested tools,
            finish_reason="tool_use" when tools requested,
            rendered_user_prompt on first call for chain seeding.
        """
        raise NotImplementedError

    @property
    def metadata(self) -> Dict[str, Any]:
        ...
```

**`tool_calls` on AgentResult** uses plain dicts for cross-process compatibility:
```python
[{"id": "call_abc", "name": "read_file", "arguments": {"path": "src/main.py"}}, ...]
```

Each adapter implements `execute_with_tools` for its runtime:

| Adapter | Implementation |
|---------|---------------|
| `FlatAgentExecutor` | `self._agent.call(tools=tools, messages=messages, **input_data)` — maps `AgentResponse.tool_calls` to `AgentResult.tool_calls` |
| `PiAgentBridgeExecutor` | Extends JSON protocol: `{"mode": "single_call", "tools": [...], "messages": [...]}` — runner does one LLM call, returns tool_calls |
| `SmolagentsExecutor` | Uses lower-level smolagents API for single-step calls instead of `agent.run()` |

The machine's `_execute_tool_loop` doesn't care what's behind the adapter. It calls `execute_with_tools`, gets back `AgentResult` with `tool_calls`, executes those tools via `ToolProvider`, appends results to the chain, and calls again. **The LLM decides what to call, the machine decides how to execute it.**

If `tool_loop` is set on a state whose adapter does not implement `execute_with_tools`, the machine raises a clear runtime error:

```
RuntimeError: Agent 'coder' (adapter 'smolagents') does not support
machine-driven tool loops. Implement execute_with_tools on the adapter
or remove tool_loop from state 'code'.
```

### Schema Addition (`flatmachine.d.ts`)

```typescript
export interface StateDefinition {
  // ... existing fields ...
  tool_loop?: boolean | ToolLoopStateConfig;
}

export interface ToolLoopStateConfig {
  max_tool_calls?: number;     // Total tool calls before forced stop. Default: 50
  max_turns?: number;          // LLM call rounds before forced stop. Default: 20
  allowed_tools?: string[];    // Whitelist (if set, only these execute)
  denied_tools?: string[];     // Blacklist (takes precedence over allowed)
  tool_timeout?: number;       // Per-tool execution timeout in seconds. Default: 30
  total_timeout?: number;      // Total loop timeout in seconds. Default: 600
  max_cost?: number;           // Cost limit in dollars
}
```

`tool_loop: true` uses all defaults. `tool_loop: { max_turns: 5, max_cost: 0.50 }` overrides specific limits.

All `ToolLoopStateConfig` values support Jinja2 templates, rendered at loop start against the current context:

```yaml
tool_loop:
  max_cost: "{{ context.approved_budget }}"
  max_turns: "{{ context.max_iterations }}"
```

### Machine YAML Example

```yaml
spec: flatmachine
spec_version: "1.1.1"

data:
  name: coding-agent
  
  context:
    task: "{{ input.task }}"
    files_modified: []
    total_tool_calls: 0
  
  agents:
    coder: ./coder.yml     # Has tools: defined in its YAML
  
  states:
    start:
      type: initial
      transitions:
        - to: code
    
    code:
      agent: coder
      tool_loop:
        max_turns: 10
        max_cost: 1.00
      input:
        task: "{{ context.task }}"
      output_to_context:
        result: "{{ output.content }}"
        total_tool_calls: "{{ output._tool_calls_count }}"
      transitions:
        - condition: "context.needs_review"
          to: human_review
        - to: done
    
    human_review:
      wait_for: "review/{{ context.task_id }}"
      output_to_context:
        approved: "{{ output.approved }}"
        feedback: "{{ output.feedback }}"
      transitions:
        - condition: "context.approved"
          to: done
        - to: code   # Back to coding with feedback
    
    done:
      type: final
      output:
        result: "{{ context.result }}"
        tool_calls: "{{ context.total_tool_calls }}"
```

### New Hooks

```python
# flatmachines/hooks.py

class MachineHooks:
    # ... all existing hooks unchanged ...
    
    def on_tool_calls(
        self,
        state_name: str,
        tool_calls: List[Dict[str, Any]],
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Called BEFORE tool execution in a tool_loop state.
        
        Fires once per LLM response that contains tool calls.
        `tool_calls` is the list of tool call requests from the LLM.
        
        Use cases:
        - Log/audit what tools the LLM is calling
        - Inject data into context for transition evaluation
        - Set context['_abort_tool_loop'] = True to stop the loop
        - Set context['_skip_tools'] = ['tool_call_id'] to skip specific calls
        
        Args:
            state_name: Current state name
            tool_calls: List of tool call dicts: [{id, name, arguments}, ...]
            context: Current context
            
        Returns:
            Modified context
        """
        return context
    
    def on_tool_result(
        self,
        state_name: str,
        tool_result: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Called AFTER each individual tool execution.
        
        Fires once per tool call — if the LLM requested 3 tools,
        this fires 3 times. A checkpoint is saved after each call,
        enabling rewind to any specific tool execution point.
        
        Use cases:
        - Inspect result for safety/compliance
        - Update context based on tool output (e.g., track modified files)
        - Inject steering messages via context['_steering_messages']
        - Set context['_abort_tool_loop'] = True to stop before next tool
        
        Args:
            state_name: Current state name
            tool_result: Result dict: {tool_call_id, name, arguments, content, is_error}
            context: Current context
            
        Returns:
            Modified context
        """
        return context
```

### Tool Execution: Where Tools Come From

Tools need two things: **definitions** (JSON schema for the LLM) and **executors** (code that runs them). These are separate concerns.

**Definitions** come from the agent's YAML config (`data.tools`) and/or `ToolProvider.get_tool_definitions()`. The LLM sees these in every call.

**Executors** come from `ToolProvider.execute_tool()`. The machine doesn't know how to `read_file` — the provider does.

`ToolProvider` is passed to the machine:

```python
from flatagents.tools import ToolProvider  # Shared protocol from flatagents

machine = FlatMachine(
    config_file="machine.yml",
    hooks=CodingHooks(working_dir="/tmp/workspace"),
    tool_provider=my_tool_provider,   # NEW constructor arg
)
```

Or via hooks (more flexible — different providers per state):

```python
class CodingHooks(MachineHooks):
    def get_tool_provider(self, state_name: str) -> Optional[ToolProvider]:
        """Return tool provider for a state. None = use default."""
        if state_name == "code":
            return self._coding_tools
        return None
```

### Execution Flow Inside `_execute_state`

When the machine encounters `agent` + `tool_loop`:

```python
# flatmachines/flatmachine.py — inside _execute_state

if agent_name and state.get('tool_loop'):
    context, output = await self._execute_tool_loop(
        state_name, state, agent_name, context
    )
```

The `_execute_tool_loop` method:

```python
async def _execute_tool_loop(
    self,
    state_name: str,
    state: Dict[str, Any],
    agent_name: str,
    context: Dict[str, Any],
) -> tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    """
    Execute an agent in tool-loop mode.
    
    Each tool call is an individually checkpointed step:
    1. Call agent via execute_with_tools (with tools + message chain)
    2. If agent returns tool_calls:
       a. Fire on_tool_calls hook (once per LLM response)
       b. For EACH tool call in the response:
          i.   Execute tool via ToolProvider
          ii.  Append result to chain
          iii. Fire on_tool_result hook
          iv.  Checkpoint
          v.   Evaluate conditional transitions — if any match, EXIT
       c. Check guardrails (max_turns, max_tool_calls, cost)
       d. Go to step 1
    3. If agent returns content (no tool_calls):
       a. Loop is done. Return output for normal transition evaluation.
    """
    # Parse guardrails from state config — Jinja2 templates supported
    loop_config = state.get('tool_loop', {})
    if isinstance(loop_config, bool):
        loop_config = {}
    
    variables = {"context": context, "input": context}
    max_turns = self._render_guardrail(loop_config.get('max_turns', 20), variables, int)
    max_tool_calls = self._render_guardrail(loop_config.get('max_tool_calls', 50), variables, int)
    tool_timeout = self._render_guardrail(loop_config.get('tool_timeout', 30.0), variables, float)
    total_timeout = self._render_guardrail(loop_config.get('total_timeout', 600.0), variables, float)
    max_cost = self._render_guardrail(loop_config.get('max_cost'), variables, float)
    allowed_tools = set(loop_config.get('allowed_tools', []))
    denied_tools = set(loop_config.get('denied_tools', []))
    
    # Get agent executor — must support execute_with_tools
    executor = self._get_executor(agent_name)
    if not hasattr(executor, 'execute_with_tools'):
        adapter_type = getattr(executor, '__class__', type(executor)).__name__
        raise RuntimeError(
            f"Agent '{agent_name}' ({adapter_type}) does not support "
            f"machine-driven tool loops. Implement execute_with_tools "
            f"on the adapter or remove tool_loop from state '{state_name}'."
        )
    
    # Get tool provider
    tool_provider = self._resolve_tool_provider(state_name)
    
    # Resolve tool definitions
    # Priority: tool_provider.get_tool_definitions() > agent YAML tools
    tool_defs = self._resolve_tool_definitions(agent_name, tool_provider)
    
    # Build initial input
    input_spec = state.get('input', {})
    variables = {"context": context, "input": context}
    agent_input = self._render_dict(input_spec, variables)
    
    # State for the loop
    chain: List[Dict[str, Any]] = []
    turns = 0
    tool_calls_count = 0
    loop_cost = 0.0
    start_time = time.monotonic()
    last_content = None
    
    while True:
        # --- Guardrail checks ---
        if time.monotonic() - start_time >= total_timeout:
            context['_tool_loop_stop'] = 'timeout'
            break
        if turns >= max_turns:
            context['_tool_loop_stop'] = 'max_turns'
            break
        if max_cost is not None and loop_cost >= max_cost:
            context['_tool_loop_stop'] = 'cost_limit'
            break
        
        # --- Call agent via execute_with_tools ---
        if turns == 0:
            result = await executor.execute_with_tools(
                input_data=agent_input,
                tools=tool_defs,
                messages=None,
                context=context,
            )
        else:
            result = await executor.execute_with_tools(
                input_data={},
                tools=tool_defs,
                messages=chain,
                context=context,
            )
        
        turns += 1
        self._accumulate_agent_metrics(result)
        loop_cost += self._extract_cost(result)
        
        # Update context with loop metadata
        context['_tool_loop_turns'] = turns
        context['_tool_loop_cost'] = loop_cost
        context['_tool_calls_count'] = tool_calls_count
        
        # --- Handle error ---
        if result.error:
            raise RuntimeError(
                f"{result.error.get('type', 'AgentError')}: "
                f"{result.error.get('message', 'unknown')}"
            )
        
        # --- Seed chain on first turn ---
        if turns == 1 and result.rendered_user_prompt:
            chain.append({"role": "user", "content": result.rendered_user_prompt})
        
        # --- Build assistant message and append to chain ---
        assistant_msg = self._build_assistant_message(result)
        chain.append(assistant_msg)
        last_content = result.content
        
        # --- No tool calls = loop complete ---
        if result.finish_reason != "tool_use":
            break
        
        pending_calls = result.tool_calls or []
        
        # --- Guardrail: tool call count ---
        if tool_calls_count + len(pending_calls) > max_tool_calls:
            context['_tool_loop_stop'] = 'max_tool_calls'
            break
        
        # --- HOOK: on_tool_calls (once per LLM response) ---
        context = await self._run_hook(
            'on_tool_calls', state_name, pending_calls, context,
        )
        
        if context.get('_abort_tool_loop'):
            context['_tool_loop_stop'] = 'aborted'
            break
        
        # --- Execute tools ONE AT A TIME with per-tool hooks + checkpoints ---
        skip_tools = set(context.pop('_skip_tools', []))
        
        for tc in pending_calls:
            tc_name = tc.get('name') or tc.get('tool')
            tc_id = tc.get('id')
            tc_args = tc.get('arguments', {})
            
            # Skip if hook requested
            if tc_id in skip_tools or tc_name in skip_tools:
                chain.append({
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "content": f"Tool '{tc_name}' was skipped by policy.",
                })
                continue
            
            # Execute single tool
            tool_result = await self._execute_single_tool(
                tool_provider, tc_name, tc_id, tc_args,
                tool_timeout, allowed_tools, denied_tools,
            )
            tool_calls_count += 1
            
            tool_result_dict = {
                "tool_call_id": tc_id,
                "name": tc_name,
                "arguments": tc_args,
                "content": tool_result.content,
                "is_error": tool_result.is_error,
            }
            
            chain.append({
                "role": "tool",
                "tool_call_id": tc_id,
                "content": tool_result.content,
            })
            
            context['_tool_calls_count'] = tool_calls_count
            
            # --- HOOK: on_tool_result (per tool call) ---
            context = await self._run_hook(
                'on_tool_result', state_name, tool_result_dict, context,
            )
            
            # --- Checkpoint after each tool call ---
            await self._save_checkpoint(
                'tool_call', state_name, self._current_step, context,
                tool_loop_state={
                    "chain": chain,
                    "turns": turns,
                    "tool_calls_count": tool_calls_count,
                    "loop_cost": loop_cost,
                },
            )
            
            # --- Evaluate conditional transitions after each tool call ---
            if context.get('_abort_tool_loop'):
                context['_tool_loop_stop'] = 'aborted'
                break
            
            next_state = self._find_conditional_transition(state_name, context)
            if next_state is not None:
                context['_tool_loop_stop'] = 'transition'
                context['_tool_loop_next_state'] = next_state
                break
        
        # Check if inner loop broke out
        if context.get('_tool_loop_stop'):
            break
        
        # --- Inject steering messages from hook ---
        steering = context.pop('_steering_messages', None)
        if steering:
            for msg in steering:
                chain.append(msg)
    
    # --- Build output ---
    output = {
        "content": last_content,
        "_tool_calls_count": tool_calls_count,
        "_tool_loop_turns": turns,
        "_tool_loop_cost": loop_cost,
        "_tool_loop_stop": context.get('_tool_loop_stop', 'complete'),
    }
    
    # Apply output_to_context mapping
    output_mapping = state.get('output_to_context', {})
    if output_mapping:
        variables = {"context": context, "output": output, "input": context}
        for ctx_key, template in output_mapping.items():
            context[ctx_key] = self._render_template(template, variables)
    
    return context, output
```

### Per-Tool-Call Granularity

Hooks, checkpoints, and transitions fire after **every individual tool call**, not after each round. When the LLM returns `[tool_A, tool_B, tool_C]`:

```
LLM response: [tool_A, tool_B, tool_C]
  ├─ on_tool_calls hook (once, sees all 3)
  ├─ execute tool_A
  │   ├─ on_tool_result hook (tool_A result)
  │   ├─ checkpoint (chain includes tool_A result)
  │   └─ evaluate conditional transitions
  ├─ execute tool_B
  │   ├─ on_tool_result hook (tool_B result)
  │   ├─ checkpoint (chain includes tool_A + tool_B results)
  │   └─ evaluate conditional transitions
  └─ execute tool_C
      ├─ on_tool_result hook (tool_C result)
      ├─ checkpoint (chain includes all 3 results)
      └─ evaluate conditional transitions
```

This enables:
- **Rewind to tool_A:** Resume from that checkpoint, replay tool_B and tool_C, or let the LLM diverge.
- **Abort mid-batch:** `on_tool_result` for tool_A sets `_abort_tool_loop`, tool_B and tool_C are skipped.
- **Transition mid-batch:** tool_A writes to a sensitive path, hook sets `context.needs_approval`, conditional transition fires, loop exits before tool_B.

### Mid-Loop Transition Evaluation

After each tool call, the machine evaluates **conditional transitions only**. Unconditional transitions (no `condition` field) are the natural exit path — they fire only when the loop completes normally (LLM stops calling tools or guardrails fire).

```python
def _find_conditional_transition(
    self,
    state_name: str,
    context: Dict[str, Any],
) -> Optional[str]:
    """Evaluate only conditional transitions. Used mid-tool-loop."""
    state = self.states.get(state_name, {})
    transitions = state.get('transitions', [])
    
    for transition in transitions:
        condition = transition.get('condition')
        to_state = transition.get('to')
        
        if not condition or not to_state:
            continue  # Skip unconditional transitions
        
        if self._evaluate_condition(condition, context):
            return to_state
    
    return None
```

```yaml
states:
  code:
    agent: coder
    tool_loop:
      max_turns: 10
    input:
      task: "{{ context.task }}"
    output_to_context:
      result: "{{ output.content }}"
    transitions:
      # These are checked AFTER EVERY TOOL CALL:
      - condition: "context.needs_approval"
        to: wait_for_approval
      - condition: "context._tool_calls_count > 20"
        to: too_many_tools
      - condition: "context._tool_loop_cost > 0.50"
        to: cost_warning
      # This is the natural exit (only when loop completes):
      - to: review
```

Hooks can set flags that trigger mid-loop transitions:

```python
class SafetyHooks(MachineHooks):
    def on_tool_result(self, state_name, tool_result, context):
        if tool_result['name'] == 'write_file':
            path = tool_result['arguments'].get('path', '')
            if '/etc/' in path or path.startswith('/root'):
                context['needs_approval'] = True  # Triggers transition!
        return context
```

### Handling `_tool_loop_next_state`

When a mid-loop transition fires, the main `execute` loop needs to know:

```python
# In execute(), after _execute_state returns:
if '_tool_loop_next_state' in context:
    next_state = context.pop('_tool_loop_next_state')
    context.pop('_tool_loop_stop', None)
else:
    next_state = self._find_next_state(current_state, context)
```

### Checkpoint & Resume

The tool loop checkpoints after every tool call (`tool_call` event). The checkpoint includes the full tool loop state for resumption:

```python
@dataclass
class MachineSnapshot:
    # ... existing fields ...
    tool_loop_state: Optional[Dict[str, Any]] = None
    # Contains: chain, turns, tool_calls_count, loop_cost
```

On resume:

```python
# In _execute_tool_loop, at the start:
if self._resuming and snapshot.tool_loop_state:
    tls = snapshot.tool_loop_state
    chain = tls['chain']
    turns = tls['turns']
    tool_calls_count = tls['tool_calls_count']
    loop_cost = tls['loop_cost']
    # Continue the loop from where we left off
```

The chain contains role/content/tool_calls dicts — all JSON-serializable. The existing `CheckpointManager._safe_serialize` handles this without changes.

### Guardrail Rendering

`ToolLoopStateConfig` values support Jinja2 templates, rendered at loop start:

```python
def _render_guardrail(self, value, variables, target_type):
    """Render a guardrail value through Jinja2 if it's a template string."""
    if value is None:
        return None
    if isinstance(value, str):
        rendered = self._render_template(value, variables)
        return target_type(rendered)
    return target_type(value)
```

This enables dynamic guardrails from context:

```yaml
code_continued:
  agent: coder
  tool_loop:
    max_cost: "{{ context.approved_budget }}"
    max_turns: "{{ context.remaining_iterations }}"
```

### Cost Tracking

The tool loop maintains its own `loop_cost` counter for guardrail evaluation. The machine's `_accumulate_agent_metrics` is called for each `AgentResult` (existing behavior), so `self.total_cost` includes all calls automatically. No double-counting — `loop_cost` is local to the loop for guardrail checks, `total_cost` is machine-wide for reporting.

---

## Comparison

| Capability | ToolLoopAgent (flatagents) | FlatMachine + tool_loop |
|---|---|---|
| Basic tool-call loop | ✅ | ✅ |
| Guardrails (turns, calls, cost, timeout) | ✅ | ✅ (+ Jinja2 templates) |
| Tool allow/deny lists | ✅ | ✅ |
| Steering messages between rounds | ✅ (callback) | ✅ (hook sets `_steering_messages`) |
| Usage aggregation | ✅ | ✅ (machine-level metrics) |
| Hooks between tool calls | ❌ | ✅ `on_tool_calls`, `on_tool_result` |
| Checkpoint after every tool call | ❌ | ✅ (rewind to any tool call) |
| Transition evaluation per tool call | ❌ | ✅ (conditional transitions) |
| Human-in-the-loop (`wait_for`) | ❌ | ✅ (transition to `wait_for` state) |
| Conditional branching mid-loop | ❌ (stop only) | ✅ (any conditional transition) |
| Error recovery (`on_error`) | ❌ (stop only) | ✅ (machine error handling) |
| Compose with other machines | ❌ | ✅ |
| Works without flatmachines | ✅ | ❌ |
| Cross-adapter (pi, smolagents) | ❌ | ✅ (via `execute_with_tools`) |

---

## Suspend/Resume + Signals: Zero-Process Human-in-the-Loop

> **No implementation changes required for these patterns.** They compose the tool_loop feature (Layer 2 above) with the existing signals, checkpoint/resume, and dispatcher infrastructure. These examples illustrate design motivation and show what becomes possible when tool use lives in flatmachines rather than an opaque inner loop.

The real power of tool_loop-in-a-machine comes from combining three existing features: **checkpoint/resume**, **signals**, and **mid-loop transitions**. Together they enable patterns where a tool-using agent can be suspended — process exits, zero memory, zero compute — and resumed later by a human or external system, with full context preserved.

This is qualitatively different from what `ToolLoopAgent` (standalone) can do. A standalone loop must stay running to stay alive. A machine can checkpoint mid-tool-loop, exit the process entirely, and resume days later from the exact same point in the conversation.

### Pattern 1: Budget Gate

Agent works autonomously until it hits a cost threshold, then suspends for human review. Nothing running while waiting.

```yaml
data:
  name: budget-gated-coder
  
  context:
    task: "{{ input.task }}"
    budget_approved: false
    total_spent: 0.0
  
  agents:
    coder: ./coder.yml
  
  states:
    start:
      type: initial
      transitions:
        - to: code

    code:
      agent: coder
      tool_loop:
        max_turns: 50
        max_cost: 0.50          # Initial budget: 50 cents
      input:
        task: "{{ context.task }}"
      output_to_context:
        result: "{{ output.content }}"
        total_spent: "{{ context.total_spent + output._tool_loop_cost }}"
      transitions:
        # Mid-loop: cost exceeded → ask for more budget
        - condition: "context._tool_loop_stop == 'cost_limit'"
          to: request_budget
        - to: done

    request_budget:
      # Machine checkpoints here and the process EXITS.
      # Zero CPU. Zero memory. Just a row in SQLite.
      wait_for: "budget/{{ context.task_id }}"
      timeout: 86400              # 24 hours to respond
      output_to_context:
        budget_approved: "{{ output.approved }}"
        new_budget: "{{ output.additional_budget }}"
      transitions:
        - condition: "context.budget_approved"
          to: code_continued       # Resume with more budget
        - to: done                 # Human said stop

    code_continued:
      agent: coder
      tool_loop:
        max_cost: "{{ context.new_budget }}"    # Human-approved budget
      input:
        task: "{{ context.task }}"
        feedback: "You ran out of budget. More has been approved. Continue where you left off."
      output_to_context:
        result: "{{ output.content }}"
      transitions:
        - condition: "context._tool_loop_stop == 'cost_limit'"
          to: request_budget       # Can ask again
        - to: done

    done:
      type: final
      output:
        result: "{{ context.result }}"
        total_spent: "{{ context.total_spent }}"
```

The human interaction is completely async:

```python
# Somewhere else — a CLI, a web UI, a Slack bot, cron job, whatever.
# The machine is NOT running. The process that started it is long gone.

from flatmachines import SQLiteSignalBackend

signals = SQLiteSignalBackend("./signals.db")

# Human reviews the work so far and approves more budget
await signals.send("budget/task-42", {
    "approved": True,
    "additional_budget": 2.00,
})

# The trigger backend (file/launchd/systemd) wakes the dispatcher.
# Dispatcher finds the checkpointed machine waiting on "budget/task-42".
# Machine resumes from the exact checkpoint, enters code_continued state.
# Agent picks up where it left off with a fresh budget allocation.
```

**What happens at each stage:**

1. Agent works in `code` state, tools firing, hooks running, checkpointing every tool call.
2. Cost hits $0.50 → `_tool_loop_stop` = `cost_limit` → transition to `request_budget`.
3. `wait_for: "budget/..."` → `WaitingForSignal` raised → checkpoint saved with `waiting_channel` → **process exits**.
4. SQLite has: one checkpoint row (full context, conversation chain), one waiting_channel marker. Zero processes.
5. Human sends signal → trigger fires → dispatcher resumes machine → enters `code_continued` → agent continues.

### Pattern 2: Unexpected Output Recovery

Agent finishes the tool loop but produces something unexpected. Human can inspect, give guidance, and the machine retries with feedback. The full conversation history is preserved in the checkpoint.

```yaml
data:
  name: resilient-writer
  
  context:
    task: "{{ input.task }}"
    attempt: 0
    max_attempts: 3
  
  agents:
    writer: ./writer.yml
  
  states:
    start:
      type: initial
      transitions:
        - to: write

    write:
      agent: writer
      tool_loop:
        max_turns: 10
      input:
        task: "{{ context.task }}"
        feedback: "{{ context.human_feedback }}"
      output_to_context:
        result: "{{ output.content }}"
        has_result: "{{ output.content is not none and output.content | length > 0 }}"
        attempt: "{{ context.attempt + 1 }}"
      transitions:
        - condition: "context.has_result"
          to: validate
        - condition: "context.attempt >= context.max_attempts"
          to: escalate
        - to: request_guidance

    validate:
      # Could be another agent, or just a hook that checks format
      action: validate_output
      transitions:
        - condition: "context.output_valid"
          to: done
        - to: request_guidance

    request_guidance:
      # Agent produced nothing useful, or output failed validation.
      # Suspend and let a human look at what happened.
      wait_for: "guidance/{{ context.task_id }}"
      timeout: 172800            # 48 hours
      output_to_context:
        human_feedback: "{{ output.feedback }}"
        should_retry: "{{ output.retry }}"
      transitions:
        - condition: "context.should_retry"
          to: write              # Try again with human guidance
        - to: done               # Human says it's good enough

    escalate:
      # Too many attempts. Notify and park.
      wait_for: "escalation/{{ context.task_id }}"
      transitions:
        - condition: "context.should_retry"
          to: write
        - to: done

    done:
      type: final
      output:
        result: "{{ context.result }}"
        attempts: "{{ context.attempt }}"
```

### Pattern 3: Safety Review for Dangerous Operations

Agent works freely with read-only tools, but any write operation triggers a review. The tool loop suspends mid-conversation, preserving the full context, while a human reviews the proposed changes.

```yaml
data:
  name: safe-coder

  context:
    task: "{{ input.task }}"
    pending_writes: []
    writes_approved: false

  agents:
    coder: ./coder.yml

  states:
    start:
      type: initial
      transitions:
        - to: code

    code:
      agent: coder
      tool_loop:
        max_turns: 20
      input:
        task: "{{ context.task }}"
      output_to_context:
        result: "{{ output.content }}"
      transitions:
        # Hook sets this when it sees write_file calls
        - condition: "context.pending_writes | length > 0"
          to: review_writes
        - to: done

    review_writes:
      # Show the human what the agent wants to write.
      # The pending_writes list was populated by on_tool_calls hook.
      wait_for: "review/{{ context.task_id }}"
      output_to_context:
        writes_approved: "{{ output.approved }}"
        approved_paths: "{{ output.approved_paths }}"
      transitions:
        - condition: "context.writes_approved"
          to: apply_writes
        - to: done              # Human rejected

    apply_writes:
      agent: coder
      tool_loop:
        max_turns: 5
        allowed_tools: [write_file]   # Only writes now
      input:
        task: "Apply the approved writes."
        approved_paths: "{{ context.approved_paths }}"
      output_to_context:
        result: "{{ output.content }}"
      transitions:
        - to: done

    done:
      type: final
      output:
        result: "{{ context.result }}"
```

The hooks that make this work:

```python
class SafetyHooks(MachineHooks):
    def on_tool_calls(self, state_name, tool_calls, context):
        if state_name == "code":
            pending = []
            for tc in tool_calls:
                if tc['name'] == 'write_file':
                    pending.append({
                        'path': tc['arguments'].get('path'),
                        'content_preview': tc['arguments'].get('content', '')[:200],
                    })
                    # Don't actually execute the write — skip it
                    context.setdefault('_skip_tools', []).append(tc['id'])
            if pending:
                context['pending_writes'] = pending
                # Transition fires after next tool call completes
        return context
```

### Pattern 4: Collaborative Multi-Agent with Handoffs

One agent hits a point where it needs a different specialist. The tool loop suspends, a different agent/machine takes over, and the original can resume with the specialist's output.

```yaml
data:
  name: collaborative-agents

  context:
    task: "{{ input.task }}"
    specialist_needed: ""

  agents:
    generalist: ./generalist.yml
    specialist: ./specialist.yml

  machines:
    deep_research: ./deep_research_machine.yml

  states:
    start:
      type: initial
      transitions:
        - to: work

    work:
      agent: generalist
      tool_loop:
        max_turns: 15
      input:
        task: "{{ context.task }}"
        specialist_findings: "{{ context.specialist_findings }}"
      output_to_context:
        result: "{{ output.content }}"
      transitions:
        # Hook detects the agent requesting specialist help
        - condition: "context.specialist_needed == 'research'"
          to: research
        - condition: "context.specialist_needed != ''"
          to: specialist_review
        - to: done

    research:
      # Hand off to a whole other machine for deep research
      machine: deep_research
      input:
        query: "{{ context.research_query }}"
      output_to_context:
        specialist_findings: "{{ output.findings }}"
        specialist_needed: ""
      transitions:
        - to: work    # Back to generalist with research results

    specialist_review:
      # Or wait for a human specialist
      wait_for: "specialist/{{ context.task_id }}"
      output_to_context:
        specialist_findings: "{{ output.findings }}"
        specialist_needed: ""
      transitions:
        - to: work    # Back to generalist with specialist input

    done:
      type: final
      output:
        result: "{{ context.result }}"
```

### Why This Matters: The Economics of Waiting

The key insight is about **what's running while you wait**.

With a standalone `ToolLoopAgent`, if you want human review you have two bad options:
1. Block the process — hold memory, hold a connection, waste compute.
2. Kill the process — lose all context, start over.

With a FlatMachine tool loop + signals:
- The machine checkpoints the full state: context, conversation chain, tool call history, cost metrics.
- The process exits. Nothing running. A checkpoint row in SQLite (or DynamoDB).
- 10,000 suspended coding agents = 10,000 rows in a database. Zero processes, zero memory, zero cost.
- When the human (or another system) sends a signal, the dispatcher resumes the exact machine from the exact checkpoint.

This makes patterns like "run 1,000 coding tasks, each with a $0.50 budget gate" economically viable. Without suspend/resume, you'd need 1,000 processes sitting idle waiting for approval. With it, you need zero processes plus a few KB of SQLite per task.

---

## Resolved Design Decisions

| # | Question | Decision | Rationale |
|---|----------|----------|-----------|
| 1 | Adapter passthrough | `execute_with_tools` on `AgentExecutor` protocol | Cross-runtime — works for FlatAgent (in-process), pi-agent (Node.js subprocess), smolagents. Each adapter implements for its runtime. |
| 2 | Transition/checkpoint granularity | Per-tool-call | Enables rewind to any specific tool execution point. Hooks fire per tool call. Can replay or diverge from any checkpoint. |
| 3 | `on_turn` callback for ToolLoopAgent | Deferred to [tool_use_on_turn.md](./tool_use_on_turn.md) | Useful for standalone, but not blocking. FlatMachine hooks provide the same power for orchestrated use. |
| 4 | Unconditional transitions mid-loop | Mid-loop evaluates conditional only | Unconditional transitions are the natural exit. `_find_conditional_transition` skips transitions without a `condition` field. |
| 5 | Jinja in ToolLoopStateConfig | Yes — render through `_render_template` | Jinja rendering is already used everywhere. Zero marginal cost. Enables `max_cost: "{{ context.approved_budget }}"`. |
| 6 | ToolProvider placement | `flatagents` package | Shared by both `ToolLoopAgent` (standalone) and `FlatMachine` (orchestrated). One concept, both layers. |
| 7 | `tool_loop` on non-capable adapter | Runtime error | Clear message: "Agent 'X' (adapter 'Y') does not support machine-driven tool loops. Implement `execute_with_tools` or remove `tool_loop` from state 'Z'." |
| 8 | Cost tracking | Separate loop counter + machine accumulator | `loop_cost` is local for guardrail checks. `_accumulate_agent_metrics` feeds machine-wide `total_cost`. No double-counting. |
| 9 | Parallel tool execution | Sequential for now | Simpler, deterministic, compatible with per-tool-call checkpointing. Can add `parallel_tools: true` later. |

---

## Implementation Order

1. **ToolProvider protocol in flatagents** — `flatagents/tools.py` with `ToolProvider`, `ToolResult`, `SimpleToolProvider`. This is the shared foundation.
2. **Cherry-pick FlatAgent.call() changes** from branch → `tools` param, `rendered_user_prompt`, conditional MCP skip.
3. **Bring over ToolLoopAgent + tests** from branch, adapted to accept `ToolProvider` (with backward-compatible `List[Tool]` convenience).
4. **Update `AgentResult`** in flatmachines — add `tool_calls` and `rendered_user_prompt` fields.
5. **Add `execute_with_tools`** to `AgentExecutor` protocol. Implement in `FlatAgentExecutor`.
6. **Update schemas** — `flatagent.d.ts` (tools field, ToolDefinition), `flatmachine.d.ts` (ToolLoopStateConfig).
7. **Add `on_tool_calls` / `on_tool_result` hooks** to `MachineHooks`. Backward compatible (default no-op).
8. **Implement `_execute_tool_loop`** in FlatMachine — core loop with per-tool-call checkpoints, hooks, and conditional transition evaluation. Wire into `_execute_state`.
9. **Add `_find_conditional_transition`** — evaluates only conditional transitions for mid-loop use.
10. **Add tool_loop checkpoint/resume** — `tool_loop_state` on `MachineSnapshot`, resume logic in `_execute_tool_loop`.
11. **Add `_render_guardrail`** — Jinja2 rendering for `ToolLoopStateConfig` values.
12. **Tests** — unit tests for the machine tool loop (mock agent, mock tool provider), integration tests with per-tool-call transitions and hooks.
13. **Example** — port the branch's `tool_loop` example to use both standalone and machine modes.

---

## Example: Full Coding Agent

### Agent config (`coder.yml`)

```yaml
spec: flatagent
spec_version: "1.1.1"
data:
  name: coder
  model: { profile: "smart" }
  system: |
    You are a coding assistant. Use the provided tools to read files,
    write files, and run commands. Think step by step.
  user: |
    Task: {{ input.task }}
    {% if input.feedback %}
    Previous feedback: {{ input.feedback }}
    {% endif %}
  tools:
    - type: function
      function:
        name: read_file
        description: "Read a file"
        parameters:
          type: object
          properties:
            path: { type: string }
          required: [path]
    - type: function
      function:
        name: write_file
        description: "Write a file"
        parameters:
          type: object
          properties:
            path: { type: string }
            content: { type: string }
          required: [path, content]
    - type: function
      function:
        name: run_command
        description: "Run a shell command"
        parameters:
          type: object
          properties:
            command: { type: string }
          required: [command]
```

### Machine config (`machine.yml`)

```yaml
spec: flatmachine
spec_version: "1.1.1"
data:
  name: coding-workflow
  
  context:
    task: "{{ input.task }}"
    feedback: ""
    files_modified: []
  
  agents:
    coder: ./coder.yml
  
  states:
    start:
      type: initial
      transitions:
        - to: code
    
    code:
      agent: coder
      tool_loop:
        max_turns: 15
        max_cost: 2.00
        denied_tools: [run_command]  # Deny until approved
      input:
        task: "{{ context.task }}"
        feedback: "{{ context.feedback }}"
      output_to_context:
        result: "{{ output.content }}"
      transitions:
        - condition: "context.wants_to_run_command"
          to: approve_command
        - to: done
    
    approve_command:
      wait_for: "approve/{{ context.task_id }}"
      output_to_context:
        command_approved: "{{ output.approved }}"
      transitions:
        - condition: "context.command_approved"
          to: code_with_commands
        - to: done
    
    code_with_commands:
      agent: coder
      tool_loop:
        max_turns: 5
        # No denied_tools — all tools available now
      input:
        task: "{{ context.task }}"
        feedback: "Run command was approved. Continue."
      output_to_context:
        result: "{{ output.content }}"
      transitions:
        - to: done
    
    done:
      type: final
      output:
        result: "{{ context.result }}"
        files: "{{ context.files_modified }}"

  hooks:
    file: ./hooks.py
    class: CodingHooks
    args:
      working_dir: "."
```

### Hooks (`hooks.py`)

```python
import os
import subprocess
from flatagents.tools import ToolProvider, ToolResult
from flatmachines import MachineHooks


class CodingToolProvider(ToolProvider):
    def __init__(self, working_dir: str):
        self.working_dir = working_dir
    
    async def execute_tool(self, name, tool_call_id, arguments):
        if name == "read_file":
            try:
                path = os.path.join(self.working_dir, arguments['path'])
                content = open(path).read()
                return ToolResult(content=content)
            except Exception as e:
                return ToolResult(content=str(e), is_error=True)
        
        elif name == "write_file":
            try:
                path = os.path.join(self.working_dir, arguments['path'])
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, 'w') as f:
                    f.write(arguments['content'])
                return ToolResult(content=f"Wrote {len(arguments['content'])} bytes to {path}")
            except Exception as e:
                return ToolResult(content=str(e), is_error=True)
        
        elif name == "run_command":
            try:
                result = subprocess.run(
                    arguments['command'], shell=True,
                    capture_output=True, text=True, timeout=30,
                    cwd=self.working_dir,
                )
                output = result.stdout
                if result.stderr:
                    output += f"\nSTDERR:\n{result.stderr}"
                return ToolResult(content=output or "(no output)")
            except Exception as e:
                return ToolResult(content=str(e), is_error=True)
        
        return ToolResult(content=f"Unknown tool: {name}", is_error=True)
    
    def get_tool_definitions(self):
        return []  # Using definitions from agent YAML


class CodingHooks(MachineHooks):
    def __init__(self, working_dir: str = "."):
        self._provider = CodingToolProvider(working_dir)
    
    def get_tool_provider(self, state_name):
        return self._provider
    
    def on_tool_calls(self, state_name, tool_calls, context):
        """Check if the LLM wants to run commands."""
        for tc in tool_calls:
            if tc['name'] == 'run_command':
                context['wants_to_run_command'] = True
                context['pending_command'] = tc['arguments'].get('command')
        return context
    
    def on_tool_result(self, state_name, tool_result, context):
        """Track modified files."""
        if tool_result['name'] == 'write_file' and not tool_result['is_error']:
            path = tool_result['arguments'].get('path')
            if path and path not in context.get('files_modified', []):
                context['files_modified'].append(path)
        return context
```

### Standalone usage (no machine)

```python
from flatagents import FlatAgent
from flatagents.tools import ToolProvider, ToolResult, SimpleToolProvider
from flatagents.tool_loop import ToolLoopAgent, Tool, Guardrails

async def read_file(tool_call_id, args):
    return ToolResult(content=open(args['path']).read())

agent = FlatAgent(config_file="coder.yml")

# Using Tool convenience objects (wrapped in SimpleToolProvider internally)
loop = ToolLoopAgent(
    agent=agent,
    tools=[
        Tool(name="read_file", description="Read a file",
             parameters={"type": "object", "properties": {"path": {"type": "string"}}},
             execute=read_file),
    ],
    guardrails=Guardrails(max_turns=5),
)

result = await loop.run(task="Read and summarize README.md")
print(result.content)

# Or using ToolProvider directly
loop = ToolLoopAgent(
    agent=agent,
    tool_provider=my_custom_provider,
    guardrails=Guardrails(max_turns=5),
)
```

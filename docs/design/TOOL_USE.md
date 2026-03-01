# Tool Use Design — FlatAgents + FlatMachines

> **Status:** Draft  
> **Branch reference:** `origin/tool-use-flatagent` (existing prototype)  
> **Date:** 2026-02-28

## Problem

The `tool-use-flatagent` branch adds a `ToolLoopAgent` class in flatagents that runs the entire tool-call loop as an opaque inner loop. It works, but flatmachines can't observe or intervene between tool calls — no hooks fire, no checkpointing, no transition evaluation mid-loop.

We want both:
1. **FlatAgents standalone** — `pip install flatagents` gives you tool use without needing flatmachines.
2. **FlatMachines orchestrated** — the tool loop runs as state transitions inside a machine, with hooks between every tool call, checkpointing for crash recovery, transition evaluation for conditional branching (including human-in-the-loop via `wait_for`).

## Design Principle

**A tool-call round is a state step.** The LLM says "call these tools" → tools execute → results go back. That's the same shape as a state in a machine: enter, execute, evaluate transitions. The tool loop maps onto the existing machine execution model without new abstractions.

---

## Layer 1: FlatAgents (Single-Call Primitives)

FlatAgent stays a single LLM call. No loop. But it needs to support the mechanics of tool use: accepting tool definitions, returning tool call requests, continuing from a message chain.

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
        tools: List[Tool],
        guardrails: Optional[Guardrails] = None,
        steering: Optional[SteeringProvider] = None,
    ):
        ...
    
    async def run(self, **input_data) -> ToolLoopResult:
        """Execute the tool loop to completion."""
        ...
```

**This is identical to what's on the branch.** The key types (`Tool`, `ToolResult`, `Guardrails`, `StopReason`, `ToolLoopResult`, `AggregateUsage`) stay as-is. The test suite from the branch (`test_tool_loop.py`) covers it thoroughly.

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

### ToolLoopAgent Extension: Per-turn Injection Callback

Current `run(**input_data)` semantics render templates from `input_data` on turn 0, then continue with the message chain. There is no first-class way to inject dynamic per-turn state (remaining budget, elapsed cost, steering context, etc.) without reimplementing the loop.

#### Proposed API (backward compatible)

```python
@dataclass
class TurnState:
    turn: int
    total_tool_calls: int
    usage: AggregateUsage
    last_assistant_message: Optional[dict]
    last_tool_results: List[dict]
    input_data: Dict[str, Any]

OnTurnCallback = Callable[[TurnState], Optional[List[dict]] | Awaitable[Optional[List[dict]]]]

class ToolLoopAgent:
    def __init__(..., on_turn: Optional[OnTurnCallback] = None):
        ...

    async def run(self, on_turn: Optional[OnTurnCallback] = None, **input_data) -> ToolLoopResult:
        ...
```

#### Callback semantics

- Called **after tool results are appended** and **before the next LLM call**.
- Receives structured loop state (`turn`, `tool_calls`, aggregated `usage`, last assistant message, last tool results).
- Returns additional messages to append to the chain (or `None`).
- Supports sync or async callbacks.
- If both constructor-level and `run(...)` callback are provided, `run(...)` wins.

#### Why this shape

- Solves dynamic steering/budget injection without template re-rendering.
- Keeps `ToolLoopAgent` simple and composable.
- Preserves current behavior when callback is not supplied.
- Keeps `SteeringProvider` usable for static steering while enabling state-aware steering via callback.

#### Deferred alternative

A callable `input_data` refresh hook (re-rendering templates every turn) is possible but more complex and not needed for the primary use case. Start with message injection callback first.

---

## Layer 2: FlatMachines (Orchestrated Tool Loop)

A state with `agent` + `tool_loop` tells the machine to run the tool-call loop as repeated executions of that state, with the full hook suite and transition evaluation between every round.

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
        - Set context['_skip_tools'] = ['tool_name'] to skip specific calls
        
        Args:
            state_name: Current state name
            tool_calls: List of tool call dicts: [{id, name, arguments}, ...]
            context: Current context
            
        Returns:
            Modified context
        """
        return context
    
    def on_tool_results(
        self,
        state_name: str,
        tool_results: List[Dict[str, Any]],
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Called AFTER tool execution, BEFORE the next LLM call.
        
        Fires once per round after all tools in that round have executed.
        `tool_results` contains the results from each tool call.
        
        Use cases:
        - Inspect results for safety/compliance
        - Update context based on tool outputs (e.g., track modified files)
        - Inject steering messages via context['_steering_messages']
        - Set context['_abort_tool_loop'] = True to stop
        
        Args:
            state_name: Current state name
            tool_results: List of result dicts: [{tool_call_id, name, content, is_error}, ...]
            context: Current context
            
        Returns:
            Modified context
        """
        return context
```

### Tool Execution: Where Tools Come From

Tools need two things: **definitions** (JSON schema for the LLM) and **executors** (code that runs them). These are separate concerns.

**Definitions** come from the agent's YAML config (`data.tools`). The LLM sees these in every call. They can also be provided at runtime via hooks.

**Executors** are registered via hooks. The machine doesn't know how to `read_file` — your hooks do.

```python
# hooks.py for the coding-agent machine

from flatmachines import MachineHooks

class CodingHooks(MachineHooks):
    """Tool execution for the coding agent."""
    
    def __init__(self, working_dir: str = "."):
        self.working_dir = working_dir
        self._tools = {
            "read_file": self._read_file,
            "write_file": self._write_file,
        }
    
    def on_action(self, action_name: str, context: dict) -> dict:
        """Execute a tool call. Called by the machine's tool loop."""
        if action_name.startswith("tool:"):
            tool_name = action_name[5:]  # Strip "tool:" prefix
            executor = self._tools.get(tool_name)
            if executor:
                # Tool args and call ID are in context['_tool_call']
                call = context['_tool_call']
                result = executor(call['arguments'])
                context['_tool_result'] = result
        return context
    
    def on_tool_results(self, state_name, tool_results, context):
        """Track which files were modified."""
        for result in tool_results:
            if result['name'] == 'write_file' and not result.get('is_error'):
                path = result.get('arguments', {}).get('path')
                if path:
                    context.setdefault('files_modified', []).append(path)
        return context
    
    def _read_file(self, args):
        path = os.path.join(self.working_dir, args['path'])
        return {"content": open(path).read()}
    
    def _write_file(self, args):
        path = os.path.join(self.working_dir, args['path'])
        with open(path, 'w') as f:
            f.write(args['content'])
        return {"written": True}
```

However, **on_action is synchronous and one-tool-at-a-time**. For tool loops, we need a more direct mechanism. The preferred pattern is a **ToolProvider** protocol:

```python
# flatmachines/tool_providers.py (NEW file)

from typing import Any, Dict, List, Optional, Protocol
from dataclasses import dataclass


@dataclass
class ToolResult:
    """Result from executing a tool."""
    content: str
    is_error: bool = False


class ToolProvider(Protocol):
    """
    Provides tool definitions and execution for tool_loop states.
    
    Registered on the machine via hooks or constructor arg.
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
```

ToolProvider is passed to the machine:

```python
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
    
    Each LLM-call + tool-execution round is a step:
    1. Call agent (with tools + message chain)
    2. If agent returns tool_calls:
       a. Fire on_tool_calls hook
       b. Execute tools via ToolProvider
       c. Fire on_tool_results hook
       d. Check guardrails (max_turns, max_tool_calls, cost)
       e. Evaluate transitions — if any match, EXIT the loop
       f. Checkpoint
       g. Append results to chain, go to step 1
    3. If agent returns content (no tool_calls):
       a. Loop is done. Return output for normal transition evaluation.
    """
    # Parse guardrails from state config
    loop_config = state.get('tool_loop', {})
    if isinstance(loop_config, bool):
        loop_config = {}
    
    max_turns = loop_config.get('max_turns', 20)
    max_tool_calls = loop_config.get('max_tool_calls', 50)
    tool_timeout = loop_config.get('tool_timeout', 30.0)
    total_timeout = loop_config.get('total_timeout', 600.0)
    max_cost = loop_config.get('max_cost')
    allowed_tools = set(loop_config.get('allowed_tools', []))
    denied_tools = set(loop_config.get('denied_tools', []))
    
    # Get agent executor and tool provider
    executor = self._get_executor(agent_name)
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
        
        # --- Call agent ---
        if turns == 0:
            # First turn: pass input_data for template rendering + tools
            response = await self._call_agent_with_tools(
                executor, agent_input, tool_defs, chain=None
            )
        else:
            # Subsequent turns: pass chain only
            response = await self._call_agent_with_tools(
                executor, {}, tool_defs, chain=chain
            )
        
        turns += 1
        self._accumulate_agent_metrics(response)
        loop_cost += self._extract_cost(response)
        
        # Update context with loop metadata
        context['_tool_loop_turns'] = turns
        context['_tool_loop_cost'] = loop_cost
        context['_tool_calls_count'] = tool_calls_count
        
        # --- Handle error ---
        if response.error:
            raise RuntimeError(
                f"{response.error.get('type', 'AgentError')}: "
                f"{response.error.get('message', 'unknown')}"
            )
        
        # --- Seed chain on first turn ---
        if turns == 1 and response.rendered_user_prompt:
            chain.append({"role": "user", "content": response.rendered_user_prompt})
        
        # --- Build assistant message and append to chain ---
        assistant_msg = self._build_assistant_message(response)
        chain.append(assistant_msg)
        last_content = response.content
        
        # --- No tool calls = loop complete ---
        if response.finish_reason != "tool_use":
            break
        
        pending_calls = response.tool_calls or []
        
        # --- Guardrail: tool call count ---
        if tool_calls_count + len(pending_calls) > max_tool_calls:
            context['_tool_loop_stop'] = 'max_tool_calls'
            break
        
        # --- HOOK: on_tool_calls ---
        context = await self._run_hook(
            'on_tool_calls', state_name, 
            [{"id": tc.id, "name": tc.tool, "arguments": tc.arguments} 
             for tc in pending_calls],
            context,
        )
        
        if context.get('_abort_tool_loop'):
            context['_tool_loop_stop'] = 'aborted'
            break
        
        # --- Execute tools ---
        tool_results = []
        for tc in pending_calls:
            result = await self._execute_single_tool(
                tool_provider, tc, tool_timeout, allowed_tools, denied_tools
            )
            tool_calls_count += 1
            tool_results.append({
                "tool_call_id": tc.id,
                "name": tc.tool,
                "arguments": tc.arguments,
                "content": result.content,
                "is_error": result.is_error,
            })
            chain.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result.content,
            })
        
        context['_tool_calls_count'] = tool_calls_count
        
        # --- HOOK: on_tool_results ---
        context = await self._run_hook(
            'on_tool_results', state_name, tool_results, context,
        )
        
        if context.get('_abort_tool_loop'):
            context['_tool_loop_stop'] = 'aborted'
            break
        
        # --- Inject steering messages from hook ---
        steering = context.pop('_steering_messages', None)
        if steering:
            for msg in steering:
                chain.append(msg)
        
        # --- Checkpoint between rounds ---
        await self._save_checkpoint(
            'tool_loop_round', state_name, self._current_step, context
        )
        
        # --- Evaluate transitions mid-loop ---
        # If any transition condition is true, exit the tool loop
        # and let the main execute loop handle the transition.
        next_state = self._find_next_state(state_name, context)
        if next_state is not None:
            context['_tool_loop_stop'] = 'transition'
            context['_tool_loop_next_state'] = next_state
            break
    
    # --- Build output ---
    output = {
        "content": last_content,
        "_tool_calls_count": tool_calls_count,
        "_tool_loop_turns": turns,
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

### Mid-Loop Transition Evaluation

This is the key feature that makes the FlatMachine version powerful. After every tool-call round, the machine checks transitions:

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
      # These are checked BETWEEN every tool-call round:
      - condition: "context.needs_approval"
        to: wait_for_approval
      - condition: "context._tool_calls_count > 20"
        to: too_many_tools
      - condition: "context._tool_loop_cost > 0.50"
        to: cost_warning
      # This is the normal exit (when LLM finishes without more tool calls):
      - to: review
```

The transitions evaluate against the current context, which hooks can modify between rounds. This means hooks can set flags that trigger transitions:

```python
class SafetyHooks(MachineHooks):
    def on_tool_results(self, state_name, tool_results, context):
        # Check if any tool wrote to a sensitive path
        for result in tool_results:
            if result['name'] == 'write_file':
                path = result['arguments'].get('path', '')
                if '/etc/' in path or path.startswith('/root'):
                    context['needs_approval'] = True  # Triggers transition!
        return context
```

### Handling `_tool_loop_next_state`

When a mid-loop transition fires, the main `execute` loop needs to know:

```python
# In _execute_state, after _execute_tool_loop returns:
if context.get('_tool_loop_next_state'):
    # Mid-loop transition override — skip normal transition evaluation
    # The main loop will pick this up
    pass
```

And in the main `execute` loop:

```python
# In execute(), after _execute_state returns:
if '_tool_loop_next_state' in context:
    next_state = context.pop('_tool_loop_next_state')
    context.pop('_tool_loop_stop', None)
else:
    next_state = self._find_next_state(current_state, context)
```

### Checkpoint & Resume

The tool loop checkpoints after every round (`tool_loop_round` event). On resume:

```python
# In _execute_tool_loop, at the start:
# Check if we have a checkpointed chain to resume from
if self._resuming_tool_loop:
    chain = self._resumed_chain
    turns = self._resumed_turns
    tool_calls_count = self._resumed_tool_calls_count
    # Continue the loop from where we left off
```

The chain, turns, and tool_calls_count need to be included in the checkpoint snapshot. This means `MachineSnapshot` gets an optional `tool_loop_state` field:

```python
@dataclass
class MachineSnapshot:
    # ... existing fields ...
    tool_loop_state: Optional[Dict[str, Any]] = None
    # Contains: chain, turns, tool_calls_count, loop_cost, start_time
```

---

## Comparison

| Capability | ToolLoopAgent (flatagents) | FlatMachine + tool_loop |
|---|---|---|
| Basic tool-call loop | ✅ | ✅ |
| Guardrails (turns, calls, cost, timeout) | ✅ | ✅ |
| Tool allow/deny lists | ✅ | ✅ |
| Steering messages between rounds | ✅ (callback) | ✅ (hook sets `_steering_messages`) |
| Usage aggregation | ✅ | ✅ (machine-level metrics) |
| Hooks between tool calls | ❌ | ✅ `on_tool_calls`, `on_tool_results` |
| Checkpoint / crash recovery | ❌ | ✅ every round |
| Transition evaluation mid-loop | ❌ | ✅ |
| Human-in-the-loop (`wait_for`) | ❌ | ✅ (transition to `wait_for` state) |
| Conditional branching mid-loop | ❌ (stop only) | ✅ (any transition) |
| Error recovery (`on_error`) | ❌ (stop only) | ✅ (machine error handling) |
| Compose with other machines | ❌ | ✅ |
| Works without flatmachines | ✅ | ❌ |

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

1. Agent works in `code` state, tools firing, hooks running, checkpointing every round.
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
                    context.setdefault('_skip_tools', []).append(tc['name'])
            if pending:
                context['pending_writes'] = pending
                # This triggers the mid-loop transition to review_writes
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

## Open Questions

### 1. How does the FlatAgent adapter pass tools through?

The current `FlatAgentExecutor.execute()` calls `self._agent.call(**input_data)`. For tool loops, the machine needs to call `self._agent.call(messages=chain, tools=tool_defs, **input_data)`. 

Options:
- **A) New method on AgentExecutor protocol:** `execute_with_tools(input_data, tools, messages) -> AgentResult`
- **B) Pass tools/messages in input_data:** `input_data['_tools'] = ...`, `input_data['_messages'] = ...`
- **C) Direct FlatAgent access:** The tool loop bypasses the adapter and calls FlatAgent directly when it detects the agent is a FlatAgent.

Leaning toward **A** — it's explicit and keeps the protocol clean. Non-flatagent adapters can raise NotImplementedError.

### 2. Should transitions evaluate after EVERY tool call, or after each ROUND?

A round is one LLM response, which may contain multiple tool calls. The LLM says "call read_file and list_dir" — that's one round with two tool calls.

Proposal: evaluate after each **round** (after all tools in one response execute). This matches the natural cadence and avoids mid-batch evaluation complexity. Hooks fire per-round too.

### 3. What about tool definitions — YAML-only or runtime too?

Current proposal: tool definitions come from agent YAML (`data.tools`). But some use cases need runtime-determined tools (e.g., available tools depend on context).

The `ToolProvider.get_tool_definitions()` method handles this — its definitions merge with YAML ones. Hooks can also swap the tool provider per state. But should the machine YAML be able to declare tools too?

```yaml
# Option: tools at the state level in machine YAML
states:
  code:
    agent: coder
    tool_loop:
      tools:
        - type: function
          function:
            name: read_file
            ...
```

This seems like over-specification. Better to keep tool definitions in the agent YAML or provider, and let the machine YAML only control the loop config (guardrails).

### 4. Cost tracking across the tool loop

`_execute_tool_loop` needs to extract cost from each agent call. The current adapter returns `AgentResult` with `cost: Optional[CostInfo | float]`. The loop accumulates this. But `_accumulate_agent_metrics` on the machine already does this per-call — we need to avoid double-counting.

Proposal: the tool loop calls `_accumulate_agent_metrics` for each call (existing behavior), and also maintains its own `loop_cost` counter for guardrail evaluation. The machine's `total_cost` includes all calls automatically.

### 5. Parallel tool execution

The branch's `ToolLoopAgent` executes tools sequentially. Should the FlatMachine version support parallel execution?

Proposal: sequential by default (simpler, deterministic). Add `parallel_tools: true` to `ToolLoopStateConfig` later if needed. Tool execution order rarely matters, but parallel execution complicates hook interactions and error handling.

---

## Implementation Order

1. **Cherry-pick FlatAgent.call() changes** from branch → `tools` param, `rendered_user_prompt`, conditional MCP skip. Small, surgical diff.
2. **Bring over ToolLoopAgent + tests** from branch as-is. Standalone flatagents use case works immediately.
3. **Add ToolProvider protocol** to flatmachines. Simple protocol, no machine changes yet.
4. **Add on_tool_calls / on_tool_results hooks** to MachineHooks. Backward compatible (default no-op).
5. **Implement _execute_tool_loop** in FlatMachine. The core logic. Wire it into `_execute_state`.
6. **Add mid-loop transition evaluation + _tool_loop_next_state handling**.
7. **Add tool_loop checkpoint/resume support** to MachineSnapshot.
8. **Update schemas** — flatagent.d.ts (tools field), flatmachine.d.ts (ToolLoopStateConfig).
9. **Tests** — unit tests for the machine tool loop (mock agent, mock tool provider), integration tests with real transitions and hooks.
10. **Example** — port the branch's `tool_loop` example to use both standalone and machine modes.

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
import asyncio
import os
import subprocess
from flatmachines import MachineHooks
from flatmachines.tool_providers import ToolProvider, ToolResult


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
    
    def on_tool_results(self, state_name, tool_results, context):
        """Track modified files."""
        for r in tool_results:
            if r['name'] == 'write_file' and not r['is_error']:
                path = r['arguments'].get('path')
                if path and path not in context.get('files_modified', []):
                    context['files_modified'].append(path)
        return context
```

### Standalone usage (no machine)

```python
from flatagents import FlatAgent
from flatagents.tool_loop import ToolLoopAgent, Tool, ToolResult, Guardrails

async def read_file(tool_call_id, args):
    return ToolResult(content=open(args['path']).read())

agent = FlatAgent(config_file="coder.yml")
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
```

# Tool Use Proposal for flatagents AND flatmachines

> **Status:** Superseded by [TOOL_USE.md](./TOOL_USE.md)

Here's my analysis and a design proposal for getting the best of both worlds:

Current State

Branch tool-use-flatagent adds:
1. ToolLoopAgent in flatagents/tool_loop.py — a standalone Python class that wraps a FlatAgent and runs the tool-call loop: message chain management, tool
execution, guardrails (max_turns, max_tool_calls, timeouts, cost limits), and steering injection between rounds.
2. FlatAgent.call() modifications — adds a tools param so external tools can be passed directly (bypassing MCP discovery), plus rendered_user_prompt on
AgentResponse so the tool loop can seed the message chain.
3. Schema additions — tools and tool_loop fields on AgentData in flatagent.d.ts.

The problem you identified: ToolLoopAgent is a self-contained Python loop that lives entirely inside flatagents. FlatMachines can't see what's happening
between tool calls — no hooks fire, no checkpointing, no transition evaluation, no machine-level orchestration of the tool loop.

Design: Tool Use at Both Layers

The key insight: a tool-call round is just a state transition. The tool loop maps naturally onto a flatmachine where each LLM-call + tool-execution is a
state step.

### Layer 1: FlatAgents (single-call primitives) ✅ Keep from branch

Keep the branch's changes to FlatAgent.call():
- Accept tools param and messages for chain continuation
- Return rendered_user_prompt and tool_calls on AgentResponse

These are the building blocks — a single LLM call that knows about tools. No loop, no orchestration. This is what makes FlatAgent composable.

Don't keep ToolLoopAgent as-is. Instead, provide a simpler convenience wrapper:

```python
  # flatagents/tool_loop.py — thin convenience for standalone use
  class ToolLoopAgent:
      """Convenience wrapper for simple tool-use without FlatMachines.

      For hooks, checkpointing, conditional branching between tool calls,
      or integration with larger workflows, use a FlatMachine with
      tool_loop: true on the agent state instead.
      """
```

This keeps the simple pip install flatagents use case working without needing flatmachines.

### Layer 2: FlatMachines (orchestrated tool loop) 🆕 New

A state with agent + tool_loop: true tells the machine to run the tool-call loop as state transitions within the machine, not as an opaque inner loop. Here's
what that looks like:

#### Schema (flatmachine.d.ts)

Already has tool_loop?: boolean on StateDefinition. We extend it:

```typescript
  export interface StateDefinition {
    // ... existing fields ...
    tool_loop?: boolean | ToolLoopStateConfig;
  }

  export interface ToolLoopStateConfig {
    max_tool_calls?: number;     // default 50
    max_turns?: number;          // default 20
    allowed_tools?: string[];
    denied_tools?: string[];
    tool_timeout?: number;       // per-tool seconds
    total_timeout?: number;      // total loop seconds
    max_cost?: number;
  }
```

#### Execution Flow

When FlatMachine encounters a state with tool_loop: true:

```
  1. Enter state "coding" (on_state_enter hook fires)
  2. Call agent with tools → response has tool_calls
  3. Fire on_tool_calls hook (NEW) with tool_calls + context
     → Hook can approve/deny/modify, inject steering messages
  4. Execute tools (with per-tool timeout)
  5. Fire on_tool_results hook (NEW) with results + context
     → Hook can inspect results, update context, decide to stop
  6. Check guardrails (max_turns, max_tool_calls, cost)
  7. Check transitions — if any condition is true, EXIT the tool loop and transition
  8. If no transition matches and LLM wants more tools, go to step 2
  9. When LLM stops calling tools (finish_reason=stop), evaluate transitions normally
```

This is the killer feature: transitions are evaluated between tool-call rounds, so you can write:

```yaml
  states:
    coding:
      agent: coder
      tool_loop: true
      input:
        task: "{{ context.task }}"
      output_to_context:
        code: "{{ output.content }}"
        tool_calls_count: "{{ output.tool_calls_count }}"
      transitions:
        - condition: "context.needs_approval"
          to: wait_for_approval       # Human-in-the-loop!
        - condition: "context.cost > 0.50"
          to: cost_exceeded
        - to: review

    wait_for_approval:
      wait_for: "approval/{{ context.task_id }}"
      # ... resumes coding state or rejects
```

#### New Hooks

```python
  class MachineHooks:
      # ... existing hooks ...

      def on_tool_calls(
          self,
          state_name: str,
          tool_calls: List[Dict],
          context: Dict[str, Any],
      ) -> Dict[str, Any]:
          """Called before tool execution. Can modify context.
          Set context['_abort_tool_loop'] = True to stop early."""
          return context

      def on_tool_results(
          self,
          state_name: str,
          tool_results: List[Dict],
          context: Dict[str, Any],
      ) -> Dict[str, Any]:
          """Called after tool execution, before next LLM call."""
          return context
```

#### Implementation in _execute_state

The tool loop in flatmachine.py replaces the simple agent call when tool_loop is set:

```python
  # In _execute_state, where agent execution happens:
  if agent_name and state.get('tool_loop'):
      result = await self._execute_tool_loop_state(state_name, state, context)
  else:
      # ... existing single-call agent logic ...
```

The _execute_tool_loop_state method manages the loop using FlatAgent.call(messages=chain, tools=tools) for each round, firing hooks and checking transitions
between rounds.

#### Tool Registration

Tools need to come from somewhere. Three options, all composable:

1. Hooks (most flexible):
  ```python
    class MyHooks(MachineHooks):
        def on_tool_calls(self, state_name, tool_calls, context):
            # Tools are registered in hooks, executed by machine
            return context
  ```
2. Agent config (YAML-declared, from the flatagent.d.ts tools field):
  ```yaml
    # agent.yml
    data:
      tools:
        - type: function
          function:
            name: read_file
            description: "Read a file"
            parameters: { ... }
  ```
3. State-level tool config (from flatmachine.d.ts):
  ```yaml
    states:
      coding:
        agent: coder
        tool_loop:
          tools: ./tools.yml  # or inline
  ```

For execution, tools are resolved via a ToolProvider that hooks can implement:

```python
  class ToolProvider(Protocol):
      async def execute_tool(self, name: str, args: Dict) -> ToolResult: ...
      def get_tool_definitions(self) -> List[Dict]: ...
```

### What This Gets You

┌─────────────────────────────────────┬─────────────────────────────────┬─────────────────────────────┐
│ Capability                          │ ToolLoopAgent (flatagents only) │ FlatMachine + tool_loop     │
├─────────────────────────────────────┼─────────────────────────────────┼─────────────────────────────┤
│ Basic tool loop                     │ ✅                              │ ✅                          │
├─────────────────────────────────────┼─────────────────────────────────┼─────────────────────────────┤
│ Guardrails                          │ ✅                              │ ✅                          │
├─────────────────────────────────────┼─────────────────────────────────┼─────────────────────────────┤
│ Hooks between calls                 │ ❌ (steering only)              │ ✅ full hook suite          │
├─────────────────────────────────────┼─────────────────────────────────┼─────────────────────────────┤
│ Checkpointing                       │ ❌                              │ ✅ every round              │
├─────────────────────────────────────┼─────────────────────────────────┼─────────────────────────────┤
│ Transition evaluation mid-loop      │ ❌                              │ ✅                          │
├─────────────────────────────────────┼─────────────────────────────────┼─────────────────────────────┤
│ Human-in-the-loop (wait_for)        │ ❌                              │ ✅                          │
├─────────────────────────────────────┼─────────────────────────────────┼─────────────────────────────┤
│ Cost-gated approval                 │ ❌ (stop only)                  │ ✅ (transition to approval) │
├─────────────────────────────────────┼─────────────────────────────────┼─────────────────────────────┤
│ Resume after crash                  │ ❌                              │ ✅                          │
├─────────────────────────────────────┼─────────────────────────────────┼─────────────────────────────┤
│ Composable with other machines      │ ❌                              │ ✅                          │
├─────────────────────────────────────┼─────────────────────────────────┼─────────────────────────────┤
│ Zero dependencies (no flatmachines) │ ✅                              │ ❌                          │
└─────────────────────────────────────┴─────────────────────────────────┴─────────────────────────────┘

────────────────────────────────────────────────────────────────────────────────

Want me to implement this? I'd suggest this order:

1. Cherry-pick the FlatAgent.call() changes from the branch (tools param, rendered_user_prompt, FinishReason.TOOL_USE)
2. Bring over ToolLoopAgent as the lightweight flatagents-only convenience
3. Implement _execute_tool_loop_state in FlatMachine with hooks + transition evaluation between rounds
4. Add on_tool_calls / on_tool_results hooks
5. Tests for both layers
6. Update the specs (flatagent.d.ts, flatmachine.d.ts)


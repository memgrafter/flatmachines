# ToolLoopAgent Extension: Per-turn Mutation Callback

> **Status:** Deferred  
> **Parent:** [TOOL_USE.md](./TOOL_USE.md)  
> **Date:** 2026-03-01

## Context

`ToolLoopAgent.run(**input_data)` renders templates from `input_data` on turn 0, then continues with a private message chain. There is no first-class way to inject dynamic per-turn state (budget, elapsed cost, steering, tool policy) without reimplementing the loop.

For this codebase (internal use, no external compatibility contract), expose a broad mutation seam.

## Proposed API

```python
@dataclass
class TurnContext:
    # conversation + loop state (mutable)
    messages: List[dict]
    input_data: Dict[str, Any]

    turn: int
    total_tool_calls: int
    usage: AggregateUsage

    last_assistant_message: Optional[dict]
    last_tool_results: List[dict]

    # optional mutable knobs
    guardrails: Guardrails
    allowed_tools: Optional[List[str]]
    denied_tools: Optional[List[str]]
    stop_reason: Optional[StopReason]

OnTurnCallback = Callable[
    [TurnContext],
    Optional[TurnContext] | Awaitable[Optional[TurnContext]]
]

class ToolLoopAgent:
    def __init__(..., on_turn: Optional[OnTurnCallback] = None):
        ...

    async def run(self, on_turn: Optional[OnTurnCallback] = None, **input_data) -> ToolLoopResult:
        ...
```

## Semantics

- Called **after tool results are appended** and **before the next LLM call**.
- Callback may mutate `TurnContext` in place and return `None`, or return a replacement `TurnContext`.
- Supports sync or async callbacks.
- If both constructor-level and `run(...)` callback are provided, `run(...)` wins.
- Keep only minimal runtime validation (message shape, non-negative counters, known stop reason values).

## Notes

- This intentionally allows arbitrary state control per turn.
- "Append-only messages" remains a subset pattern: callback can choose to only append to `messages`.
- If stricter boundaries are desired later, we can layer a typed/limited callback on top.
- For FlatMachine-orchestrated tool loops, the `on_tool_result` hook provides equivalent power with checkpointing and transitions.

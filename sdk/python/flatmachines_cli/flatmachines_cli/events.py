"""
Event types emitted by CLIHooks into the backend pipeline.

Events are plain dicts with a "type" key. This module defines the type
constants and convenience constructors. Keeping events as dicts (not
dataclasses) makes them trivially serializable — important when the
frontend is eventually replaced by Rust reading from a socket.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


# --- Event type constants ---

MACHINE_START = "machine_start"
MACHINE_END = "machine_end"
STATE_ENTER = "state_enter"
STATE_EXIT = "state_exit"
TRANSITION = "transition"
TOOL_CALLS = "tool_calls"
TOOL_RESULT = "tool_result"
ACTION = "action"
ERROR = "error"

# All event types that processors may subscribe to
ALL_TYPES = frozenset({
    MACHINE_START, MACHINE_END,
    STATE_ENTER, STATE_EXIT,
    TRANSITION,
    TOOL_CALLS, TOOL_RESULT,
    ACTION, ERROR,
})


# --- Event constructors ---
# Each returns a plain dict. "type" is always first key for readability.

def machine_start(context: Dict[str, Any]) -> Dict[str, Any]:
    machine_meta = context.get("machine") or {}
    return {
        "type": MACHINE_START,
        "machine_name": machine_meta.get("machine_name", "") if isinstance(machine_meta, dict) else "",
        "execution_id": machine_meta.get("execution_id", "") if isinstance(machine_meta, dict) else "",
        "context": context,
    }


def machine_end(
    context: Dict[str, Any],
    final_output: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "type": MACHINE_END,
        "final_output": final_output,
        "context": context,
    }


def state_enter(state_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
    machine = context.get("machine") or {}
    return {
        "type": STATE_ENTER,
        "state": state_name,
        "step": machine.get("step", 0) if isinstance(machine, dict) else 0,
        "context": context,
    }


def state_exit(
    state_name: str,
    context: Dict[str, Any],
    output: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    return {
        "type": STATE_EXIT,
        "state": state_name,
        "output": output,
        "context": context,
    }


def transition(
    from_state: str,
    to_state: str,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "type": TRANSITION,
        "from_state": from_state,
        "to_state": to_state,
        "context": context,
    }


def tool_calls(
    state_name: str,
    calls: List[Dict[str, Any]],
    context: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "type": TOOL_CALLS,
        "state": state_name,
        "tool_calls": calls,
        "content": context.get("_tool_loop_content", ""),
        "usage": context.get("_tool_loop_usage", {}),
        "cost": context.get("_tool_loop_cost", 0.0),
        "turns": context.get("_tool_loop_turns", 0),
        "context": context,
    }


def tool_result(
    state_name: str,
    result: Dict[str, Any],
    context: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "type": TOOL_RESULT,
        "state": state_name,
        "name": result.get("name", ""),
        "arguments": result.get("arguments", {}),
        "content": result.get("content", ""),
        "is_error": result.get("is_error", False),
        "tool_call_id": result.get("tool_call_id", ""),
        "context": context,
    }


def action(action_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "type": ACTION,
        "action": action_name,
        "context": context,
    }


def error(
    state_name: str,
    exc: Exception,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "type": ERROR,
        "state": state_name,
        "error_type": type(exc).__name__,
        "error_message": str(exc),
        "context": context,
    }

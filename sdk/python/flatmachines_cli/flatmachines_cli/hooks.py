"""
CLIHooks — bridge from flatmachines MachineHooks to the CLI backend.

This is the integration point between flatmachines execution and the
CLI data pipeline. Each hook method:
1. Converts the flatmachines callback into a typed event dict.
2. Broadcasts the event to the backend (which fans out to processors).
3. Returns immediately — no blocking, no I/O, no rendering.

The hooks also handle actions (like human_review) by delegating to the
backend's action handler, which coordinates with the frontend.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

from flatmachines import MachineHooks

from . import events

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .backend import CLIBackend


class CLIHooks(MachineHooks):
    """
    MachineHooks implementation that emits events to a CLIBackend.

    The hooks are intentionally thin — all data processing happens
    in the backend's async processors. The hooks just capture and emit.

    Usage:
        backend = CLIBackend(...)
        hooks = CLIHooks(backend)
        machine = FlatMachine(config_file="...", hooks=hooks)
    """

    def __init__(
        self,
        backend: CLIBackend,
        tool_provider_factory: Optional[Callable] = None,
    ):
        self._backend = backend
        self._tool_provider_factory = tool_provider_factory
        self._tool_provider = None
        self._hook_timings: Dict[str, float] = {}
        self._hook_counts: Dict[str, int] = {}

    def _emit(self, event: Dict[str, Any]) -> None:
        """Emit event to backend. Non-blocking."""
        self._backend.emit(event)

    def _record_timing(self, hook_name: str, elapsed: float) -> None:
        """Record execution time for a hook call."""
        self._hook_timings[hook_name] = (
            self._hook_timings.get(hook_name, 0.0) + elapsed
        )
        self._hook_counts[hook_name] = (
            self._hook_counts.get(hook_name, 0) + 1
        )

    @property
    def timing_stats(self) -> Dict[str, Dict[str, Any]]:
        """Return timing statistics for all hooks.

        Returns dict of {hook_name: {calls, total_ms, avg_ms}}.
        Useful for performance debugging.
        """
        stats = {}
        for name, total_s in self._hook_timings.items():
            count = self._hook_counts.get(name, 0)
            total_ms = total_s * 1000
            stats[name] = {
                "calls": count,
                "total_ms": round(total_ms, 3),
                "avg_ms": round(total_ms / count, 3) if count > 0 else 0,
            }
        return stats

    # --- MachineHooks interface ---

    def on_machine_start(self, context: Dict[str, Any]) -> Dict[str, Any]:
        t0 = time.monotonic()
        self._emit(events.machine_start(context))
        self._record_timing("on_machine_start", time.monotonic() - t0)
        return context

    def on_machine_end(
        self, context: Dict[str, Any], final_output: Dict[str, Any]
    ) -> Dict[str, Any]:
        t0 = time.monotonic()
        self._emit(events.machine_end(context, final_output))
        self._record_timing("on_machine_end", time.monotonic() - t0)
        return final_output

    def on_state_enter(
        self, state_name: str, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        t0 = time.monotonic()
        self._emit(events.state_enter(state_name, context))
        self._record_timing("on_state_enter", time.monotonic() - t0)
        return context

    def on_state_exit(
        self,
        state_name: str,
        context: Dict[str, Any],
        output: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        t0 = time.monotonic()
        self._emit(events.state_exit(state_name, context, output))
        self._record_timing("on_state_exit", time.monotonic() - t0)
        return output

    def on_transition(
        self, from_state: str, to_state: str, context: Dict[str, Any]
    ) -> str:
        t0 = time.monotonic()
        self._emit(events.transition(from_state, to_state, context))
        self._record_timing("on_transition", time.monotonic() - t0)
        return to_state

    def on_error(
        self, state_name: str, error: Exception, context: Dict[str, Any]
    ) -> Optional[str]:
        t0 = time.monotonic()
        self._emit(events.error(state_name, error, context))
        self._record_timing("on_error", time.monotonic() - t0)
        return None  # re-raise by default

    def on_action(
        self, action_name: str, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        t0 = time.monotonic()
        self._emit(events.action(action_name, context))
        # Delegate action handling to the backend's action handler
        result = self._backend.handle_action(action_name, context)
        self._record_timing("on_action", time.monotonic() - t0)
        return result

    def on_tool_calls(
        self,
        state_name: str,
        tool_calls: List[Dict[str, Any]],
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        t0 = time.monotonic()
        self._emit(events.tool_calls(state_name, tool_calls, context))
        self._record_timing("on_tool_calls", time.monotonic() - t0)
        return context

    def on_tool_result(
        self,
        state_name: str,
        tool_result: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        t0 = time.monotonic()
        self._emit(events.tool_result(state_name, tool_result, context))
        self._record_timing("on_tool_result", time.monotonic() - t0)
        return context

    def get_tool_provider(self, state_name: str):
        """Return tool provider, creating lazily if factory is set."""
        if self._tool_provider is None and self._tool_provider_factory:
            self._tool_provider = self._tool_provider_factory(state_name)
        return self._tool_provider

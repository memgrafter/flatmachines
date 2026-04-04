"""
Async data processors — the backend data-preparation layer.

Each processor:
1. Receives raw events from an asyncio.Queue (fed by CLIHooks).
2. Maintains its own aggregated state.
3. Writes processed/formatted data to a DataBus slot.
4. Is Hz-capped: output writes are throttled to max_hz, preventing
   the bus from churning faster than any frontend can consume.

Processors run as independent async tasks. One slow processor never
blocks another. This is the key async guarantee the user requested.

Processor lifecycle:
    start() → runs until stop() or queue gets sentinel → cleanup
"""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from . import events
from .bus import DataBus

logger = logging.getLogger(__name__)

# Sentinel to signal processor shutdown
_STOP = object()


class Processor(ABC):
    """
    Base async processor with Hz-capped output.

    Subclasses implement:
        slot_name   — which bus slot to write to
        event_types — which event types to process (None = all)
        process()   — handle one event, return data to write (or None to skip)
    """

    def __init__(self, bus: DataBus, max_hz: float = 30.0, queue_size: int = 1024):
        self._bus = bus
        self._max_hz = max_hz
        self._min_interval = 1.0 / max_hz if max_hz > 0 else 0.0
        self._last_write: float = 0.0
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=queue_size)
        self._task: Optional[asyncio.Task] = None
        self._pending_data: Any = None  # buffered between hz-throttled writes

    @property
    @abstractmethod
    def slot_name(self) -> str:
        """Bus slot name this processor writes to."""
        ...

    @property
    def event_types(self) -> Optional[frozenset]:
        """Event types to process. None means all events."""
        return None

    @abstractmethod
    def process(self, event: Dict[str, Any]) -> Any:
        """
        Process a single event. Return data to write to the bus slot,
        or None to skip writing.

        This method should be fast. Do aggregation/formatting here,
        not I/O. It runs in the processor's own async task so it
        won't block other processors, but keeping it fast means
        the processor stays responsive to new events.
        """
        ...

    def reset(self) -> None:
        """Reset processor state for a new machine execution. Override in subclasses."""
        pass

    def accepts(self, event: Dict[str, Any]) -> bool:
        """Check if this processor handles the given event type."""
        types = self.event_types
        if types is None:
            return True
        return event.get("type") in types

    def enqueue(self, event: Dict[str, Any]) -> None:
        """
        Push an event into this processor's queue. Non-blocking.
        Called by the backend dispatcher. Never raises.
        """
        # Drop if queue is full — UDP semantics. 1024 is generous headroom.
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            pass

    async def _run(self) -> None:
        """Main loop: drain queue, process, hz-cap writes.

        Uses a timeout on queue.get() to ensure pending data is flushed
        even when no new events arrive. Without this, the last buffered
        update could be lost until stop() or the next event.
        """
        while True:
            try:
                event = await asyncio.wait_for(
                    self._queue.get(),
                    timeout=self._min_interval if self._pending_data is not None else None,
                )
            except asyncio.TimeoutError:
                # No new event arrived — flush pending data
                if self._pending_data is not None:
                    self._bus.write(self.slot_name, self._pending_data)
                    self._last_write = time.monotonic()
                    self._pending_data = None
                continue

            if event is _STOP:
                # Flush any pending data before exit
                if self._pending_data is not None:
                    self._bus.write(self.slot_name, self._pending_data)
                    self._pending_data = None
                break

            if not self.accepts(event):
                continue

            try:
                data = self.process(event)
            except Exception as e:
                logger.warning(
                    "Processor %s failed on event %s: %s",
                    self.slot_name, event.get("type", "?"), e,
                )
                continue
            if data is None:
                continue

            now = time.monotonic()
            elapsed = now - self._last_write
            if elapsed >= self._min_interval:
                self._bus.write(self.slot_name, data)
                self._last_write = now
                self._pending_data = None
            else:
                # Buffer latest — will be flushed after min_interval timeout
                self._pending_data = data

    def __repr__(self) -> str:
        running = "running" if self._task and not self._task.done() else "stopped"
        pending = " (pending)" if self._pending_data is not None else ""
        return f"{type(self).__name__}(slot={self.slot_name!r}, hz={self._max_hz}, {running}{pending})"

    def start(self) -> asyncio.Task:
        """Start the processor as an async task."""
        self._task = asyncio.ensure_future(self._run())
        return self._task

    def stop(self) -> None:
        """Signal processor to stop. It will flush pending data and exit."""
        try:
            self._queue.put_nowait(_STOP)
        except asyncio.QueueFull:
            # Force-cancel if queue is jammed
            if self._task and not self._task.done():
                self._task.cancel()


# ---------------------------------------------------------------------------
# Concrete processors
# ---------------------------------------------------------------------------


class StatusProcessor(Processor):
    """
    Tracks machine execution status.

    Bus slot "status":
    {
        "machine_name": str,
        "execution_id": str,
        "state": str,          # current state name
        "prev_state": str,     # previous state
        "step": int,
        "phase": str,          # "starting" | "running" | "done" | "error"
        "elapsed_s": float,
        "states_visited": [str],
    }
    """

    slot_name = "status"
    event_types = frozenset({
        events.MACHINE_START, events.MACHINE_END,
        events.STATE_ENTER, events.STATE_EXIT,
        events.TRANSITION, events.ERROR,
    })

    def __init__(self, bus: DataBus, max_hz: float = 10.0):
        super().__init__(bus, max_hz)
        self.reset()

    def reset(self) -> None:
        self._machine_name = ""
        self._execution_id = ""
        self._state = ""
        self._prev_state = ""
        self._step = 0
        self._phase = "idle"
        self._start_time = 0.0
        self._states_visited: List[str] = []

    def process(self, event: Dict[str, Any]) -> Any:
        etype = event["type"]

        if etype == events.MACHINE_START:
            self._machine_name = event.get("machine_name", "")
            self._execution_id = event.get("execution_id", "")
            self._phase = "starting"
            self._start_time = time.monotonic()
            self._states_visited = []

        elif etype == events.STATE_ENTER:
            state = event.get("state", "")
            self._state = state
            self._step = event.get("step", self._step)
            self._phase = "running"
            if state and state not in self._states_visited:
                self._states_visited.append(state)

        elif etype == events.STATE_EXIT:
            self._prev_state = event.get("state", self._prev_state)

        elif etype == events.TRANSITION:
            self._prev_state = event.get("from_state", self._prev_state)
            self._state = event.get("to_state", self._state)

        elif etype == events.MACHINE_END:
            self._phase = "done"

        elif etype == events.ERROR:
            self._phase = "error"

        elapsed = time.monotonic() - self._start_time if self._start_time else 0.0

        return {
            "machine_name": self._machine_name,
            "execution_id": self._execution_id,
            "state": self._state,
            "prev_state": self._prev_state,
            "step": self._step,
            "phase": self._phase,
            "elapsed_s": round(elapsed, 2),
            "states_visited": list(self._states_visited),
        }


class TokenProcessor(Processor):
    """
    Tracks token usage and cost.

    Bus slot "tokens":
    {
        "input_tokens": int,
        "output_tokens": int,
        "total_tokens": int,
        "total_cost": float,
        "turns": int,
        "tool_calls_count": int,
    }
    """

    slot_name = "tokens"
    event_types = frozenset({events.TOOL_CALLS, events.MACHINE_START, events.MACHINE_END})

    def __init__(self, bus: DataBus, max_hz: float = 5.0):
        super().__init__(bus, max_hz)
        self.reset()

    def reset(self) -> None:
        self._input_tokens = 0
        self._output_tokens = 0
        self._total_cost = 0.0
        self._turns = 0
        self._tool_calls_count = 0

    def process(self, event: Dict[str, Any]) -> Any:
        etype = event["type"]

        if etype == events.MACHINE_START:
            self.reset()
            return self._snapshot()

        if etype == events.TOOL_CALLS:
            usage = event.get("usage", {})
            self._input_tokens = usage.get("input_tokens", self._input_tokens)
            self._output_tokens = usage.get("output_tokens", self._output_tokens)
            self._total_cost = event.get("cost", self._total_cost)
            self._turns = event.get("turns", self._turns)
            self._tool_calls_count += len(event.get("tool_calls", []))

        if etype == events.MACHINE_END:
            ctx = event.get("context", {})
            self._total_cost = ctx.get("_tool_loop_cost", self._total_cost)

        return self._snapshot()

    def _snapshot(self) -> Dict[str, Any]:
        return {
            "input_tokens": self._input_tokens,
            "output_tokens": self._output_tokens,
            "total_tokens": self._input_tokens + self._output_tokens,
            "total_cost": round(self._total_cost, 6),
            "turns": self._turns,
            "tool_calls_count": self._tool_calls_count,
        }


class ToolProcessor(Processor):
    """
    Tracks tool calls and results.

    Bus slot "tools":
    {
        "active": [{"name": str, "arguments": dict}],
        "last_result": {"name", "arguments", "content", "is_error"} | None,
        "history": [{"name", "is_error", "summary"}],
        "total_calls": int,
        "error_count": int,
        "files_modified": [str],
    }
    """

    slot_name = "tools"
    event_types = frozenset({events.TOOL_CALLS, events.TOOL_RESULT, events.MACHINE_START})

    def __init__(self, bus: DataBus, max_hz: float = 30.0, history_limit: int = 50):
        super().__init__(bus, max_hz)
        self._history_limit = history_limit
        self.reset()

    def reset(self) -> None:
        self._active: List[Dict[str, Any]] = []
        self._last_result: Optional[Dict[str, Any]] = None
        self._history: List[Dict[str, Any]] = []
        self._total_calls = 0
        self._error_count = 0
        self._files_modified: List[str] = []

    def process(self, event: Dict[str, Any]) -> Any:
        etype = event["type"]

        if etype == events.MACHINE_START:
            self.reset()
            return self._snapshot()

        if etype == events.TOOL_CALLS:
            self._active = [
                {
                    "name": tc.get("name", ""),
                    "arguments": tc.get("arguments", {}),
                    "tool_call_id": tc.get("tool_call_id", ""),
                }
                for tc in event.get("tool_calls", [])
            ]

        elif etype == events.TOOL_RESULT:
            name = event.get("name", "")
            args = event.get("arguments", {})
            is_error = event.get("is_error", False)

            self._last_result = {
                "name": name,
                "arguments": args,
                "content": event.get("content", ""),
                "is_error": is_error,
            }

            # Build summary for history
            summary = self._summarize_tool(name, args)
            self._history.append({
                "name": name,
                "is_error": is_error,
                "summary": summary,
            })
            if self._history_limit == 0:
                self._history = []
            elif len(self._history) > self._history_limit:
                self._history = self._history[-self._history_limit:]

            self._total_calls += 1
            if is_error:
                self._error_count += 1

            # Track modified files
            if not is_error and name in ("write", "edit"):
                path = args.get("path", "")
                if path and path not in self._files_modified:
                    self._files_modified.append(path)

            # Remove the matching tool from active. Prefer matching by
            # tool_call_id (exact), fall back to name (first match).
            tool_call_id = event.get("tool_call_id", "")
            removed = False
            new_active = []
            for a in self._active:
                if not removed:
                    if tool_call_id and a.get("tool_call_id") == tool_call_id:
                        removed = True
                        continue
                    elif not tool_call_id and a["name"] == name:
                        removed = True
                        continue
                new_active.append(a)
            self._active = new_active

        return self._snapshot()

    def _snapshot(self) -> Dict[str, Any]:
        return {
            "active": list(self._active),
            "last_result": self._last_result,
            "history": list(self._history),
            "total_calls": self._total_calls,
            "error_count": self._error_count,
            "files_modified": list(self._files_modified),
        }

    @staticmethod
    def _summarize_tool(name: str, args: Dict[str, Any]) -> str:
        if name == "bash":
            cmd = args.get("command", "")
            return f"bash: {cmd[:80]}" if cmd else "bash"
        elif name == "read":
            return f"read: {args.get('path', '')}"
        elif name == "write":
            n = len(args.get("content", ""))
            return f"write: {args.get('path', '')} ({n}B)"
        elif name == "edit":
            return f"edit: {args.get('path', '')}"
        else:
            return f"{name}"


class ContentProcessor(Processor):
    """
    Tracks agent thinking/output text.

    Bus slot "content":
    {
        "text": str,       # latest agent text
        "lines": [str],    # split into lines for rendering
        "has_content": bool,
    }
    """

    slot_name = "content"
    event_types = frozenset({events.TOOL_CALLS, events.MACHINE_START, events.MACHINE_END})

    def __init__(self, bus: DataBus, max_hz: float = 15.0):
        super().__init__(bus, max_hz)
        self.reset()

    def reset(self) -> None:
        self._text = ""

    def process(self, event: Dict[str, Any]) -> Any:
        etype = event["type"]

        if etype == events.MACHINE_START:
            self.reset()
            return self._snapshot()

        if etype == events.TOOL_CALLS:
            content = event.get("content", "")
            if content and content.strip():
                self._text = content.strip()
            else:
                return None  # no update

        if etype == events.MACHINE_END:
            ctx = event.get("context", {})
            result = ctx.get("result", "")
            if result:
                self._text = str(result)

        return self._snapshot()

    def _snapshot(self) -> Dict[str, Any]:
        return {
            "text": self._text,
            "lines": self._text.splitlines() if self._text else [],
            "has_content": bool(self._text),
        }


class ErrorProcessor(Processor):
    """
    Tracks errors.

    Bus slot "error":
    {
        "has_error": bool,
        "state": str,
        "error_type": str,
        "error_message": str,
        "errors": [{"state", "error_type", "error_message"}],
    }
    """

    slot_name = "error"
    event_types = frozenset({events.ERROR, events.MACHINE_START})

    def __init__(self, bus: DataBus, max_hz: float = 10.0):
        super().__init__(bus, max_hz)
        self.reset()

    def reset(self) -> None:
        self._errors: List[Dict[str, str]] = []

    def process(self, event: Dict[str, Any]) -> Any:
        etype = event["type"]

        if etype == events.MACHINE_START:
            self.reset()
            return self._snapshot()

        if etype == events.ERROR:
            entry = {
                "state": event.get("state", ""),
                "error_type": event.get("error_type", ""),
                "error_message": event.get("error_message", ""),
            }
            self._errors.append(entry)

        return self._snapshot()

    def _snapshot(self) -> Dict[str, Any]:
        latest = self._errors[-1] if self._errors else {}
        return {
            "has_error": bool(self._errors),
            "state": latest.get("state", ""),
            "error_type": latest.get("error_type", ""),
            "error_message": latest.get("error_message", ""),
            "errors": list(self._errors),
        }


# --- Default processor set ---

def default_processors(bus: DataBus) -> List[Processor]:
    """Create the standard set of processors with sensible Hz caps."""
    return [
        StatusProcessor(bus, max_hz=10.0),
        TokenProcessor(bus, max_hz=5.0),
        ToolProcessor(bus, max_hz=30.0),
        ContentProcessor(bus, max_hz=15.0),
        ErrorProcessor(bus, max_hz=10.0),
    ]

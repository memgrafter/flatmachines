"""
Frontend protocol — the interface between backend and frontend.

This is the contract that any frontend must implement. The current
Python terminal frontend is temporary; it will be replaced by a Rust
CLI later. Keep this interface minimal and stable.

The frontend protocol is intentionally pull-based (like UDP recv):
- The backend writes data to the DataBus.
- The frontend reads from the DataBus at its own pace.
- The frontend never blocks the backend.

The protocol defines lifecycle hooks and the action callback mechanism
for interactive actions (like human_review) that require frontend I/O.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, Optional

from .bus import DataBus


class Frontend(ABC):
    """
    Abstract frontend interface.

    A frontend renders CLI data from the DataBus. It runs as an
    independent async task, reading bus slots at its own frame rate.

    Lifecycle:
        start(bus) → renders until stop() → cleanup

    For Rust replacement: this maps to a trait with the same methods.
    The DataBus snapshot() dict is the serialization boundary —
    it's a plain dict that maps cleanly to JSON/msgpack for IPC.
    """

    @abstractmethod
    async def start(self, bus: DataBus) -> None:
        """
        Start the frontend render loop.

        The frontend should:
        1. Store a reference to the bus.
        2. Begin its render loop (polling bus.snapshot() at its frame rate).
        3. Return only when stop() is called or execution ends.
        """
        ...

    @abstractmethod
    async def stop(self) -> None:
        """
        Stop the frontend render loop. Called when machine execution ends.
        Should flush any buffered output and clean up.
        """
        ...

    @abstractmethod
    def handle_action(self, action_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle an interactive action (e.g., human_review).

        This is called synchronously from the hooks during machine execution.
        The frontend should perform the interaction (e.g., prompt for input)
        and return the modified context.

        For non-interactive frontends, return context unchanged (auto-approve).

        Args:
            action_name: Name of the action (e.g., "human_review")
            context: Current machine context

        Returns:
            Modified context
        """
        ...

    def on_bus_update(self, slot_name: str, data: Any) -> None:
        """
        Optional callback when a specific bus slot is updated.
        Default is no-op — most frontends will poll via snapshot().

        For event-driven frontends that want push notification.
        """
        pass


class ActionHandler:
    """
    Registry of action handlers.

    Actions are interactive operations that require frontend involvement
    (e.g., human review, confirmation prompts). The backend routes
    action events to registered handlers.

    Default handlers can be overridden per-action.
    """

    def __init__(self):
        self._handlers: Dict[str, Callable] = {}
        self._default: Optional[Callable] = None

    def register(self, action_name: str, handler: Callable) -> None:
        """Register a handler for a specific action name."""
        self._handlers[action_name] = handler

    def set_default(self, handler: Callable) -> None:
        """Set the default handler for unregistered actions."""
        self._default = handler

    def handle(self, action_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Route an action to its handler.

        Falls back to default handler, then to returning context unchanged.
        """
        handler = self._handlers.get(action_name, self._default)
        if handler is not None:
            return handler(action_name, context)
        return context

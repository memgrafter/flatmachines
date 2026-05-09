"""
CLIBackend — orchestrates processors, manages the DataBus, routes events.

The backend is the permanent core of the CLI. It:
1. Owns the DataBus (the shared data surface).
2. Creates and manages async processor tasks.
3. Receives events from CLIHooks and fans them out to processors.
4. Routes interactive actions to the frontend.

The backend runs entirely within the asyncio event loop. No threads,
no subprocess boundaries. The frontend reads from the same DataBus
in the same process (for now — Rust frontend will use IPC later).

Key async guarantees:
- flatmachines execution never blocks on CLI rendering.
- CLI data preparation (processors) never blocks on frontend render.
- Frontend render never blocks on data preparation.
- Each processor runs independently — one slow processor won't block others.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Dict, List, Optional

from .bus import DataBus
from .processors import Processor, default_processors
from .protocol import Frontend, ActionHandler


class CLIBackend:
    """
    Central orchestrator for the CLI data pipeline.

    Usage:
        bus = DataBus()
        backend = CLIBackend(bus=bus)
        backend.set_frontend(my_frontend)

        # Create hooks that bridge flatmachines → backend
        hooks = CLIHooks(backend, tool_provider_factory=...)

        # Start processors before machine execution
        await backend.start()

        # Machine runs, hooks emit events, processors write to bus,
        # frontend reads from bus at its own rate
        result = await machine.execute(input={...})

        # Stop processors after machine execution
        await backend.stop()
    """

    def __init__(
        self,
        bus: Optional[DataBus] = None,
        processors: Optional[List[Processor]] = None,
        frontend: Optional[Frontend] = None,
    ):
        self._bus = bus or DataBus()
        self._processors = processors or default_processors(self._bus)
        self._frontend = frontend
        self._action_handler = ActionHandler()
        self._frontend_task: Optional[asyncio.Task] = None
        self._running = False

    @property
    def bus(self) -> DataBus:
        """The shared data bus. Read by frontends, written by processors."""
        return self._bus

    @property
    def processors(self) -> List[Processor]:
        return self._processors

    @property
    def action_handler(self) -> ActionHandler:
        return self._action_handler

    def set_frontend(self, frontend: Frontend) -> None:
        """
        Attach a frontend. The frontend's action handler will be
        registered as the default action handler.
        """
        self._frontend = frontend
        self._action_handler.set_default(
            lambda action_name, ctx: frontend.handle_action(action_name, ctx)
        )

    def add_processor(self, processor: Processor) -> None:
        """Add a custom processor to the pipeline."""
        self._processors.append(processor)

    def register_action(self, action_name: str, handler: Callable) -> None:
        """Register a handler for a specific action name."""
        self._action_handler.register(action_name, handler)

    # --- Lifecycle ---

    async def start(self) -> None:
        """
        Start all processors and the frontend.
        Call before machine.execute().
        """
        if self._running:
            return

        self._bus.reset()

        # Reset and start all processors
        for proc in self._processors:
            proc.reset()
            proc.start()

        # Start frontend render loop in background
        if self._frontend:
            self._frontend_task = asyncio.ensure_future(
                self._frontend.start(self._bus)
            )

        self._running = True

    async def stop(self) -> None:
        """
        Stop all processors and the frontend.
        Call after machine.execute() returns.
        """
        if not self._running:
            return

        # Stop all processors (they flush pending data)
        for proc in self._processors:
            proc.stop()

        # Wait for processor tasks to finish
        tasks = [p._task for p in self._processors if p._task and not p._task.done()]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        # Stop frontend
        if self._frontend:
            await self._frontend.stop()
        if self._frontend_task and not self._frontend_task.done():
            self._frontend_task.cancel()
            try:
                await self._frontend_task
            except asyncio.CancelledError:
                pass

        self._running = False

    # --- Event dispatch ---

    def emit(self, event: Dict[str, Any]) -> None:
        """
        Broadcast an event to all processors that accept it.

        Called by CLIHooks. Non-blocking — just enqueues.
        Each processor filters by event type in its own task.
        """
        for proc in self._processors:
            if proc.accepts(event):
                proc.enqueue(event)

    # --- Action routing ---

    def handle_action(self, action_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Route an action to its handler (typically the frontend).
        Called synchronously from CLIHooks.on_action().
        """
        return self._action_handler.handle(action_name, context)

    # --- Convenience: run a machine with full lifecycle ---

    async def run_machine(
        self,
        machine,
        input: Optional[Dict[str, Any]] = None,
        **execute_kwargs,
    ) -> Dict[str, Any]:
        """
        Convenience: start backend, execute machine, stop backend.

        Args:
            machine: FlatMachine instance (already configured with CLIHooks)
            input: Machine input dict
            **execute_kwargs: Extra args for machine.execute()

        Returns:
            Machine execution result
        """
        await self.start()
        try:
            result = await machine.execute(input=input, **execute_kwargs)
            return result
        finally:
            await self.stop()

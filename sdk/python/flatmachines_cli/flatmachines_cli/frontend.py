"""
Simple terminal frontend — temporary Python implementation.

This will be replaced by a Rust CLI frontend. The interface contract
is defined in protocol.py (Frontend ABC). This implementation:
- Polls the DataBus at a fixed frame rate.
- Prints to stdout using ANSI escape codes.
- Handles human_review action via input().

The rendering is deliberately simple — just enough to be useful.
The Rust frontend will do proper TUI rendering.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any, Dict, Optional

from .bus import DataBus
from .protocol import Frontend


def _dim(text: str) -> str:
    return f"\033[2m{text}\033[0m"


def _bold(text: str) -> str:
    return f"\033[1m{text}\033[0m"


def _green(text: str) -> str:
    return f"\033[32m{text}\033[0m"


def _red(text: str) -> str:
    return f"\033[31m{text}\033[0m"


def _yellow(text: str) -> str:
    return f"\033[33m{text}\033[0m"


class TerminalFrontend(Frontend):
    """
    Simple line-based terminal frontend.

    Reads from DataBus, prints updates to stdout. No cursor movement,
    no screen clearing — just sequential lines. This keeps it simple
    and compatible with all terminals, pipes, and log capture.
    """

    def __init__(
        self,
        fps: float = 10.0,
        auto_approve: bool = False,
    ):
        self._fps = fps
        self._auto_approve = auto_approve
        self._bus: Optional[DataBus] = None
        self._running = False
        self._last_versions: Dict[str, int] = {}
        # Track what we've already printed to avoid duplicate output
        self._last_tool_call_count = 0
        self._last_content_text = ""
        self._printed_done = False

    async def start(self, bus: DataBus) -> None:
        """Start the render loop. Runs until stop() is called."""
        self._bus = bus
        self._running = True
        self._last_versions = {}
        self._last_tool_call_count = 0
        self._last_content_text = ""
        self._printed_done = False

        while self._running:
            self._render_frame()
            await asyncio.sleep(1.0 / self._fps)

        # Final render to flush any remaining data
        self._render_frame()

    async def stop(self) -> None:
        """Stop the render loop."""
        self._running = False
        # Give one more frame to flush
        await asyncio.sleep(0)

    def handle_action(self, action_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Handle interactive actions."""
        if action_name == "human_review":
            return self._human_review(context)
        return context

    # --- Render logic ---

    def _render_frame(self) -> None:
        """
        One render frame. Check each slot for changes, print updates.

        This is intentionally incremental — we only print what changed
        since the last frame. No screen redraw.
        """
        if self._bus is None:
            return

        versions = self._bus.versions()

        # Content updates (agent thinking)
        self._render_content(versions)

        # Tool updates
        self._render_tools(versions)

        # Status updates (state transitions, phase changes)
        self._render_status(versions)

        # Token updates (periodic)
        self._render_tokens(versions)

        # Error updates
        self._render_errors(versions)

        self._last_versions = dict(versions)

    def _changed(self, slot_name: str, versions: Dict[str, int]) -> bool:
        """Check if a slot has changed since last render frame."""
        current = versions.get(slot_name, 0)
        previous = self._last_versions.get(slot_name, 0)
        return current > previous

    def _render_content(self, versions: Dict[str, int]) -> None:
        if not self._changed("content", versions):
            return
        data = self._bus.read_data("content")
        if not data or not data.get("has_content"):
            return
        text = data["text"]
        if text == self._last_content_text:
            return
        self._last_content_text = text
        print()
        print(_dim(text))

    def _render_tools(self, versions: Dict[str, int]) -> None:
        if not self._changed("tools", versions):
            return
        data = self._bus.read_data("tools")
        if not data:
            return

        # Print new tool results since last render
        history = data.get("history", [])
        new_count = data.get("total_calls", 0)
        if new_count <= self._last_tool_call_count:
            return

        # Print only new entries
        new_entries = history[self._last_tool_call_count:]
        for entry in new_entries:
            status = _red("x") if entry.get("is_error") else _green("v")
            summary = entry.get("summary", "")
            print(f"  {status} {_bold(summary)}")

        self._last_tool_call_count = new_count

    def _render_status(self, versions: Dict[str, int]) -> None:
        if not self._changed("status", versions):
            return
        data = self._bus.read_data("status")
        if not data:
            return

        phase = data.get("phase", "")
        if phase == "done" and not self._printed_done:
            self._printed_done = True
            elapsed = data.get("elapsed_s", 0)
            print()
            print(f"Done ({elapsed:.1f}s)")

    def _render_tokens(self, versions: Dict[str, int]) -> None:
        if not self._changed("tokens", versions):
            return
        data = self._bus.read_data("tokens")
        if not data:
            return
        # Token info is shown inline with content in the coding_machine_cli
        # pattern. Here we just track it — shown on content updates.
        parts = []
        inp = data.get("input_tokens", 0)
        out = data.get("output_tokens", 0)
        if inp or out:
            parts.append(f"tokens: {inp}->{out}")
        cost = data.get("total_cost", 0)
        if cost:
            parts.append(f"${cost:.4f}")
        if parts:
            print(_dim(" | ".join(parts)))

    def _render_errors(self, versions: Dict[str, int]) -> None:
        if not self._changed("error", versions):
            return
        data = self._bus.read_data("error")
        if not data or not data.get("has_error"):
            return
        msg = data.get("error_message", "Unknown error")
        state = data.get("state", "?")
        print(_red(f"Error in {state}: {msg}"))

    # --- Action handlers ---

    def _human_review(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Show agent output, ask for follow-up or accept."""
        result = context.get("result", "")
        if result:
            print()
            print(result)

        files = context.get("files_modified", [])
        if files:
            print()
            print(_dim(f"Files modified: {', '.join(files)}"))

        if self._auto_approve:
            context["human_approved"] = True
            return context

        print()
        try:
            response = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            response = ""

        if response:
            chain = context.get("_tool_loop_chain", [])
            chain.append({"role": "user", "content": response})
            context["_tool_loop_chain"] = chain
            context["human_approved"] = False
        else:
            context["human_approved"] = True

        return context

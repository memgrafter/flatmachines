"""
Machine API Hooks.

Wires the MachineAPIToolProvider into the FlatMachine tool_loop.
This is the glue between the machine runtime and the tool provider.
"""

import json
import sys
from typing import Any, Dict, List

from flatmachines import MachineHooks
from .tools import MachineAPIToolProvider


def _dim(text: str) -> str:
    return f"\033[2m{text}\033[0m"


def _bold(text: str) -> str:
    return f"\033[1m{text}\033[0m"


class MachineAPIHooks(MachineHooks):
    """
    Hooks that provide Machine API tools to the agent in a tool_loop state.

    The hooks:
    1. Create a MachineAPIToolProvider bound to the live machine
    2. Return it via get_tool_provider() so tool_loop uses it
    3. Display tool call results for observability
    """

    def __init__(self):
        self._provider = None

    def on_machine_start(self, context: Dict[str, Any]) -> Dict[str, Any]:
        # Provider is created lazily in get_tool_provider because
        # we need the machine reference which isn't available here
        return context

    def get_tool_provider(self, state_name: str):
        return self._provider

    def set_machine(self, machine):
        """Called by the runner to inject the machine reference."""
        self._provider = MachineAPIToolProvider(machine)

    def on_tool_calls(
        self,
        state_name: str,
        tool_calls: List[Dict[str, Any]],
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Display agent thinking before tool execution."""
        content = context.get("_tool_loop_content")
        if content and content.strip():
            print()
            print(_dim(content.strip()))

        usage = context.get("_tool_loop_usage") or {}
        parts = []
        input_tokens = usage.get("input_tokens")
        output_tokens = usage.get("output_tokens")
        if input_tokens is not None or output_tokens is not None:
            parts.append(f"tokens: {input_tokens or 0} -> {output_tokens or 0}")
        cost = context.get("_tool_loop_cost")
        if cost:
            parts.append(f"${cost:.4f}")
        if parts:
            print(_dim(" | ".join(parts)))

        return context

    def on_tool_result(
        self,
        state_name: str,
        tool_result: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Display each Machine API tool call and its result."""
        name = tool_result.get("name", "")
        args = tool_result.get("arguments", {})
        is_error = tool_result.get("is_error", False)
        content = tool_result.get("content", "")

        # Build a concise label
        if name == "machine_launch":
            label = f"launch: {args.get('machine', '?')}"
        elif name == "machine_invoke":
            label = f"invoke: {args.get('machine', '?')}"
        elif name == "machine_status":
            eid = args.get("execution_id", "?")
            # Shorten execution_id for display
            short = eid.split(":")[-1] if ":" in eid else eid[:12]
            label = f"status: ...{short}"
        elif name == "machine_inspect":
            eid = args.get("execution_id", "?")
            short = eid.split(":")[-1] if ":" in eid else eid[:12]
            label = f"inspect: ...{short}"
        elif name == "context_read":
            key = args.get("key", "(all)")
            label = f"ctx.read: {key}"
        elif name == "context_write":
            label = f"ctx.write: {args.get('key', '?')}"
        elif name == "runtime_info":
            label = "runtime_info"
        elif name == "signal_send":
            label = f"signal: {args.get('channel', '?')}"
        else:
            label = f"{name}: {args}"

        status = "\u2717" if is_error else "\u2713"
        print(f"  {status} {_bold(label)}")

        # Show a brief excerpt of the result for key operations
        if name in ("machine_invoke", "machine_inspect", "machine_status") and content:
            try:
                data = json.loads(content)
                # Show just the key fields
                if "output" in data:
                    output_str = json.dumps(data["output"], default=str)
                    if len(output_str) > 200:
                        output_str = output_str[:200] + "..."
                    print(f"    {_dim(output_str)}")
                elif "status" in data:
                    print(f"    {_dim(data.get('status', ''))}")
            except (json.JSONDecodeError, TypeError):
                pass

        return context

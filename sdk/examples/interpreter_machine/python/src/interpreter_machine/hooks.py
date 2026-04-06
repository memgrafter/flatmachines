"""
Interpreter machine display hooks.

Minimal terminal display for the interpretation process.
"""

from typing import Any, Dict, Optional

from flatmachines import MachineHooks


def _dim(text: str) -> str:
    return f"\033[2m{text}\033[0m"


def _bold(text: str) -> str:
    return f"\033[1m{text}\033[0m"


def _cyan(text: str) -> str:
    return f"\033[36m{text}\033[0m"


def _summarize_tool_input(name: str, input_data: Dict[str, Any]) -> str:
    """Summarize tool input for one-line display."""
    if name == "Bash":
        return input_data.get("command", "")
    if name == "Read":
        return input_data.get("file_path", input_data.get("path", ""))
    if name == "Write":
        path = input_data.get("file_path", input_data.get("path", ""))
        content = input_data.get("content", "")
        return f"{path} ({len(content)} bytes)"
    if name == "Edit":
        return input_data.get("file_path", input_data.get("path", ""))
    for v in input_data.values():
        if isinstance(v, str) and len(v) < 80:
            return v
    return ""


class InterpreterHooks(MachineHooks):
    """Display hooks for the interpreter machine."""

    def on_state_enter(self, state_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        if state_name == "interpret":
            stmt = context.get("statement", "")
            print(f"\n{'─' * 60}")
            print(f"  {_cyan('Interpreting')}: {_bold(stmt[:80])}")
            print(f"{'─' * 60}")
        return context

    def on_state_exit(
        self,
        state_name: str,
        context: Dict[str, Any],
        output: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        if not output:
            return output

        events = context.get("_claude_code_stream_events", [])
        if not events:
            return output

        tool_count = 0
        for event in events:
            etype = event.get("type")

            if etype == "assistant":
                message = event.get("message", {})
                for block in message.get("content", []):
                    if block.get("type") == "tool_use":
                        name = block.get("name", "?")
                        input_data = block.get("input", {})
                        label = _summarize_tool_input(name, input_data)
                        print(f"  ✓ {_bold(name)}: {label}")
                        tool_count += 1

            elif etype == "result":
                usage = event.get("usage", {})
                cost = event.get("total_cost_usd")
                parts = []
                in_tok = usage.get("input_tokens")
                out_tok = usage.get("output_tokens")
                if in_tok is not None or out_tok is not None:
                    parts.append(f"tokens: {in_tok or 0}→{out_tok or 0}")
                if cost:
                    parts.append(f"${cost:.4f}")
                if tool_count:
                    parts.append(f"{tool_count} tools")
                if parts:
                    print(f"  {_dim(' | '.join(parts))}")

        return output

"""
Interpreter machine display hooks.

Real-time terminal display for the interpretation process using
on_agent_stream_event for live tool call / progress streaming.
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
    """Display hooks for the interpreter machine.

    Uses on_agent_stream_event for real-time display of tool calls
    and progress as they happen, rather than replaying after completion.
    """

    def __init__(self) -> None:
        self._tool_count = 0
        self._has_shown_text = False

    def on_state_enter(self, state_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        if state_name == "interpret":
            stmt = context.get("statement", "")
            print(f"\n{'─' * 60}")
            print(f"  {_cyan('Interpreting')}: {_bold(stmt)}")
            print(f"{'─' * 60}")
            self._tool_count = 0
            self._has_shown_text = False
        return context

    def on_agent_stream_event(
        self,
        state_name: str,
        event: Dict[str, Any],
        context: Dict[str, Any],
    ) -> None:
        """Real-time display of Claude Code stream events."""
        etype = event.get("type")

        if etype == "assistant":
            message = event.get("message", {})
            for block in message.get("content", []):
                if block.get("type") == "tool_use":
                    name = block.get("name", "?")
                    input_data = block.get("input", {})
                    label = _summarize_tool_input(name, input_data)
                    print(f"  🔧 {_bold(name)}: {label}")
                    self._tool_count += 1
                elif block.get("type") == "text":
                    text = block.get("text", "").strip()
                    if text and len(text) < 200:
                        if not self._has_shown_text:
                            self._has_shown_text = True
                        print(f"  {_dim(text)}")

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
            if self._tool_count:
                parts.append(f"{self._tool_count} tools")
            if parts:
                print(f"  {_dim(' | '.join(parts))}")

    def on_state_exit(
        self,
        state_name: str,
        context: Dict[str, Any],
        output: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        # All display now happens in real-time via on_agent_stream_event.
        # on_state_exit is kept as a no-op override point.
        return output

"""
Claude Code display hooks.

Replays stream events from AgentResult metadata to show tool use
in the terminal, similar to CLIToolHooks from coding_machine_cli.
"""

from typing import Any, Dict, List, Optional

from flatmachines import MachineHooks


def _dim(text: str) -> str:
    return f"\033[2m{text}\033[0m"


def _bold(text: str) -> str:
    return f"\033[1m{text}\033[0m"


def _summarize_tool_input(name: str, input_data: Dict[str, Any]) -> str:
    """Summarize tool input for one-line display."""
    if name == "Bash":
        return input_data.get("command", "")
    if name == "Read":
        path = input_data.get("file_path", "")
        return path
    if name == "Write":
        path = input_data.get("file_path", input_data.get("path", ""))
        content = input_data.get("content", "")
        return f"{path} ({len(content)} bytes)"
    if name == "Edit":
        path = input_data.get("file_path", input_data.get("path", ""))
        return path
    if name == "Grep":
        return input_data.get("pattern", "")
    if name == "Glob":
        return input_data.get("pattern", "")
    # Fallback: first string value
    for v in input_data.values():
        if isinstance(v, str) and len(v) < 80:
            return v
    return ""


class ClaudeCodeHooks(MachineHooks):
    """Display hooks that replay Claude Code stream events for terminal output."""

    def on_state_enter(self, state_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        print(f"\n{'─' * 60}")
        print(f"  State: {_bold(state_name)}")
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

        # Get stream events from the agent result metadata
        # The machine stores output from output_to_context, but we need
        # the raw stream events which are in the AgentResult metadata.
        # For display, we parse context for any session info.
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
                    elif block.get("type") == "text":
                        text = block.get("text", "").strip()
                        if text and len(text) < 200:
                            print(f"  {_dim(text)}")

            elif etype == "result":
                usage = event.get("usage", {})
                cost = event.get("total_cost_usd")
                parts = []
                in_tok = usage.get("input_tokens")
                out_tok = usage.get("output_tokens")
                cache_read = usage.get("cache_read_input_tokens")
                if in_tok is not None or out_tok is not None:
                    parts.append(f"tokens: {in_tok or 0}→{out_tok or 0}")
                if cache_read:
                    parts.append(f"cache: {cache_read}")
                if cost:
                    parts.append(f"${cost:.4f}")
                if tool_count:
                    parts.append(f"{tool_count} tools")
                if parts:
                    print(f"  {_dim(' | '.join(parts))}")

        return output

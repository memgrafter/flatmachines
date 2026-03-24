"""
Codex CLI display hooks.

Replays stream events and item data from AgentResult metadata
to show tool use and token metrics in the terminal.
"""

from typing import Any, Dict, List, Optional

from flatmachines import MachineHooks


def _dim(text: str) -> str:
    return f"\033[2m{text}\033[0m"


def _bold(text: str) -> str:
    return f"\033[1m{text}\033[0m"


def _summarize_item(item: Dict[str, Any]) -> Optional[str]:
    """One-line summary for a Codex CLI item."""
    itype = item.get("type", "")

    if itype == "command_execution":
        cmd = item.get("command", "")
        exit_code = item.get("exit_code")
        status = f" (exit {exit_code})" if exit_code is not None and exit_code != 0 else ""
        return f"bash: {cmd}{status}"

    if itype == "fileChange":
        path = item.get("path", item.get("file", ""))
        action = item.get("action", "edit")
        return f"{action}: {path}"

    if itype == "agent_message" or itype == "agentMessage":
        text = item.get("text", "")
        if text and len(text) < 200:
            return text
        elif text:
            return text[:197] + "..."
        return None

    # Fallback for unknown item types
    if itype:
        return f"[{itype}]"
    return None


class CodexCliHooks(MachineHooks):
    """Display hooks that replay Codex CLI items for terminal output."""

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

        thread_id = context.get("thread_id", "")
        result_text = context.get("result", "")

        if thread_id:
            print(f"  {_dim(f'thread: {thread_id}')}")

        if result_text and isinstance(result_text, str):
            preview = result_text[:200]
            if len(result_text) > 200:
                preview += "..."
            print(f"  {_dim(preview)}")

        return output

    def on_machine_end(
        self,
        context: Dict[str, Any],
        output: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """Print summary at machine completion."""
        thread_id = context.get("thread_id", "")
        if thread_id:
            print(f"\n  {_dim(f'Final thread: {thread_id}')}")
        return output

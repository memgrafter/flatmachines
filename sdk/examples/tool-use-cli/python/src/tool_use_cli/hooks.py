"""
CLI Tool Use Hooks.

Provides the tool provider, file tracking, and human review.
"""

from typing import Any, Dict

from flatmachines import MachineHooks
from .tools import CLIToolProvider


class CLIToolHooks(MachineHooks):
    """Hooks for CLI tool-use workflow with human review."""

    def __init__(self, working_dir: str = "."):
        self._provider = CLIToolProvider(working_dir)

    def get_tool_provider(self, state_name: str):
        return self._provider

    def on_action(self, action_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        if action_name == "human_review":
            return self._human_review(context)
        return context

    def on_tool_result(self, state_name: str, tool_result: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """Track files modified by write/edit tools."""
        name = tool_result.get("name", "")
        is_error = tool_result.get("is_error", False)

        if not is_error and name in ("write", "edit"):
            path = tool_result.get("arguments", {}).get("path", "")
            if path:
                modified = context.setdefault("files_modified", [])
                if path not in modified:
                    modified.append(path)

        return context

    def _human_review(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Show agent output, ask for follow-up or accept."""
        result = context.get("result", "")
        if result:
            print()
            print(result)
            print()

        files = context.get("files_modified", [])
        if files:
            print(f"Files modified: {', '.join(files)}")
            print()

        try:
            response = input("Follow-up (or Enter to finish): ").strip()
        except (EOFError, KeyboardInterrupt):
            response = ""

        if response:
            context["human_approved"] = False
            context["feedback"] = response
        else:
            context["human_approved"] = True
            context["feedback"] = ""

        return context

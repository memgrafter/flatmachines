"""
CLI Tool Use Hooks.

Provides the tool provider and optional logging for tool calls.
"""

from typing import Any, Dict

from flatmachines import MachineHooks
from .tools import CLIToolProvider


class CLIToolHooks(MachineHooks):
    """Hooks for CLI tool-use workflow."""

    def __init__(self, working_dir: str = "."):
        self._provider = CLIToolProvider(working_dir)

    def get_tool_provider(self, state_name: str):
        return self._provider

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

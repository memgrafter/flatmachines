"""
Tool-as-FlatMachine provider.

Each tool invocation launches an ephemeral FlatMachine, giving every tool call
its own execution_id, hooks lifecycle, error handling, and observability — all
inherited from the FlatMachine runtime for free.

Tools default to ephemeral (no persistence, no checkpoint overhead). Set
``persistence: true`` in a tool machine YAML to make it long-lived — useful
for complex tools like bash that benefit from retry/backoff or multi-state
pipelines.

The parent machine's tool loop sees no difference: it calls
``execute_tool(name, id, args) → ToolResult`` as before. Under the hood,
a child machine is created inline, executed, and its final output mapped
back to a ToolResult.
"""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from flatagents.tools import ToolResult
from flatmachines import FlatMachine
from flatmachines.hooks import MachineHooks

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool action hooks — execute the actual tool logic inside machine states
# ---------------------------------------------------------------------------

class AsyncToolActionHooks(MachineHooks):
    """Hooks that implement tool actions for ephemeral tool machines.

    Each tool machine config uses ``action: tool_<name>`` in its execute
    state. This hooks class routes those actions to the original async
    tool functions, writing results into context for the final state.
    """

    def __init__(self, working_dir: str):
        self._working_dir = working_dir

    async def on_action(self, action_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Dispatch tool actions to async implementations.

        Results are written to context.tool_content / context.tool_is_error
        so the machine's final state can read them via Jinja2 templates.
        """
        from .tools import tool_read, tool_bash, tool_write, tool_edit

        working_dir = context.get("working_dir", self._working_dir)

        if action_name == "tool_bash":
            timeout = context.get("timeout", 30)
            try:
                timeout = int(timeout)
            except (TypeError, ValueError):
                timeout = 30
            result = await tool_bash(working_dir, "", {
                "command": context.get("command", ""),
                "timeout": timeout,
            })
        elif action_name == "tool_read":
            args = {"path": context.get("path", "")}
            if context.get("offset") not in (None, "None"):
                args["offset"] = context["offset"]
            if context.get("limit") not in (None, "None"):
                args["limit"] = context["limit"]
            result = await tool_read(working_dir, "", args)
        elif action_name == "tool_write":
            result = await tool_write(working_dir, "", {
                "path": context.get("path", ""),
                "content": context.get("content", ""),
            })
        elif action_name == "tool_edit":
            result = await tool_edit(working_dir, "", {
                "path": context.get("path", ""),
                "oldText": context.get("oldText", ""),
                "newText": context.get("newText", ""),
            })
        else:
            return context

        # Write results directly into context for the final state to read
        context["tool_content"] = result.content
        context["tool_is_error"] = result.is_error
        return context


# ---------------------------------------------------------------------------
# Tool machine configs registry
# ---------------------------------------------------------------------------

class ToolMachineRegistry:
    """Registry of tool name → machine config.

    Loads YAML configs from a tools directory. Each tool can be:
    - ephemeral (default): no persistence, minimal overhead
    - long-lived: with persistence, retry, multi-state pipelines

    The registry also supports inline configs passed as dicts.
    """

    def __init__(self, tools_dir: Optional[str] = None):
        self._configs: Dict[str, Dict[str, Any]] = {}
        self._tools_dir = tools_dir
        if tools_dir:
            self._load_from_dir(tools_dir)

    def _load_from_dir(self, tools_dir: str) -> None:
        """Load all .yml files from the tools directory."""
        tools_path = Path(tools_dir)
        if not tools_path.is_dir():
            logger.warning(f"Tools directory not found: {tools_dir}")
            return

        for yml_file in sorted(tools_path.glob("*.yml")):
            with open(yml_file) as f:
                config = yaml.safe_load(f)
            # Tool name is the filename stem (bash.yml → bash)
            tool_name = yml_file.stem
            self._configs[tool_name] = config
            tool_type = (config.get("metadata") or {}).get("tool_type", "ephemeral")
            logger.debug(f"Registered tool machine: {tool_name} ({tool_type})")

    def register(self, name: str, config: Dict[str, Any]) -> None:
        """Register a tool machine config by name."""
        self._configs[name] = config

    def get(self, name: str) -> Optional[Dict[str, Any]]:
        """Get a tool machine config by name."""
        return self._configs.get(name)

    def has(self, name: str) -> bool:
        return name in self._configs

    @property
    def tool_names(self) -> List[str]:
        return list(self._configs.keys())

    def is_ephemeral(self, name: str) -> bool:
        """Check if a tool is ephemeral (no persistence)."""
        config = self._configs.get(name)
        if not config:
            return True
        tool_type = (config.get("metadata") or {}).get("tool_type", "ephemeral")
        return tool_type == "ephemeral"


# ---------------------------------------------------------------------------
# ToolMachineProvider — the ToolProvider that launches machines
# ---------------------------------------------------------------------------

class ToolMachineProvider:
    """ToolProvider that launches an ephemeral FlatMachine per tool call.

    Each tool invocation:
    1. Looks up the tool's machine config from the registry
    2. Creates a child FlatMachine with the tool args as input
    3. Executes the machine inline (same event loop, no subprocess)
    4. Maps the machine's final output back to a ToolResult

    The machine gets its own execution_id (derived from the parent's
    execution_id + tool call id), making every tool invocation a
    first-class trackable unit in the execution graph.

    For tools without a machine config, falls back to direct function
    execution via CLIToolProvider.
    """

    def __init__(
        self,
        working_dir: str,
        registry: ToolMachineRegistry,
        parent_execution_id: Optional[str] = None,
    ):
        self.working_dir = os.path.abspath(working_dir)
        self._registry = registry
        self._parent_execution_id = parent_execution_id
        # Fallback for tools without machine configs
        from .tools import CLIToolProvider
        self._fallback = CLIToolProvider(working_dir)
        # Tool action hooks for child machines
        self._tool_hooks = AsyncToolActionHooks(self.working_dir)

    def get_tool_definitions(self) -> list:
        # Definitions come from the agent YAML, not here
        return []

    async def execute_tool(
        self,
        name: str,
        tool_call_id: str,
        arguments: Dict[str, Any],
    ) -> ToolResult:
        """Execute a tool by launching an ephemeral child machine."""
        config = self._registry.get(name)

        if config is None:
            # No machine config for this tool — use direct execution
            logger.debug(f"Tool '{name}' has no machine config, using direct execution")
            return await self._fallback.execute_tool(name, tool_call_id, arguments)

        return await self._execute_as_machine(name, tool_call_id, arguments, config)

    async def _execute_as_machine(
        self,
        name: str,
        tool_call_id: str,
        arguments: Dict[str, Any],
        config: Dict[str, Any],
    ) -> ToolResult:
        """Launch an ephemeral machine for this tool call."""
        # Build execution_id for the child machine
        child_execution_id = self._make_execution_id(name, tool_call_id)

        # Build input: tool arguments + working_dir
        machine_input = {
            **arguments,
            "working_dir": self.working_dir,
        }

        is_ephemeral = self._registry.is_ephemeral(name)

        try:
            machine = FlatMachine(
                config_dict=config,
                hooks=self._tool_hooks,
                _execution_id=child_execution_id,
                _parent_execution_id=self._parent_execution_id,
            )

            # Ephemeral machines: disable checkpoint events to minimize
            # overhead while keeping MemoryBackend for structural correctness
            if is_ephemeral:
                machine.checkpoint_events = set()

            result = await machine.execute(input=machine_input)

            # Map machine output → ToolResult
            if isinstance(result, dict):
                content = result.get("content", str(result))
                is_error = result.get("is_error", False)
                # Handle string "true"/"false" from Jinja2 rendering
                if isinstance(is_error, str):
                    is_error = is_error.lower() in ("true", "1", "yes")
                return ToolResult(content=str(content), is_error=is_error)
            else:
                return ToolResult(content=str(result))

        except Exception as e:
            logger.error(f"Tool machine '{name}' failed: {e}")
            return ToolResult(
                content=f"Tool machine error ({name}): {e}",
                is_error=True,
            )

    def _make_execution_id(self, tool_name: str, tool_call_id: str) -> str:
        """Generate a child execution_id for a tool machine."""
        if self._parent_execution_id:
            return f"{self._parent_execution_id}:tool:{tool_name}:{tool_call_id}"
        # No parent — generate a standalone id
        id_hash = hashlib.md5(
            f"{tool_name}:{tool_call_id}".encode()
        ).hexdigest()[:8]
        return f"tool:{tool_name}:{id_hash}"

"""
MachineAPIToolProvider — reference implementation.

Maps LLM tool calls to FlatMachine runtime primitives. This is the
cross-SDK contract: each SDK implements the same tool names and
parameter shapes, backed by its own MachineInvoker, ResultBackend, etc.

The tool provider is injected into the machine's tool_loop state via
hooks.get_tool_provider(). The agent calls tools like machine_launch,
machine_invoke, context_read — and this provider executes them against
the live runtime.

Designed to be portable: no Python-specific tricks, no closures over
framework internals. The provider holds explicit references to the
runtime components it needs (invoker, persistence, signal backend, etc.).
A Rust/Go/Java SDK would implement the same interface against its own
runtime types.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import yaml

from flatagents.tools import ToolProvider, ToolResult

if TYPE_CHECKING:
    from flatmachines.flatmachine import FlatMachine

logger = logging.getLogger(__name__)


def _load_tool_definitions() -> List[Dict[str, Any]]:
    """Load tool definitions from the canonical YAML file."""
    tools_path = Path(__file__).resolve().parents[4] / "config" / "machine_api_tools.yml"
    with open(tools_path) as f:
        data = yaml.safe_load(f)
    return data.get("tools", [])


class MachineAPIToolProvider:
    """
    ToolProvider that exposes the Machine API as LLM function-call tools.

    Each method maps 1:1 to the MachineAPI interface defined in
    flatagents-runtime.d.ts. The tool names match the YAML definitions
    in config/machine_api_tools.yml.

    Usage:
        provider = MachineAPIToolProvider(machine)
        result = await provider.execute_tool("machine_launch", id, {"machine": "echo", "input": {...}})
    """

    def __init__(self, machine: FlatMachine):
        self._machine = machine
        self._tool_defs: Optional[List[Dict[str, Any]]] = None

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        if self._tool_defs is None:
            self._tool_defs = _load_tool_definitions()
        return self._tool_defs

    async def execute_tool(
        self,
        name: str,
        tool_call_id: str,
        arguments: Dict[str, Any],
    ) -> ToolResult:
        try:
            if name == "context_read":
                return await self._context_read(arguments)
            elif name == "context_write":
                return await self._context_write(arguments)
            elif name == "runtime_info":
                return await self._runtime_info()
            elif name == "machine_launch":
                return await self._machine_launch(arguments)
            elif name == "machine_invoke":
                return await self._machine_invoke(arguments)
            elif name == "machine_status":
                return await self._machine_status(arguments)
            elif name == "machine_inspect":
                return await self._machine_inspect(arguments)
            elif name == "signal_send":
                return await self._signal_send(arguments)
            else:
                return ToolResult(content=f"Unknown tool: {name}", is_error=True)
        except Exception as e:
            logger.exception(f"Machine API tool error: {name}")
            return ToolResult(content=f"Error in {name}: {e}", is_error=True)

    # ------------------------------------------------------------------
    # Tool implementations
    # ------------------------------------------------------------------

    async def _context_read(self, args: Dict[str, Any]) -> ToolResult:
        ctx = self._machine.context
        key = args.get("key")
        if key:
            value = ctx.get(key)
            if value is None:
                return ToolResult(content=f"Key '{key}' not found in context")
            return ToolResult(content=json.dumps(value, indent=2, default=str))

        # Filter out internal keys (prefixed with _)
        public_ctx = {k: v for k, v in ctx.items() if not k.startswith("_")}
        return ToolResult(content=json.dumps(public_ctx, indent=2, default=str))

    async def _context_write(self, args: Dict[str, Any]) -> ToolResult:
        key = args.get("key")
        value = args.get("value")
        if not key:
            return ToolResult(content="Missing required parameter: key", is_error=True)

        self._machine.context[key] = value
        return ToolResult(content=f"Set context.{key} = {json.dumps(value, default=str)}")

    async def _runtime_info(self) -> ToolResult:
        m = self._machine
        config = m._config

        machines = list((config.get("data", {}).get("machines") or {}).keys())
        agents = list((config.get("data", {}).get("agents") or {}).keys())

        info = {
            "machine_name": config.get("data", {}).get("name", "unknown"),
            "execution_id": m.execution_id,
            "current_state": m._current_state,
            "machines": machines,
            "agents": agents,
        }
        return ToolResult(content=json.dumps(info, indent=2, default=str))

    async def _machine_launch(self, args: Dict[str, Any]) -> ToolResult:
        machine_name = args.get("machine")
        input_data = args.get("input", {})
        debug = args.get("debug", False)

        if not machine_name:
            return ToolResult(content="Missing required parameter: machine", is_error=True)

        # Resolve machine config
        target_config = self._resolve_machine(machine_name)
        if target_config is None:
            available = list((self._machine._config.get("data", {}).get("machines") or {}).keys())
            return ToolResult(
                content=f"Machine '{machine_name}' not found. Available: {available}",
                is_error=True,
            )

        execution_id = f"{self._machine.execution_id}:child:{machine_name}:{uuid.uuid4().hex[:8]}"

        if debug:
            # Enable all checkpoint events for debug inspection
            if "data" in target_config:
                target_config.setdefault("data", {})
                target_config["data"].setdefault("persistence", {})
                target_config["data"]["persistence"]["enabled"] = True
                target_config["data"]["persistence"]["checkpoint_on"] = [
                    "machine_start", "state_enter", "execute",
                    "state_exit", "machine_end"
                ]

        # Fire-and-forget via invoker
        invoker = self._machine._invoker
        await invoker.launch(self._machine, target_config, input_data, execution_id)

        # Track in context
        launched = self._machine.context.get("launched_machines", [])
        launched.append({"execution_id": execution_id, "machine": machine_name})
        self._machine.context["launched_machines"] = launched

        return ToolResult(content=json.dumps({
            "execution_id": execution_id,
            "machine": machine_name,
            "status": "launched",
        }, indent=2))

    async def _machine_invoke(self, args: Dict[str, Any]) -> ToolResult:
        machine_name = args.get("machine")
        input_data = args.get("input", {})
        timeout = args.get("timeout")
        debug = args.get("debug", False)

        if not machine_name:
            return ToolResult(content="Missing required parameter: machine", is_error=True)

        target_config = self._resolve_machine(machine_name)
        if target_config is None:
            available = list((self._machine._config.get("data", {}).get("machines") or {}).keys())
            return ToolResult(
                content=f"Machine '{machine_name}' not found. Available: {available}",
                is_error=True,
            )

        execution_id = f"{self._machine.execution_id}:child:{machine_name}:{uuid.uuid4().hex[:8]}"

        if debug:
            if "data" in target_config:
                target_config["data"].setdefault("persistence", {})
                target_config["data"]["persistence"]["enabled"] = True
                target_config["data"]["persistence"]["checkpoint_on"] = [
                    "machine_start", "state_enter", "execute",
                    "state_exit", "machine_end"
                ]

        # Blocking invoke via invoker
        invoker = self._machine._invoker
        result = await invoker.invoke(self._machine, target_config, input_data, execution_id)

        # Track in context
        results = self._machine.context.get("results", {})
        results[execution_id] = result
        self._machine.context["results"] = results

        launched = self._machine.context.get("launched_machines", [])
        launched.append({"execution_id": execution_id, "machine": machine_name, "finished": True})
        self._machine.context["launched_machines"] = launched

        return ToolResult(content=json.dumps({
            "execution_id": execution_id,
            "machine": machine_name,
            "status": "completed",
            "output": result,
        }, indent=2, default=str))

    async def _machine_status(self, args: Dict[str, Any]) -> ToolResult:
        execution_id = args.get("execution_id")
        if not execution_id:
            return ToolResult(content="Missing required parameter: execution_id", is_error=True)

        from flatmachines.backends import make_uri

        # Check if result exists
        uri = make_uri(execution_id, "result")
        result_exists = await self._machine.result_backend.exists(uri)

        if result_exists:
            result = await self._machine.result_backend.read(uri)
            status = {
                "execution_id": execution_id,
                "finished": True,
                "output": result,
            }
        else:
            # Try to read latest checkpoint
            snapshot = await self._load_latest_snapshot(execution_id)
            if snapshot:
                status = {
                    "execution_id": execution_id,
                    "finished": False,
                    "machine_name": snapshot.get("machine_name"),
                    "current_state": snapshot.get("current_state"),
                    "step": snapshot.get("step"),
                    "total_cost": snapshot.get("total_cost"),
                    "total_api_calls": snapshot.get("total_api_calls"),
                }
            else:
                status = {
                    "execution_id": execution_id,
                    "finished": False,
                    "note": "No checkpoint found — machine may still be starting or not using persistence",
                }

        return ToolResult(content=json.dumps(status, indent=2, default=str))

    async def _machine_inspect(self, args: Dict[str, Any]) -> ToolResult:
        execution_id = args.get("execution_id")
        if not execution_id:
            return ToolResult(content="Missing required parameter: execution_id", is_error=True)

        snapshot = await self._load_latest_snapshot(execution_id)
        if snapshot is None:
            # Check result backend as fallback
            from flatmachines.backends import make_uri
            uri = make_uri(execution_id, "result")
            result_exists = await self._machine.result_backend.exists(uri)
            if result_exists:
                result = await self._machine.result_backend.read(uri)
                return ToolResult(content=json.dumps({
                    "execution_id": execution_id,
                    "note": "No checkpoint available, but result found",
                    "output": result,
                }, indent=2, default=str))
            return ToolResult(
                content=f"No checkpoint or result found for execution_id: {execution_id}",
                is_error=True,
            )

        # Filter out very large fields for readability
        inspect_data = dict(snapshot)
        if "tool_loop_state" in inspect_data:
            tls = inspect_data["tool_loop_state"]
            if tls and isinstance(tls, dict):
                chain = tls.get("chain", [])
                if len(chain) > 5:
                    tls["chain"] = f"[{len(chain)} messages — truncated]"
                inspect_data["tool_loop_state"] = tls

        return ToolResult(content=json.dumps(inspect_data, indent=2, default=str))

    async def _signal_send(self, args: Dict[str, Any]) -> ToolResult:
        channel = args.get("channel")
        data = args.get("data", {})
        if not channel:
            return ToolResult(content="Missing required parameter: channel", is_error=True)

        signal_backend = getattr(self._machine, "_signal_backend", None)
        if signal_backend is None:
            return ToolResult(
                content="Signal backend not configured on this machine",
                is_error=True,
            )

        signal_id = await signal_backend.send(channel, data)
        return ToolResult(content=json.dumps({
            "signal_id": signal_id,
            "channel": channel,
            "status": "sent",
        }, indent=2))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_machine(self, machine_name: str) -> Optional[Dict[str, Any]]:
        """Resolve a machine name to its config dict."""
        machines_map = self._machine._config.get("data", {}).get("machines", {})
        ref = machines_map.get(machine_name)
        if ref is None:
            return None

        if isinstance(ref, dict):
            # Inline config
            return ref

        # String path — load YAML
        config_dir = self._machine._config_dir or "."
        path = Path(config_dir) / ref
        if not path.exists():
            return None

        with open(path) as f:
            return yaml.safe_load(f)

    async def _load_latest_snapshot(self, execution_id: str) -> Optional[Dict[str, Any]]:
        """Load the latest checkpoint snapshot for an execution."""
        persistence = self._machine.persistence
        if persistence is None:
            return None

        try:
            # List checkpoints for this execution
            keys = await persistence.list(f"{execution_id}/")
            if not keys:
                return None

            # Load the latest one (last in sorted order)
            latest_key = keys[-1]
            snapshot = await persistence.load(latest_key)
            if snapshot is None:
                return None

            # Convert to dict if it's a dataclass
            if hasattr(snapshot, "__dict__"):
                return vars(snapshot)
            return snapshot
        except Exception as e:
            logger.debug(f"Could not load snapshot for {execution_id}: {e}")
            return None

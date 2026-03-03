"""
MachineHooks - Extensibility points for FlatMachine.

Hooks allow custom logic at key points in machine execution:
- Before/after state entry/exit
- Before/after agent calls
- On transitions
- On errors

Includes built-in LoggingHooks and MetricsHooks implementations.
"""

import logging
import time
from abc import ABC
from typing import Any, Dict, Optional

from . import __version__
from .monitoring import get_logger

logger = get_logger(__name__)

try:
    import httpx
except ImportError:
    httpx = None


class MachineHooks(ABC):
    """
    Base class for machine hooks.
    
    Override methods to customize machine behavior.
    All methods have default implementations that pass through unchanged.
    
    Example:
        from flatmachines import get_logger
        logger = get_logger(__name__)

        class MyHooks(MachineHooks):
            def on_state_enter(self, state_name, context):
                logger.info(f"Entering state: {state_name}")
                return context
                
        machine = FlatMachine(config_file="...", hooks=MyHooks())
    """

    def on_machine_start(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Called when machine execution starts.
        
        Args:
            context: Initial context
            
        Returns:
            Modified context
        """
        return context

    def on_machine_end(self, context: Dict[str, Any], final_output: Dict[str, Any]) -> Dict[str, Any]:
        """
        Called when machine execution ends.
        
        Args:
            context: Final context
            final_output: Output from final state
            
        Returns:
            Modified final output
        """
        return final_output

    def on_state_enter(self, state_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Called before executing a state.
        
        Args:
            state_name: Name of the state being entered
            context: Current context
            
        Returns:
            Modified context
        """
        return context

    def on_state_exit(
        self,
        state_name: str,
        context: Dict[str, Any],
        output: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """
        Called after executing a state.
        
        Args:
            state_name: Name of the state that was executed
            context: Current context
            output: Output from the state (agent output or None)
            
        Returns:
            Modified output
        """
        return output

    def on_transition(
        self,
        from_state: str,
        to_state: str,
        context: Dict[str, Any]
    ) -> str:
        """
        Called when transitioning between states.
        
        Can override the target state.
        
        Args:
            from_state: Source state name
            to_state: Target state name (from transition evaluation)
            context: Current context
            
        Returns:
            Actual target state name (can override)
        """
        return to_state

    def on_error(
        self,
        state_name: str,
        error: Exception,
        context: Dict[str, Any]
    ) -> Optional[str]:
        """
        Called when an error occurs during state execution.
        
        Args:
            state_name: Name of the state where error occurred
            error: The exception that was raised
            context: Current context
            
        Returns:
            State to transition to, or None to re-raise the error
        """
        return None  # Re-raise by default

    def on_action(
        self,
        action_name: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Called for custom hook actions defined in states.
        
        Args:
            action_name: Name of the action to execute
            context: Current context
            
        Returns:
            Modified context
        """
        logger.warning(f"Unhandled action: {action_name}")
        return context

    def on_tool_calls(
        self,
        state_name: str,
        tool_calls: list,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Called BEFORE tool execution in a tool_loop state.

        Fires once per LLM response that contains tool calls.
        ``tool_calls`` is the list of tool call requests from the LLM.

        Use cases:
        - Log/audit what tools the LLM is calling
        - Inject data into context for transition evaluation
        - Set context['_abort_tool_loop'] = True to stop the loop
        - Set context['_skip_tools'] = ['tool_call_id'] to skip specific calls

        Args:
            state_name: Current state name
            tool_calls: List of tool call dicts: [{id, name, arguments}, ...]
            context: Current context

        Returns:
            Modified context
        """
        return context

    def on_tool_result(
        self,
        state_name: str,
        tool_result: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Called AFTER each individual tool execution.

        Fires once per tool call — if the LLM requested 3 tools,
        this fires 3 times. A checkpoint is saved after each call,
        enabling rewind to any specific tool execution point.

        Use cases:
        - Inspect result for safety/compliance
        - Update context based on tool output (e.g., track modified files)
        - Inject steering messages via context['_steering_messages']
        - Set context['_abort_tool_loop'] = True to stop before next tool

        Args:
            state_name: Current state name
            tool_result: Result dict: {tool_call_id, name, arguments, content, is_error}
            context: Current context

        Returns:
            Modified context
        """
        return context

    def get_tool_provider(self, state_name: str):
        """Return tool provider for a state. None = use machine default."""
        return None


class LoggingHooks(MachineHooks):
    """Hooks that log all state transitions."""

    def __init__(self, log_level: int = logging.INFO):
        self.log_level = log_level

    def on_machine_start(self, context: Dict[str, Any]) -> Dict[str, Any]:
        logger.log(self.log_level, "Machine execution started")
        return context

    def on_machine_end(self, context: Dict[str, Any], final_output: Dict[str, Any]) -> Dict[str, Any]:
        logger.log(self.log_level, f"Machine execution ended with output: {final_output}")
        return final_output

    def on_state_enter(self, state_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        logger.log(self.log_level, f"Entering state: {state_name}")
        return context

    def on_state_exit(
        self,
        state_name: str,
        context: Dict[str, Any],
        output: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        logger.log(self.log_level, f"Exiting state: {state_name}")
        return output

    def on_transition(self, from_state: str, to_state: str, context: Dict[str, Any]) -> str:
        logger.log(self.log_level, f"Transition: {from_state} -> {to_state}")
        return to_state

    def on_tool_calls(self, state_name: str, tool_calls: list, context: Dict[str, Any]) -> Dict[str, Any]:
        tool_names = [tc.get("name", "?") for tc in tool_calls]
        logger.log(self.log_level, f"Tool calls in {state_name}: {tool_names}")
        return context

    def on_tool_result(self, state_name: str, tool_result: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        name = tool_result.get("name", "?")
        is_error = tool_result.get("is_error", False)
        status = "ERROR" if is_error else "OK"
        logger.log(self.log_level, f"Tool result in {state_name}: {name} [{status}]")
        return context


class MetricsHooks(MachineHooks):
    """Hooks that track execution metrics."""

    def __init__(self):
        self.state_counts: Dict[str, int] = {}
        self.transition_counts: Dict[str, int] = {}
        self.total_states_executed = 0
        self.error_count = 0

    def on_state_enter(self, state_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        self.state_counts[state_name] = self.state_counts.get(state_name, 0) + 1
        self.total_states_executed += 1
        return context

    def on_transition(self, from_state: str, to_state: str, context: Dict[str, Any]) -> str:
        key = f"{from_state}->{to_state}"
        self.transition_counts[key] = self.transition_counts.get(key, 0) + 1
        return to_state

    def on_error(self, state_name: str, error: Exception, context: Dict[str, Any]) -> Optional[str]:
        self.error_count += 1
        return None

    def get_metrics(self) -> Dict[str, Any]:
        """Get collected metrics."""
        return {
            "state_counts": self.state_counts,
            "transition_counts": self.transition_counts,
            "total_states_executed": self.total_states_executed,
            "error_count": self.error_count,
        }


class CompositeHooks(MachineHooks):
    """Compose multiple hooks together."""

    def __init__(self, *hooks: MachineHooks):
        self.hooks = list(hooks)

    def on_machine_start(self, context: Dict[str, Any]) -> Dict[str, Any]:
        for hook in self.hooks:
            context = hook.on_machine_start(context)
        return context

    def on_machine_end(self, context: Dict[str, Any], final_output: Dict[str, Any]) -> Dict[str, Any]:
        for hook in self.hooks:
            final_output = hook.on_machine_end(context, final_output)
        return final_output

    def on_state_enter(self, state_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        for hook in self.hooks:
            context = hook.on_state_enter(state_name, context)
        return context

    def on_state_exit(
        self,
        state_name: str,
        context: Dict[str, Any],
        output: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        for hook in self.hooks:
            output = hook.on_state_exit(state_name, context, output)
        return output

    def on_transition(self, from_state: str, to_state: str, context: Dict[str, Any]) -> str:
        for hook in self.hooks:
            to_state = hook.on_transition(from_state, to_state, context)
        return to_state

    def on_error(self, state_name: str, error: Exception, context: Dict[str, Any]) -> Optional[str]:
        for hook in self.hooks:
            result = hook.on_error(state_name, error, context)
            if result is not None:
                return result
        return None

    def on_action(self, action_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        for hook in self.hooks:
            context = hook.on_action(action_name, context)
        return context

    def on_tool_calls(self, state_name: str, tool_calls: list, context: Dict[str, Any]) -> Dict[str, Any]:
        for hook in self.hooks:
            context = hook.on_tool_calls(state_name, tool_calls, context)
        return context

    def on_tool_result(self, state_name: str, tool_result: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        for hook in self.hooks:
            context = hook.on_tool_result(state_name, tool_result, context)
        return context

    def get_tool_provider(self, state_name: str):
        for hook in self.hooks:
            provider = hook.get_tool_provider(state_name)
            if provider is not None:
                return provider
        return None


class WebhookHooks(MachineHooks):
    """
    Hooks that dispatch events to an HTTP endpoint.
    
    Requires 'httpx' installed.
    """

    def __init__(
        self,
        endpoint: str,
        timeout: float = 5.0,
        api_key: Optional[str] = None
    ):
        if httpx is None:
            raise ImportError("httpx is required for WebhookHooks")
            
        self.endpoint = endpoint
        self.timeout = timeout
        self.headers = {
            "Content-Type": "application/json",
            "User-Agent": f"FlatAgents/{__version__}"
        }
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"

    async def _send(self, event: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Send event to webhook."""
        data = {"event": event, **payload}
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.endpoint,
                    json=data,
                    headers=self.headers,
                    timeout=self.timeout
                )
                response.raise_for_status()
                if response.status_code == 204:
                    return None
                return response.json()
        except Exception as e:
            logger.error(f"Webhook error ({event}): {e}")
            return None

    async def on_machine_start(self, context: Dict[str, Any]) -> Dict[str, Any]:
        resp = await self._send("machine_start", {"context": context})
        if resp and "context" in resp:
            return resp["context"]
        return context

    async def on_machine_end(self, context: Dict[str, Any], final_output: Dict[str, Any]) -> Dict[str, Any]:
        resp = await self._send("machine_end", {"context": context, "output": final_output})
        if resp and "output" in resp:
            return resp["output"]
        return final_output

    async def on_state_enter(self, state_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        resp = await self._send("state_enter", {"state": state_name, "context": context})
        if resp and "context" in resp:
            return resp["context"]
        return context

    async def on_state_exit(
        self,
        state_name: str,
        context: Dict[str, Any],
        output: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        resp = await self._send("state_exit", {"state": state_name, "context": context, "output": output})
        if resp and "output" in resp:
            return resp["output"]
        return output

    async def on_transition(self, from_state: str, to_state: str, context: Dict[str, Any]) -> str:
        resp = await self._send("transition", {"from": from_state, "to": to_state, "context": context})
        if resp and "to_state" in resp:
            return resp["to_state"]
        return to_state

    async def on_error(self, state_name: str, error: Exception, context: Dict[str, Any]) -> Optional[str]:
        resp = await self._send("error", {
            "state": state_name,
            "error": str(error),
            "error_type": type(error).__name__,
            "context": context
        })
        if resp and "recovery_state" in resp:
            return resp["recovery_state"]
        return None  # Re-raise

    async def on_action(self, action_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        resp = await self._send("action", {"action": action_name, "context": context})
        if resp and "context" in resp:
            return resp["context"]
        return context

    async def on_tool_calls(self, state_name: str, tool_calls: list, context: Dict[str, Any]) -> Dict[str, Any]:
        resp = await self._send("tool_calls", {"state": state_name, "tool_calls": tool_calls, "context": context})
        if resp and "context" in resp:
            return resp["context"]
        return context

    async def on_tool_result(self, state_name: str, tool_result: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        resp = await self._send("tool_result", {"state": state_name, "tool_result": tool_result, "context": context})
        if resp and "context" in resp:
            return resp["context"]
        return context


class HooksRegistry:
    """
    Name-based registry for resolving hooks from machine config.

    Machine configs reference hooks by name (e.g., hooks: "my-hooks").
    The registry maps names to factory classes/functions and resolves
    them at runtime, keeping configs language-agnostic.

    Example:
        registry = HooksRegistry()
        registry.register("my-hooks", MyHooksClass)
        hooks = registry.resolve("my-hooks")
        hooks = registry.resolve({"name": "my-hooks", "args": {"key": "val"}})
        hooks = registry.resolve(["logging", {"name": "my-hooks", "args": {}}])
    """

    def __init__(self):
        self._factories: Dict[str, Any] = {}

    def register(self, name: str, factory) -> None:
        """Register a hooks factory by name."""
        self._factories[name] = factory

    def has(self, name: str) -> bool:
        """Check if a name is registered."""
        return name in self._factories

    def resolve(self, ref) -> MachineHooks:
        """
        Resolve a hooks reference into a MachineHooks instance.

        Args:
            ref: A string name, a dict with 'name' and optional 'args',
                 or a list of either (resolved into CompositeHooks).

        Returns:
            MachineHooks instance

        Raises:
            KeyError: If a referenced name is not registered
        """
        if isinstance(ref, list):
            hooks = [self._resolve_single(entry) for entry in ref]
            return CompositeHooks(*hooks)
        return self._resolve_single(ref)

    def _resolve_single(self, ref) -> MachineHooks:
        if isinstance(ref, str):
            name = ref
            args = {}
        elif isinstance(ref, dict):
            name = ref['name']
            args = ref.get('args', {})
        else:
            raise TypeError(f"Invalid hooks ref type: {type(ref)}")

        if name not in self._factories:
            raise KeyError(f"No hooks registered for name '{name}'. "
                           f"Registered: {list(self._factories.keys())}")

        factory = self._factories[name]
        if args:
            return factory(**args)
        return factory()


__all__ = [
    "MachineHooks",
    "LoggingHooks",
    "MetricsHooks",
    "CompositeHooks",
    "WebhookHooks",
    "HooksRegistry",
]

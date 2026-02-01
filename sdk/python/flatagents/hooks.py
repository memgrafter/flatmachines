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
        from flatagents import get_logger
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

    def on_tool_call(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        context: Dict[str, Any]
    ) -> Any:
        """
        Called when an agent requests a tool call during tool_loop execution.

        Must be implemented to execute tools and return results.
        The result will be sent back to the agent for continued processing.

        Args:
            tool_name: Name of the tool to execute
            arguments: Arguments passed to the tool (parsed from JSON)
            context: Current machine context (read-only, for reference)

        Returns:
            Tool execution result (will be JSON serialized for the agent)

        Raises:
            NotImplementedError: If tool_loop is used without implementing this method

        Example:
            def on_tool_call(self, tool_name, arguments, context):
                if tool_name == "search":
                    return self.search_engine.search(arguments["query"])
                elif tool_name == "read_file":
                    with open(arguments["path"]) as f:
                        return f.read()
                else:
                    raise ValueError(f"Unknown tool: {tool_name}")
        """
        raise NotImplementedError(
            f"on_tool_call not implemented. Cannot execute tool '{tool_name}'. "
            "Implement on_tool_call in your hooks class to use tool_loop."
        )


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

    def on_tool_call(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        context: Dict[str, Any]
    ) -> Any:
        # Try each hook until one handles the tool call
        for hook in self.hooks:
            try:
                return hook.on_tool_call(tool_name, arguments, context)
            except NotImplementedError:
                continue
        # No hook handled it
        raise NotImplementedError(
            f"No hook in composite handles tool '{tool_name}'"
        )


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

    async def on_tool_call(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        context: Dict[str, Any]
    ) -> Any:
        resp = await self._send("tool_call", {
            "tool": tool_name,
            "arguments": arguments,
            "context": context
        })
        if resp and "result" in resp:
            return resp["result"]
        raise NotImplementedError(
            f"Webhook did not return result for tool '{tool_name}'"
        )


__all__ = [
    "MachineHooks",
    "LoggingHooks",
    "MetricsHooks",
    "CompositeHooks",
    "WebhookHooks",
]

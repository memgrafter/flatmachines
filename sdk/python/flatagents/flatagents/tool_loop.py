"""
ToolLoopAgent — runs the LLM tool-call loop.

Composes with FlatAgent: one FlatAgent instance handles each LLM call,
ToolLoopAgent manages the message chain, tool execution, guardrails,
and steering between calls.

Usage:
    from flatagents import FlatAgent
    from flatagents.tool_loop import ToolLoopAgent, Tool, ToolResult, Guardrails

    agent = FlatAgent(config_file="coder.yaml")
    loop = ToolLoopAgent(agent, tools=[...], guardrails=Guardrails(max_turns=10))
    result = await loop.run(task="List Python files in src/")
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, List, Optional, Protocol, Union, runtime_checkable

from .baseagent import FinishReason
from .tools import ToolResult, ToolProvider, SimpleToolProvider


class StopReason(str, Enum):
    """Why the tool loop stopped."""
    COMPLETE = "complete"
    MAX_TOOL_CALLS = "max_tool_calls"
    MAX_TURNS = "max_turns"
    TIMEOUT = "timeout"
    COST_LIMIT = "cost_limit"
    ABORTED = "aborted"
    ERROR = "error"


@dataclass
class Tool:
    """A tool the LLM can call.

    Attributes:
        name: Tool name (must match what the LLM calls).
        description: Human-readable description for the LLM.
        parameters: JSON Schema for the tool's arguments.
        execute: Async callable (tool_call_id, args) -> ToolResult.
    """
    name: str
    description: str
    parameters: Dict[str, Any]
    execute: Callable[..., Awaitable[ToolResult]]


@dataclass
class Guardrails:
    """Configurable limits for the tool loop.

    Numeric guardrails use 0 to mean unlimited/disabled.
    max_turns counts LLM calls, not tool calls.
    """
    max_tool_calls: int = 0
    max_turns: int = 0
    allowed_tools: Optional[List[str]] = None
    denied_tools: Optional[List[str]] = None
    tool_timeout: float = 0.0
    total_timeout: float = 0.0
    max_cost: Optional[float] = 0.0


@dataclass
class AggregateUsage:
    """Aggregated usage across all turns."""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    total_cost: float = 0.0
    api_calls: int = 0


@dataclass
class ToolLoopResult:
    """Result from a complete tool loop execution."""
    content: Optional[str]
    messages: List[Dict[str, Any]]
    tool_calls_count: int
    turns: int
    stop_reason: StopReason
    usage: AggregateUsage
    error: Optional[str] = None


@runtime_checkable
class SteeringProvider(Protocol):
    """Provides mid-loop message injection."""
    async def get_messages(self) -> List[Dict[str, Any]]: ...


# Convenience type for a simple async callback
SteeringCallback = Callable[[], Awaitable[List[Dict[str, Any]]]]


class _CallbackSteering:
    """Adapts a simple callback to the SteeringProvider protocol."""
    def __init__(self, callback: SteeringCallback):
        self._callback = callback

    async def get_messages(self) -> List[Dict[str, Any]]:
        return await self._callback()


def _tools_for_llm(tools: List[Tool]) -> List[Dict[str, Any]]:
    """Convert Tool list to OpenAI function-calling format."""
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            },
        }
        for t in tools
    ]


def _build_tool_result_message(tool_call_id: str, content: str) -> Dict[str, Any]:
    """Build a tool result message for the chain."""
    return {
        "role": "tool",
        "tool_call_id": tool_call_id,
        "content": content,
    }


def _build_assistant_message(response) -> Dict[str, Any]:
    """Build an assistant message dict from an AgentResponse for chain continuation."""
    msg: Dict[str, Any] = {"role": "assistant", "content": response.content or ""}
    if response.tool_calls:
        msg["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.tool,
                    "arguments": _serialize_arguments(tc.arguments),
                },
            }
            for tc in response.tool_calls
        ]
    return msg


def _serialize_arguments(arguments: Any) -> str:
    """Serialize tool call arguments to JSON string."""
    import json
    if isinstance(arguments, str):
        return arguments
    return json.dumps(arguments)


def _map_finish_reason(reason: Optional[FinishReason]) -> tuple[StopReason, Optional[str]]:
    """Map agent finish reason to tool-loop stop reason and optional error text."""
    if reason is None or reason == FinishReason.STOP:
        return StopReason.COMPLETE, None
    if reason == FinishReason.ABORTED:
        return StopReason.ABORTED, "agent aborted"
    if reason == FinishReason.LENGTH:
        return StopReason.ERROR, "model stopped due to max token length"
    if reason == FinishReason.CONTENT_FILTER:
        return StopReason.ERROR, "model output blocked by content filter"
    if reason == FinishReason.ERROR:
        return StopReason.ERROR, "agent returned error finish reason"
    return StopReason.ERROR, f"unexpected finish reason: {reason}"


class ToolLoopAgent:
    """
    Runs the LLM tool-call loop without FlatMachines.

    Composes with FlatAgent: one FlatAgent instance handles each LLM call,
    ToolLoopAgent manages the message chain, tool execution, guardrails,
    and steering between calls.

    For hooks between tool calls, checkpointing, transition evaluation,
    or integration with larger workflows, use a FlatMachine with
    tool_loop on the agent state instead.
    """

    def __init__(
        self,
        agent,  # FlatAgent instance
        tools: Optional[List[Tool]] = None,
        tool_provider: Optional[ToolProvider] = None,
        guardrails: Optional[Guardrails] = None,
        steering: Optional[Union[SteeringProvider, SteeringCallback]] = None,
    ):
        # Resolve tool provider: explicit provider wins, otherwise wrap tools
        if tool_provider is not None:
            self._provider = tool_provider
        elif tools is not None:
            self._provider = SimpleToolProvider(tools)
        else:
            raise ValueError("Either 'tools' or 'tool_provider' must be provided")

        self._agent = agent
        self._tools = tools or []
        self._tools_by_name: Dict[str, Tool] = {t.name: t for t in self._tools}
        self._guardrails = guardrails or Guardrails()
        self._llm_tools = self._provider.get_tool_definitions()

        # Normalize steering to protocol
        if steering is None:
            self._steering: Optional[SteeringProvider] = None
        elif callable(steering) and not isinstance(steering, SteeringProvider):
            self._steering = _CallbackSteering(steering)
        else:
            self._steering = steering

    async def run(self, **input_data) -> ToolLoopResult:
        """Execute the tool loop to completion."""
        guardrails = self._guardrails
        chain: List[Dict[str, Any]] = []
        usage = AggregateUsage()
        tool_calls_count = 0
        turns = 0
        start_time = time.monotonic()
        last_content: Optional[str] = None
        initial_user_prompt: Optional[str] = None

        while True:
            # Check total timeout
            elapsed = time.monotonic() - start_time
            if guardrails.total_timeout > 0 and elapsed >= guardrails.total_timeout:
                return ToolLoopResult(
                    content=last_content, messages=chain,
                    tool_calls_count=tool_calls_count, turns=turns,
                    stop_reason=StopReason.TIMEOUT, usage=usage,
                )

            # Check max turns
            if guardrails.max_turns > 0 and turns >= guardrails.max_turns:
                return ToolLoopResult(
                    content=last_content, messages=chain,
                    tool_calls_count=tool_calls_count, turns=turns,
                    stop_reason=StopReason.MAX_TURNS, usage=usage,
                )

            # Check cost limit
            if guardrails.max_cost is not None and guardrails.max_cost > 0 and usage.total_cost >= guardrails.max_cost:
                return ToolLoopResult(
                    content=last_content, messages=chain,
                    tool_calls_count=tool_calls_count, turns=turns,
                    stop_reason=StopReason.COST_LIMIT, usage=usage,
                )

            # Call LLM
            if turns == 0:
                # First turn: use input_data for template rendering
                response = await self._agent.call(
                    messages=chain if chain else None,
                    tools=self._llm_tools,
                    **input_data,
                )
                initial_user_prompt = getattr(response, "rendered_user_prompt", None)
            else:
                # Subsequent turns: pass chain only (no input_data re-rendering)
                response = await self._agent.call(
                    messages=chain,
                    tools=self._llm_tools,
                )

            turns += 1
            self._accumulate_usage(usage, response)

            # Check for error response
            if response.error is not None:
                return ToolLoopResult(
                    content=response.content, messages=chain,
                    tool_calls_count=tool_calls_count, turns=turns,
                    stop_reason=StopReason.ERROR, usage=usage,
                    error=response.error.message,
                )

            # Seed chain with initial rendered user prompt once.
            if turns == 1 and initial_user_prompt:
                chain.append({"role": "user", "content": initial_user_prompt})

            # Build assistant message and add to chain
            assistant_msg = _build_assistant_message(response)
            chain.append(assistant_msg)
            last_content = response.content

            # If this turn pushed us over budget, stop before any tool side-effects.
            if (
                response.finish_reason == FinishReason.TOOL_USE
                and guardrails.max_cost is not None
                and guardrails.max_cost > 0
                and usage.total_cost >= guardrails.max_cost
            ):
                return ToolLoopResult(
                    content=last_content, messages=chain,
                    tool_calls_count=tool_calls_count, turns=turns,
                    stop_reason=StopReason.COST_LIMIT, usage=usage,
                )

            # Check finish reason
            if response.finish_reason != FinishReason.TOOL_USE:
                stop_reason, finish_error = _map_finish_reason(response.finish_reason)
                return ToolLoopResult(
                    content=last_content, messages=chain,
                    tool_calls_count=tool_calls_count, turns=turns,
                    stop_reason=stop_reason, usage=usage,
                    error=finish_error,
                )

            # We have tool calls — check guardrails before executing
            pending_calls = response.tool_calls or []
            if guardrails.max_tool_calls > 0 and tool_calls_count + len(pending_calls) > guardrails.max_tool_calls:
                return ToolLoopResult(
                    content=last_content, messages=chain,
                    tool_calls_count=tool_calls_count, turns=turns,
                    stop_reason=StopReason.MAX_TOOL_CALLS, usage=usage,
                )

            # Execute tool calls sequentially
            for tc in pending_calls:
                result = await self._execute_tool(tc.id, tc.tool, tc.arguments)
                tool_calls_count += 1
                chain.append(_build_tool_result_message(tc.id, result.content))

            # Check steering
            if self._steering is not None:
                try:
                    steering_messages = await self._steering.get_messages()
                except asyncio.CancelledError:
                    return ToolLoopResult(
                        content=last_content, messages=chain,
                        tool_calls_count=tool_calls_count, turns=turns,
                        stop_reason=StopReason.ABORTED, usage=usage,
                        error="steering cancelled",
                    )
                except Exception as e:
                    return ToolLoopResult(
                        content=last_content, messages=chain,
                        tool_calls_count=tool_calls_count, turns=turns,
                        stop_reason=StopReason.ERROR, usage=usage,
                        error=f"steering provider failed: {e}",
                    )
                for msg in steering_messages:
                    chain.append(msg)

    async def _execute_tool(
        self, tool_call_id: str, name: str, arguments: Dict[str, Any]
    ) -> ToolResult:
        """Execute a single tool call with validation and timeout."""
        guardrails = self._guardrails

        # Check allow/deny
        if guardrails.denied_tools and name in guardrails.denied_tools:
            return ToolResult(content=f"Tool '{name}' is not allowed", is_error=True)
        if guardrails.allowed_tools and name not in guardrails.allowed_tools:
            return ToolResult(content=f"Tool '{name}' is not allowed", is_error=True)

        # Execute via provider with timeout. 0 disables the per-tool timeout.
        try:
            coroutine = self._provider.execute_tool(name, tool_call_id, arguments)
            if guardrails.tool_timeout > 0:
                result = await asyncio.wait_for(coroutine, timeout=guardrails.tool_timeout)
            else:
                result = await coroutine
            return result
        except asyncio.TimeoutError:
            return ToolResult(
                content=f"Tool '{name}' timed out after {guardrails.tool_timeout}s",
                is_error=True,
            )
        except Exception as e:
            return ToolResult(content=f"Error executing '{name}': {e}", is_error=True)

    def _accumulate_usage(self, usage: AggregateUsage, response) -> None:
        """Accumulate usage from an AgentResponse."""
        usage.api_calls += 1
        if response.usage is not None:
            usage.input_tokens += response.usage.input_tokens or 0
            usage.output_tokens += response.usage.output_tokens or 0
            usage.total_tokens += response.usage.total_tokens or 0
            if response.usage.cost is not None:
                usage.total_cost += response.usage.cost.total or 0.0

    def run_sync(self, **input_data) -> ToolLoopResult:
        """Synchronous wrapper for run()."""
        return asyncio.run(self.run(**input_data))


__all__ = [
    "ToolLoopAgent",
    "Tool",
    "ToolResult",
    "Guardrails",
    "ToolLoopResult",
    "AggregateUsage",
    "StopReason",
    "SteeringProvider",
    "SteeringCallback",
]

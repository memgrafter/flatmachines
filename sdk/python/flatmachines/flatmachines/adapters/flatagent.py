"""FlatAgent adapter for FlatMachines."""

from __future__ import annotations

from typing import Any, Dict, Optional

from ..agents import (
    AgentAdapter,
    AgentAdapterContext,
    AgentExecutor,
    AgentRef,
    AgentResult,
    AgentErrorDict,
    RateLimitState,
    ProviderData,
    UsageInfo,
    CostInfo,
    build_rate_limit_state,
)

try:
    from flatagents.flatagent import FlatAgent
    from flatagents.profiles import (
        discover_profiles_file,
        load_profiles_from_file,
        resolve_profiles_with_fallback,
    )
except ImportError as exc:  # pragma: no cover - optional dependency
    raise ImportError("flatagents is required for FlatAgentAdapter") from exc


def _map_error_code(error_type: str, status_code: Optional[int]) -> str:
    """Map error type/status to a known error code."""
    if status_code == 429:
        return "rate_limit"
    if status_code == 401 or status_code == 403:
        return "auth_error"
    if status_code == 400:
        return "invalid_request"
    if status_code and 500 <= status_code < 600:
        return "server_error"
    
    # Check error type name
    error_lower = error_type.lower()
    if "ratelimit" in error_lower or "rate_limit" in error_lower:
        return "rate_limit"
    if "timeout" in error_lower:
        return "timeout"
    if "content" in error_lower and "filter" in error_lower:
        return "content_filter"
    if "context" in error_lower and "length" in error_lower:
        return "context_length"
    
    return "server_error"  # Default


class FlatAgentExecutor(AgentExecutor):
    def __init__(self, agent: FlatAgent):
        self._agent = agent

    @property
    def metadata(self) -> Dict[str, Any]:
        return getattr(self._agent, "metadata", {})

    def _map_response(self, response, delta_calls: int, delta_cost: float) -> AgentResult:
        """Map a FlatAgent AgentResponse to a FlatMachines AgentResult."""
        from typing import List as _List

        # Build usage info
        usage: Optional[UsageInfo] = None
        if response.usage:
            usage = {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
                "total_tokens": response.usage.total_tokens,
                "cache_read_tokens": response.usage.cache_read_tokens,
                "cache_write_tokens": response.usage.cache_write_tokens,
                "api_calls": delta_calls,
            }
        elif delta_calls:
            usage = {"api_calls": delta_calls}

        # Build cost info
        cost: Optional[CostInfo] = None
        if response.usage and response.usage.cost:
            cost = {
                "input": response.usage.cost.input,
                "output": response.usage.cost.output,
                "cache_read": response.usage.cost.cache_read,
                "cache_write": response.usage.cost.cache_write,
                "total": response.usage.cost.total,
            }
        elif delta_cost:
            cost = {"total": delta_cost}

        # Build error info
        error: Optional[AgentErrorDict] = None
        if response.error:
            error = {
                "code": _map_error_code(response.error.error_type, response.error.status_code),
                "type": response.error.error_type,
                "message": response.error.message,
                "retryable": response.error.retryable,
            }
            if response.error.status_code:
                error["status_code"] = response.error.status_code

        # Build rate limit state
        rate_limit: Optional[RateLimitState] = None
        raw_headers: Dict[str, str] = {}
        if response.rate_limit:
            raw_headers = response.rate_limit.raw_headers or {}
            retry_after = response.rate_limit.retry_after

            rate_limit = build_rate_limit_state(raw_headers, retry_after)

            # Also check the normalized fields if windows didn't find anything
            if not rate_limit.get("windows"):
                if response.rate_limit.remaining_requests is not None or \
                   response.rate_limit.remaining_tokens is not None:
                    windows = []
                    if response.rate_limit.remaining_requests is not None:
                        windows.append({
                            "name": "requests",
                            "resource": "requests",
                            "remaining": response.rate_limit.remaining_requests,
                            "limit": response.rate_limit.limit_requests,
                        })
                    if response.rate_limit.remaining_tokens is not None:
                        windows.append({
                            "name": "tokens",
                            "resource": "tokens",
                            "remaining": response.rate_limit.remaining_tokens,
                            "limit": response.rate_limit.limit_tokens,
                        })
                    if windows:
                        rate_limit["windows"] = windows

            # Update limited flag from normalized fields if not set by windows
            if not rate_limit["limited"]:
                rate_limit["limited"] = response.rate_limit.is_limited()

        # Build provider data
        provider_data: Optional[ProviderData] = {
            "provider": getattr(self._agent, "provider", None),
            "model": getattr(self._agent, "model", None),
        }
        if raw_headers:
            provider_data["raw_headers"] = raw_headers
        # Clean up None values
        provider_data = {k: v for k, v in provider_data.items() if v is not None}
        if not provider_data:
            provider_data = None

        # Map finish reason
        finish_reason: Optional[str] = None
        if response.finish_reason:
            finish_reason = response.finish_reason.value
        elif response.error:
            finish_reason = "error"

        # Map tool_calls from ToolCall objects to plain dicts
        tool_calls = None
        if response.tool_calls:
            tool_calls = [
                {"id": tc.id, "name": tc.tool, "arguments": tc.arguments}
                for tc in response.tool_calls
            ]

        return AgentResult(
            output=response.output,
            content=response.content,
            raw=response,
            usage=usage,
            cost=cost,
            metadata=getattr(self._agent, "metadata", None),
            finish_reason=finish_reason,
            error=error,
            rate_limit=rate_limit,
            provider_data=provider_data,
            tool_calls=tool_calls,
            rendered_user_prompt=getattr(response, "rendered_user_prompt", None),
        )

    async def execute(
        self,
        input_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> AgentResult:
        pre_calls = self._agent.total_api_calls
        pre_cost = self._agent.total_cost

        response = await self._agent.call(**input_data)

        delta_calls = self._agent.total_api_calls - pre_calls
        delta_cost = self._agent.total_cost - pre_cost

        return self._map_response(response, delta_calls, delta_cost)

    async def execute_with_tools(
        self,
        input_data: Dict[str, Any],
        tools: list,
        messages: Optional[list] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> AgentResult:
        pre_calls = self._agent.total_api_calls
        pre_cost = self._agent.total_cost

        # Pass execution_id as session_id so the Codex backend can set
        # prompt_cache_key, enabling KV-cache hits across continuation turns.
        extra: Dict[str, Any] = {}
        if context and self._agent._backend == "codex":
            execution_id = context.get("execution_id")
            if execution_id and not self._agent._model_config.get("codex_session_id"):
                extra["session_id"] = str(execution_id)

        response = await self._agent.call(
            tools=tools,
            messages=messages,
            **input_data,
            **extra,
        )

        delta_calls = self._agent.total_api_calls - pre_calls
        delta_cost = self._agent.total_cost - pre_cost

        return self._map_response(response, delta_calls, delta_cost)


class FlatAgentAdapter(AgentAdapter):
    type_name = "flatagent"

    def create_executor(
        self,
        *,
        agent_name: str,
        agent_ref: AgentRef,
        context: AgentAdapterContext,
    ) -> AgentExecutor:
        profiles_file = discover_profiles_file(context.config_dir, context.profiles_file)
        own_profiles = load_profiles_from_file(profiles_file) if profiles_file else None
        profiles_dict = resolve_profiles_with_fallback(own_profiles, context.profiles_dict)

        if agent_ref.ref:
            return FlatAgentExecutor(
                FlatAgent(
                    config_file=self._resolve_ref(agent_ref.ref, context),
                    profiles_dict=profiles_dict,
                )
            )
        if agent_ref.config:
            return FlatAgentExecutor(
                FlatAgent(
                    config_dict=agent_ref.config,
                    profiles_dict=profiles_dict,
                )
            )
        raise ValueError(f"FlatAgent reference missing ref/config for agent '{agent_name}'")

    def _resolve_ref(self, ref: str, context: AgentAdapterContext) -> str:
        import os

        if os.path.isabs(ref):
            return ref
        return os.path.join(context.config_dir, ref)

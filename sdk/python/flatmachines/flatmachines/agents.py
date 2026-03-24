"""Agent executor interfaces and adapter registry for FlatMachines."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Protocol, Union

# TypedDict requires Python 3.8+, use regular dicts with documentation for compatibility
# These type aliases document the expected structure


# =============================================================================
# Agent Result Types (see flatagents-runtime.d.ts for canonical spec)
# =============================================================================

# UsageInfo: Token usage metrics
# {
#     "input_tokens": int,
#     "output_tokens": int,
#     "total_tokens": int,
#     "cache_read_tokens": int,
#     "cache_write_tokens": int,
# }
UsageInfo = Dict[str, Any]

# CostInfo: Cost breakdown
# {
#     "input": float,
#     "output": float,
#     "cache_read": float,
#     "cache_write": float,
#     "total": float,
# }
CostInfo = Dict[str, float]

# AgentError: Structured error info (serializable across process/network)
# {
#     "code": str,        # Known: "rate_limit", "timeout", "server_error", 
#                         # "invalid_request", "auth_error", "content_filter",
#                         # "context_length", "model_unavailable"
#     "type": str,        # Original error type name
#     "message": str,     # Human-readable message
#     "status_code": int, # HTTP status code
#     "retryable": bool,  # Whether retry might succeed
# }
AgentErrorDict = Dict[str, Any]

# RateLimitWindow: Per-window rate limit state
# {
#     "name": str,        # e.g., "requests_per_minute", "tokens_per_day"
#     "resource": str,    # Known: "requests", "tokens", "input_tokens", "output_tokens"
#     "remaining": int,
#     "limit": int,
#     "resets_in": int,   # Seconds until reset
#     "reset_at": float,  # Unix timestamp
# }
RateLimitWindow = Dict[str, Any]

# RateLimitState: Normalized rate limit state for orchestration
# {
#     "limited": bool,           # Is any limit exhausted?
#     "retry_after": int,        # Recommended wait (seconds)
#     "windows": List[RateLimitWindow],
# }
RateLimitState = Dict[str, Any]

# ProviderData: Provider-specific data including raw headers
# {
#     "provider": str,
#     "model": str,
#     "request_id": str,
#     "raw_headers": Dict[str, str],
#     ...any other provider-specific fields
# }
ProviderData = Dict[str, Any]


@dataclass
class AgentResult:
    """
    Universal result contract for agent execution.
    
    All fields use structured data (dicts) for cross-language and
    cross-process/network compatibility. See flatagents-runtime.d.ts
    for the canonical interface specification.
    """

    # Content
    output: Optional[Dict[str, Any]] = None
    content: Optional[str] = None
    raw: Any = None  # In-process only, not serialized
    
    # Metrics
    usage: Optional[UsageInfo] = None
    cost: Optional[Union[CostInfo, float]] = None  # float for backwards compat
    metadata: Optional[Dict[str, Any]] = None
    
    # Completion status
    # Known values: "stop", "length", "tool_use", "error", "content_filter", "aborted"
    finish_reason: Optional[str] = None
    
    # Error info (None = success)
    error: Optional[AgentErrorDict] = None
    
    # Rate limit state (normalized for orchestration)
    rate_limit: Optional[RateLimitState] = None
    
    # Provider-specific data (includes raw_headers when available)
    provider_data: Optional[ProviderData] = None

    # Tool use fields
    tool_calls: Optional[List[Dict[str, Any]]] = None
    rendered_user_prompt: Optional[str] = None

    @property
    def success(self) -> bool:
        """Whether the agent call succeeded (no error)."""
        return self.error is None

    def output_payload(self) -> Dict[str, Any]:
        """Get output as dict, falling back to content wrapper."""
        if self.output is not None:
            return self.output
        if self.content is not None:
            return {"content": self.content}
        return {}


class AgentExecutor(Protocol):
    """Protocol for running a single agent call."""

    async def execute(
        self,
        input_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
    ) -> AgentResult:
        ...

    async def execute_with_tools(
        self,
        input_data: Dict[str, Any],
        tools: List[Dict[str, Any]],
        messages: Optional[List[Dict[str, Any]]] = None,
        context: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
    ) -> AgentResult:
        """
        Execute a single LLM call with tool definitions and optional
        conversation chain. Used by the machine's tool loop.

        Args:
            input_data: Input for template rendering (first call only)
            tools: Tool definitions in OpenAI function-calling format
            messages: Conversation chain for continuation (subsequent calls)
            context: Machine context (read-only, for adapter use)
            session_id: Cache key for prompt prefix caching. The machine
                generates this and passes it explicitly — adapters forward
                it to the backend (e.g. as prompt_cache_key for codex).

        Returns:
            AgentResult with tool_calls populated if LLM requested tools,
            finish_reason="tool_use" when tools requested,
            rendered_user_prompt on first call for chain seeding.
        """
        raise NotImplementedError

    @property
    def metadata(self) -> Dict[str, Any]:  # Optional metadata for execution strategies
        ...


@dataclass
class AgentRef:
    """Normalized agent reference for adapter resolution."""

    type: str
    ref: Optional[str] = None
    config: Optional[Dict[str, Any]] = None


@dataclass
class AgentAdapterContext:
    config_dir: str
    settings: Dict[str, Any]
    machine_name: str
    profiles_file: Optional[str] = None
    profiles_dict: Optional[Dict[str, Any]] = None


class AgentAdapter(Protocol):
    """Adapter interface used to build agent executors."""

    type_name: str

    def create_executor(
        self,
        *,
        agent_name: str,
        agent_ref: AgentRef,
        context: AgentAdapterContext,
    ) -> AgentExecutor:
        ...


class AgentAdapterRegistry:
    """Registry mapping adapter type names to adapter instances."""

    def __init__(self, adapters: Optional[Iterable[AgentAdapter]] = None):
        self._adapters: Dict[str, AgentAdapter] = {}
        if adapters:
            for adapter in adapters:
                self.register(adapter)

    def register(self, adapter: AgentAdapter) -> None:
        self._adapters[adapter.type_name] = adapter

    def get(self, type_name: str) -> AgentAdapter:
        if type_name not in self._adapters:
            raise KeyError(f"No agent adapter registered for type '{type_name}'")
        return self._adapters[type_name]

    def create_executor(
        self,
        *,
        agent_name: str,
        agent_ref: AgentRef,
        context: AgentAdapterContext,
    ) -> AgentExecutor:
        adapter = self.get(agent_ref.type)
        return adapter.create_executor(
            agent_name=agent_name,
            agent_ref=agent_ref,
            context=context,
        )


DEFAULT_AGENT_TYPE = "flatagent"


def normalize_agent_ref(raw_ref: Any) -> AgentRef:
    """Normalize agent reference into AgentRef.

    Backward compatibility:
      - string -> type=flatagent, ref=string
      - dict with spec: flatagent -> type=flatagent, config=dict
    """
    if isinstance(raw_ref, str):
        return AgentRef(type=DEFAULT_AGENT_TYPE, ref=raw_ref)

    if isinstance(raw_ref, dict):
        if "type" in raw_ref:
            return AgentRef(
                type=raw_ref["type"],
                ref=raw_ref.get("ref"),
                config=raw_ref.get("config"),
            )

        if raw_ref.get("spec") == "flatagent":
            return AgentRef(type=DEFAULT_AGENT_TYPE, config=raw_ref)

    raise ValueError(
        "Invalid agent reference. Expected string path or {type, ref/config}."
    )


def coerce_agent_result(value: Any) -> AgentResult:
    """Coerce a value to AgentResult, preserving structured fields if present."""
    if isinstance(value, AgentResult):
        return value
    if isinstance(value, dict):
        # Check if this looks like an AgentResult dict (has known fields)
        known_fields = {"output", "content", "raw", "usage", "cost", "metadata",
                        "finish_reason", "error", "rate_limit", "provider_data",
                        "tool_calls", "rendered_user_prompt"}
        if any(k in value for k in known_fields):
            return AgentResult(
                output=value.get("output"),
                content=value.get("content"),
                raw=value.get("raw"),
                usage=value.get("usage"),
                cost=value.get("cost"),
                metadata=value.get("metadata"),
                finish_reason=value.get("finish_reason"),
                error=value.get("error"),
                rate_limit=value.get("rate_limit"),
                provider_data=value.get("provider_data"),
                tool_calls=value.get("tool_calls"),
                rendered_user_prompt=value.get("rendered_user_prompt"),
            )
        # Otherwise treat as output dict
        return AgentResult(output=value, raw=value)
    if value is None:
        return AgentResult()
    return AgentResult(content=str(value), raw=value)


# =============================================================================
# Rate Limit Window Builders
# =============================================================================

def build_rate_limit_windows(raw_headers: Dict[str, str]) -> List[RateLimitWindow]:
    """
    Build rate limit windows from raw HTTP headers.
    
    Parses headers from multiple providers:
    - Cerebras: x-ratelimit-remaining-{requests,tokens}-{minute,hour,day}
    - OpenAI: x-ratelimit-remaining-{requests,tokens}, x-ratelimit-reset-{requests,tokens}
    - Anthropic: anthropic-ratelimit-{requests,tokens}-{remaining,limit,reset}
    
    Returns:
        List of RateLimitWindow dicts for orchestration
    """
    windows: List[RateLimitWindow] = []
    
    # Cerebras time-bucketed limits
    for bucket in ["minute", "hour", "day"]:
        for resource in ["requests", "tokens"]:
            remaining_key = f"x-ratelimit-remaining-{resource}-{bucket}"
            limit_key = f"x-ratelimit-limit-{resource}-{bucket}"
            
            remaining = _parse_int_header(raw_headers, remaining_key)
            limit = _parse_int_header(raw_headers, limit_key)
            
            if remaining is not None or limit is not None:
                window: RateLimitWindow = {
                    "name": f"{resource}_per_{bucket}",
                    "resource": resource,
                }
                if remaining is not None:
                    window["remaining"] = remaining
                if limit is not None:
                    window["limit"] = limit
                # Estimate resets_in based on bucket
                if bucket == "minute":
                    window["resets_in"] = 60
                elif bucket == "hour":
                    window["resets_in"] = 3600
                elif bucket == "day":
                    window["resets_in"] = 86400
                windows.append(window)
    
    # OpenAI-style limits (no time bucket, general limits)
    for resource in ["requests", "tokens"]:
        remaining_key = f"x-ratelimit-remaining-{resource}"
        limit_key = f"x-ratelimit-limit-{resource}"
        reset_key = f"x-ratelimit-reset-{resource}"
        
        remaining = _parse_int_header(raw_headers, remaining_key)
        limit = _parse_int_header(raw_headers, limit_key)
        reset_str = raw_headers.get(reset_key)
        
        # Only add if we have data and didn't already add from Cerebras buckets
        if remaining is not None or limit is not None:
            # Check if we already have this resource from Cerebras
            existing = [w for w in windows if w["resource"] == resource]
            if not existing:
                window: RateLimitWindow = {
                    "name": resource,
                    "resource": resource,
                }
                if remaining is not None:
                    window["remaining"] = remaining
                if limit is not None:
                    window["limit"] = limit
                if reset_str:
                    resets_in = _parse_duration_string(reset_str)
                    if resets_in is not None:
                        window["resets_in"] = resets_in
                windows.append(window)
    
    # Anthropic-style limits
    for resource in ["requests", "tokens"]:
        remaining_key = f"anthropic-ratelimit-{resource}-remaining"
        limit_key = f"anthropic-ratelimit-{resource}-limit"
        reset_key = f"anthropic-ratelimit-{resource}-reset"
        
        remaining = _parse_int_header(raw_headers, remaining_key)
        limit = _parse_int_header(raw_headers, limit_key)
        reset_str = raw_headers.get(reset_key)
        
        if remaining is not None or limit is not None:
            window: RateLimitWindow = {
                "name": resource,
                "resource": resource,
            }
            if remaining is not None:
                window["remaining"] = remaining
            if limit is not None:
                window["limit"] = limit
            if reset_str:
                reset_at = _parse_iso_timestamp(reset_str)
                if reset_at is not None:
                    window["reset_at"] = reset_at
            windows.append(window)
    
    return windows


def build_rate_limit_state(
    raw_headers: Dict[str, str],
    retry_after: Optional[int] = None,
) -> RateLimitState:
    """
    Build a RateLimitState dict from raw headers.
    
    Args:
        raw_headers: Normalized (lowercase) HTTP headers
        retry_after: Optional retry-after value (seconds)
    
    Returns:
        RateLimitState dict for orchestration
    """
    windows = build_rate_limit_windows(raw_headers)
    
    # Check if any window is exhausted
    limited = any(w.get("remaining") == 0 for w in windows)
    
    # Get retry_after from headers if not provided
    if retry_after is None:
        retry_after = _parse_int_header(raw_headers, "retry-after")
    
    state: RateLimitState = {
        "limited": limited,
    }
    
    if retry_after is not None:
        state["retry_after"] = retry_after
    
    if windows:
        state["windows"] = windows
    
    return state


def _parse_int_header(headers: Dict[str, str], key: str) -> Optional[int]:
    """Parse an integer header value."""
    val = headers.get(key) or headers.get(key.lower())
    if val is not None:
        try:
            return int(val)
        except (ValueError, TypeError):
            pass
    return None


def _parse_duration_string(val: str) -> Optional[int]:
    """
    Parse OpenAI duration strings like "6m30s", "1h", "500ms".
    Returns total seconds (rounds up for sub-second).
    """
    import math
    
    val = val.strip()
    if not val:
        return None
    
    total_seconds = 0.0
    current_num = ""
    
    i = 0
    while i < len(val):
        char = val[i]
        
        if char.isdigit() or char == '.':
            current_num += char
            i += 1
        elif char in 'hms':
            if current_num:
                num = float(current_num)
                if char == 'h':
                    total_seconds += num * 3600
                elif char == 'm':
                    # Check for 'ms' (milliseconds)
                    if i + 1 < len(val) and val[i + 1] == 's':
                        total_seconds += num / 1000
                        i += 1
                    else:
                        total_seconds += num * 60
                elif char == 's':
                    total_seconds += num
                current_num = ""
            i += 1
        else:
            i += 1
    
    if current_num:
        try:
            total_seconds += float(current_num)
        except ValueError:
            pass
    
    return math.ceil(total_seconds) if total_seconds > 0 else None


def _parse_iso_timestamp(val: str) -> Optional[float]:
    """Parse ISO 8601 timestamp to Unix timestamp."""
    from datetime import datetime
    
    val = val.strip()
    for fmt in [
        '%Y-%m-%dT%H:%M:%S.%fZ',
        '%Y-%m-%dT%H:%M:%SZ',
        '%Y-%m-%dT%H:%M:%S%z',
        '%Y-%m-%dT%H:%M:%S',
    ]:
        try:
            dt = datetime.strptime(val, fmt)
            return dt.timestamp()
        except ValueError:
            continue
    return None

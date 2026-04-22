"""Internal compatibility types for migrated runtime adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Union

StreamEventCallback = Optional[Callable[[Dict[str, Any]], None]]

UsageInfo = Dict[str, Any]
CostInfo = Dict[str, float]
AgentErrorDict = Dict[str, Any]
RateLimitState = Dict[str, Any]
ProviderData = Dict[str, Any]


@dataclass
class AgentResult:
    output: Optional[Dict[str, Any]] = None
    content: Optional[str] = None
    raw: Any = None
    usage: Optional[UsageInfo] = None
    cost: Optional[Union[CostInfo, float]] = None
    metadata: Optional[Dict[str, Any]] = None
    finish_reason: Optional[str] = None
    error: Optional[AgentErrorDict] = None
    rate_limit: Optional[RateLimitState] = None
    provider_data: Optional[ProviderData] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    rendered_user_prompt: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.error is None

    def output_payload(self) -> Dict[str, Any]:
        if self.output is not None:
            return self.output
        if self.content is not None:
            return {"content": self.content}
        return {}

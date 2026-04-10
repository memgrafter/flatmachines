from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class CopilotOAuthCredential:
    access: str
    refresh: str
    expires: int
    enterprise_url: Optional[str] = None
    base_url: Optional[str] = None


@dataclass
class CopilotUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


@dataclass
class CopilotToolCall:
    id: str
    name: str
    arguments_json: str


@dataclass
class CopilotResult:
    content: str = ""
    tool_calls: List[CopilotToolCall] = field(default_factory=list)
    usage: CopilotUsage = field(default_factory=CopilotUsage)
    finish_reason: Optional[str] = None
    raw_response: Dict[str, Any] = field(default_factory=dict)
    response_headers: Dict[str, str] = field(default_factory=dict)
    response_status_code: Optional[int] = None
    request_meta: Dict[str, Any] = field(default_factory=dict)

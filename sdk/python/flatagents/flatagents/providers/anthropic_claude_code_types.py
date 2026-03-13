from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ClaudeCodeOAuthCredential:
    access: str
    refresh: str
    expires: int


@dataclass
class ClaudeCodeUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


@dataclass
class ClaudeCodeToolCall:
    id: str
    name: str
    arguments_json: str


@dataclass
class ClaudeCodeResult:
    content: str = ""
    tool_calls: List[ClaudeCodeToolCall] = field(default_factory=list)
    usage: ClaudeCodeUsage = field(default_factory=ClaudeCodeUsage)
    finish_reason: Optional[str] = None
    stop_reason: Optional[str] = None
    raw_events: List[Dict[str, Any]] = field(default_factory=list)
    response_headers: Dict[str, str] = field(default_factory=dict)
    response_status_code: Optional[int] = None
    request_meta: Dict[str, Any] = field(default_factory=dict)

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class CodexOAuthCredential:
    access: str
    refresh: str
    expires: int
    account_id: Optional[str] = None


@dataclass
class CodexUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cached_tokens: int = 0


@dataclass
class CodexToolCall:
    id: str
    name: str
    arguments_json: str


@dataclass
class CodexResult:
    content: str = ""
    tool_calls: List[CodexToolCall] = field(default_factory=list)
    usage: CodexUsage = field(default_factory=CodexUsage)
    finish_reason: Optional[str] = None
    status: Optional[str] = None
    raw_events: List[Dict[str, Any]] = field(default_factory=list)

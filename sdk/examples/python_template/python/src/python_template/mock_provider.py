"""
Mock LLM backend for testing flatagents without real API calls.

Patches litellm.acompletion to return canned JSON responses keyed by
agent name (detected from the system prompt).
"""

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock


@dataclass
class MockUsage:
    prompt_tokens: int = 10
    completion_tokens: int = 10
    total_tokens: int = 20
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


@dataclass
class MockMessage:
    content: str = ""
    role: str = "assistant"
    tool_calls: Optional[list] = None


@dataclass
class MockChoice:
    message: MockMessage = field(default_factory=MockMessage)
    finish_reason: str = "stop"


@dataclass
class MockResponse:
    choices: list = field(default_factory=list)
    usage: MockUsage = field(default_factory=MockUsage)
    model: str = "mock"
    _hidden_params: dict = field(default_factory=dict)
    id: str = "mock-response-id"


# Canned responses keyed by pattern found in system prompt
MOCK_RESPONSES: Dict[str, dict] = {
    "classifier": {
        "category": "technical",
        "confidence": 0.92,
    },
    "summarizer": {
        "summary": "This document discusses key technical concepts and their applications.",
    },
    "entity extractor": {
        "entities": "Python, FlatMachines, SQLite, LiteLLM",
    },
    "report writer": {
        "report": "Technical document (confidence: 0.92). Summary: discusses key technical concepts. Key entities: Python, FlatMachines, SQLite, LiteLLM.",
    },
}


def _detect_agent(messages: List[Dict[str, str]]) -> str:
    """Detect which agent is calling based on system prompt content."""
    system = ""
    for msg in messages:
        if msg.get("role") == "system":
            system = msg.get("content", "").lower()
            break
    for key in MOCK_RESPONSES:
        if key in system:
            return key
    return "classifier"


def _make_mock_response(messages, **kwargs):
    """Build a MockResponse for the given messages."""
    agent_type = _detect_agent(messages)
    content = json.dumps(MOCK_RESPONSES[agent_type])
    return MockResponse(
        choices=[MockChoice(message=MockMessage(content=content))],
    )


def install_mock():
    """
    Monkey-patch litellm.acompletion so all FlatAgent calls get mock responses.
    Call this before creating any FlatMachine/FlatAgent instances.
    """
    import litellm

    async def mock_acompletion(model=None, messages=None, **kwargs):
        return _make_mock_response(messages or [])

    litellm.acompletion = mock_acompletion

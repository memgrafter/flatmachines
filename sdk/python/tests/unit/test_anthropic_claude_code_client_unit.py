from __future__ import annotations

import json
from pathlib import Path

import pytest

from flatagents.providers.anthropic_claude_code_client import (
    CLAUDE_CODE_IDENTITY,
    ClaudeCodeClient,
    ClaudeCodeClientError,
    _from_claude_code_name,
    _to_claude_code_name,
)
from _claude_code_test_helpers import write_auth_file


def _client(tmp_path: Path, **overrides) -> ClaudeCodeClient:
    auth_file = tmp_path / "auth.json"
    write_auth_file(auth_file)
    config = {
        "provider": "anthropic",
        "base_url": "https://api.anthropic.com",
        "oauth": {"auth_file": str(auth_file)},
    }
    config.update(overrides)
    return ClaudeCodeClient(config)


# ---- Tool name mapping ----

def test_to_claude_code_name_matches_known_tools() -> None:
    assert _to_claude_code_name("read") == "Read"
    assert _to_claude_code_name("bash") == "Bash"
    assert _to_claude_code_name("edit") == "Edit"
    assert _to_claude_code_name("Write") == "Write"
    assert _to_claude_code_name("GREP") == "Grep"
    assert _to_claude_code_name("webfetch") == "WebFetch"
    assert _to_claude_code_name("websearch") == "WebSearch"
    assert _to_claude_code_name("askuserquestion") == "AskUserQuestion"
    assert _to_claude_code_name("todowrite") == "TodoWrite"


def test_to_claude_code_name_passes_through_unknown() -> None:
    assert _to_claude_code_name("my_custom_tool") == "my_custom_tool"
    assert _to_claude_code_name("FancyTool") == "FancyTool"


def test_from_claude_code_name_maps_back() -> None:
    original_tools = [
        {"type": "function", "function": {"name": "read_file"}},
        {"type": "function", "function": {"name": "run_bash"}},
    ]
    # Unknown tool → pass through
    assert _from_claude_code_name("Read", original_tools) == "Read"

    # Matching tool (case-insensitive)
    tools_with_read = [
        {"type": "function", "function": {"name": "read"}},
    ]
    assert _from_claude_code_name("Read", tools_with_read) == "read"


def test_from_claude_code_name_no_tools() -> None:
    assert _from_claude_code_name("Read", None) == "Read"
    assert _from_claude_code_name("Read", []) == "Read"


# ---- Request body building ----

def test_build_request_body_basic(tmp_path: Path) -> None:
    client = _client(tmp_path)
    body = client._build_request_body({
        "model": "anthropic/claude-sonnet-4-20250514",
        "messages": [
            {"role": "system", "content": "Be helpful."},
            {"role": "user", "content": "Hello"},
        ],
    })

    assert body["model"] == "claude-sonnet-4-20250514"
    assert body["stream"] is True

    # System blocks: identity first, then user system prompt
    system = body["system"]
    assert len(system) == 2
    assert system[0]["text"] == CLAUDE_CODE_IDENTITY
    assert system[1]["text"] == "Be helpful."

    # Messages should only have user (system extracted)
    assert len(body["messages"]) == 1
    assert body["messages"][0]["role"] == "user"


def test_build_request_body_with_tools(tmp_path: Path) -> None:
    client = _client(tmp_path)
    body = client._build_request_body({
        "model": "claude-sonnet-4-20250514",
        "messages": [{"role": "user", "content": "List files"}],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "read",
                    "description": "Read a file",
                    "parameters": {
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                        "required": ["path"],
                    },
                },
            }
        ],
    })

    assert len(body["tools"]) == 1
    tool = body["tools"][0]
    # Tool name should be mapped to Claude Code canonical casing
    assert tool["name"] == "Read"
    assert tool["description"] == "Read a file"
    assert "input_schema" in tool


def test_build_request_body_with_temperature(tmp_path: Path) -> None:
    client = _client(tmp_path)
    body = client._build_request_body({
        "model": "claude-sonnet-4-20250514",
        "messages": [{"role": "user", "content": "Hi"}],
        "temperature": 0.7,
    })
    assert body["temperature"] == 0.7


def test_build_request_body_assistant_with_tool_calls(tmp_path: Path) -> None:
    client = _client(tmp_path)
    body = client._build_request_body({
        "model": "claude-sonnet-4-20250514",
        "messages": [
            {"role": "user", "content": "Read the file"},
            {
                "role": "assistant",
                "content": "I'll read that file.",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "function": {
                            "name": "read",
                            "arguments": '{"path": "test.txt"}',
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_1",
                "content": "file contents here",
            },
        ],
    })

    # assistant message should have text + tool_use blocks
    assistant_msg = body["messages"][1]
    assert assistant_msg["role"] == "assistant"
    assert len(assistant_msg["content"]) == 2
    assert assistant_msg["content"][0]["type"] == "text"
    assert assistant_msg["content"][1]["type"] == "tool_use"
    assert assistant_msg["content"][1]["name"] == "Read"  # mapped

    # tool result should be a user message with tool_result block
    tool_msg = body["messages"][2]
    assert tool_msg["role"] == "user"
    assert tool_msg["content"][0]["type"] == "tool_result"


# ---- Headers ----

def test_build_headers_contains_claude_code_identity(tmp_path: Path) -> None:
    client = _client(tmp_path)
    headers = client._build_headers(
        access_token="sk-ant-oat-test", params={}
    )

    assert headers["Authorization"] == "Bearer sk-ant-oat-test"
    assert "claude-code" in headers["anthropic-beta"]
    assert "oauth-2025-04-20" in headers["anthropic-beta"]
    assert "claude-cli/" in headers["user-agent"]
    assert headers["x-app"] == "cli"
    assert headers["anthropic-version"] == "2023-06-01"


def test_build_headers_applies_config_overrides(tmp_path: Path) -> None:
    client = _client(tmp_path, headers={"x-custom": "value"})
    headers = client._build_headers(
        access_token="sk-ant-oat-test", params={}
    )
    assert headers["x-custom"] == "value"


def test_build_headers_applies_param_overrides(tmp_path: Path) -> None:
    client = _client(tmp_path)
    headers = client._build_headers(
        access_token="sk-ant-oat-test",
        params={"headers": {"x-per-call": "123"}},
    )
    assert headers["x-per-call"] == "123"


def test_redact_headers(tmp_path: Path) -> None:
    client = _client(tmp_path)
    headers = {"Authorization": "Bearer sk-ant-oat-secret", "x-app": "cli"}
    redacted = client._redact_headers(headers)
    assert redacted["Authorization"] == "Bearer ***"
    assert redacted["x-app"] == "cli"


# ---- SSE parsing ----

def _sse_payload(*events: dict) -> str:
    """Build a raw SSE payload from event dicts."""
    blocks = [f"data: {json.dumps(e)}" for e in events]
    return "\n\n".join(blocks) + "\n\n"


def test_parse_sse_to_result_text_content(tmp_path: Path) -> None:
    client = _client(tmp_path)
    payload = _sse_payload(
        {
            "type": "message_start",
            "message": {
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 0,
                    "cache_read_input_tokens": 5,
                    "cache_creation_input_tokens": 2,
                },
            },
        },
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "text", "text": ""},
        },
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Hello"}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": " world"}},
        {"type": "content_block_stop", "index": 0},
        {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn"},
            "usage": {"output_tokens": 3},
        },
    )

    result = client._parse_sse_to_result(payload)
    assert result.content == "Hello world"
    assert result.finish_reason == "stop"
    assert result.usage.input_tokens == 10
    assert result.usage.output_tokens == 3
    assert result.usage.cache_read_tokens == 5
    assert result.usage.cache_write_tokens == 2


def test_parse_sse_to_result_tool_use(tmp_path: Path) -> None:
    original_tools = [
        {"type": "function", "function": {"name": "read", "parameters": {}}},
    ]
    client = _client(tmp_path)
    payload = _sse_payload(
        {
            "type": "message_start",
            "message": {"usage": {"input_tokens": 5, "output_tokens": 0}},
        },
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {
                "type": "tool_use",
                "id": "toolu_123",
                "name": "Read",
                "input": {},
            },
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "input_json_delta", "partial_json": '{"path":'},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "input_json_delta", "partial_json": '"test.txt"}'},
        },
        {"type": "content_block_stop", "index": 0},
        {
            "type": "message_delta",
            "delta": {"stop_reason": "tool_use"},
            "usage": {"output_tokens": 10},
        },
    )

    result = client._parse_sse_to_result(payload, original_tools=original_tools)
    assert result.finish_reason == "tool_calls"
    assert len(result.tool_calls) == 1

    tc = result.tool_calls[0]
    assert tc.id == "toolu_123"
    # Name should be reverse-mapped to original casing
    assert tc.name == "read"
    assert json.loads(tc.arguments_json) == {"path": "test.txt"}


def test_parse_sse_to_result_error_event(tmp_path: Path) -> None:
    client = _client(tmp_path)
    payload = _sse_payload(
        {
            "type": "error",
            "error": {"type": "overloaded_error", "message": "Overloaded"},
        },
    )

    with pytest.raises(ClaudeCodeClientError, match="Overloaded"):
        client._parse_sse_to_result(payload)


def test_parse_sse_to_result_max_tokens_stop(tmp_path: Path) -> None:
    client = _client(tmp_path)
    payload = _sse_payload(
        {
            "type": "message_start",
            "message": {"usage": {"input_tokens": 5, "output_tokens": 0}},
        },
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "text", "text": ""},
        },
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "partial"}},
        {"type": "content_block_stop", "index": 0},
        {
            "type": "message_delta",
            "delta": {"stop_reason": "max_tokens"},
            "usage": {"output_tokens": 100},
        },
    )

    result = client._parse_sse_to_result(payload)
    assert result.finish_reason == "length"


# ---- URL resolution ----

def test_resolve_url(tmp_path: Path) -> None:
    client = _client(tmp_path)
    assert client._resolve_url("https://api.anthropic.com") == "https://api.anthropic.com/v1/messages"
    assert client._resolve_url("https://api.anthropic.com/v1") == "https://api.anthropic.com/v1/messages"
    assert client._resolve_url("https://api.anthropic.com/v1/messages") == "https://api.anthropic.com/v1/messages"
    assert client._resolve_url("https://custom.proxy.com/") == "https://custom.proxy.com/v1/messages"


# ---- Model name normalization ----

def test_normalize_model_name(tmp_path: Path) -> None:
    client = _client(tmp_path)
    assert client._normalize_model_name("anthropic/claude-sonnet-4-20250514") == "claude-sonnet-4-20250514"
    assert client._normalize_model_name("claude-sonnet-4-20250514") == "claude-sonnet-4-20250514"


# ---- Error parsing ----

def test_parse_error_response_rate_limit(tmp_path: Path) -> None:
    client = _client(tmp_path)
    msg = client._parse_error_response(
        429,
        json.dumps({"error": {"type": "rate_limit_error", "message": "Too many requests"}}),
    )
    assert "rate limited" in msg.lower()


def test_parse_error_response_auth_failure(tmp_path: Path) -> None:
    client = _client(tmp_path)
    msg = client._parse_error_response(
        401,
        json.dumps({"error": {"type": "authentication_error", "message": "Invalid token"}}),
    )
    assert "claude-code-login" in msg.lower()


def test_parse_error_response_overloaded(tmp_path: Path) -> None:
    client = _client(tmp_path)
    msg = client._parse_error_response(
        529,
        json.dumps({"error": {"type": "overloaded_error", "message": "API is overloaded"}}),
    )
    assert "overloaded" in msg.lower()

"""
Integration contract tests for the Claude Code client.

Uses httpx.MockTransport to simulate the Anthropic API and verify
end-to-end behavior: auth, request building, SSE parsing, and retries.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from flatagents.providers.anthropic_claude_code_auth import ClaudeCodeAuthError
from flatagents.providers.anthropic_claude_code_client import (
    CLAUDE_CODE_IDENTITY,
    ClaudeCodeClient,
    ClaudeCodeClientError,
)
from flatagents.providers.anthropic_claude_code_types import ClaudeCodeOAuthCredential
from _claude_code_test_helpers import write_auth_file


def _build_client(
    tmp_path: Path,
    transport: httpx.AsyncBaseTransport,
    *,
    expires: int = 9_999_999_999_999,
    access_token: str = "sk-ant-oat-test-token",
) -> ClaudeCodeClient:
    auth_file = tmp_path / "auth.json"
    write_auth_file(auth_file, access_token=access_token, expires=expires)
    return ClaudeCodeClient(
        {
            "provider": "anthropic",
            "base_url": "https://api.anthropic.com",
            "oauth": {"auth_file": str(auth_file), "max_retries": 2},
        },
        transport=transport,
    )


def _sse_ok(text: str = "ok") -> str:
    """Build a minimal successful SSE response."""
    events = [
        {"type": "message_start", "message": {"usage": {"input_tokens": 5, "output_tokens": 0}}},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text}},
        {"type": "content_block_stop", "index": 0},
        {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 2}},
    ]
    return "\n\n".join(f"data: {json.dumps(e)}" for e in events) + "\n\n"


@pytest.mark.asyncio
async def test_happy_path_success(tmp_path: Path) -> None:
    seen_headers: dict = {}
    seen_body: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_headers, seen_body
        seen_headers = dict(request.headers)
        seen_body = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            text=_sse_ok("hello"),
            headers={"content-type": "text/event-stream"},
        )

    client = _build_client(tmp_path, httpx.MockTransport(handler))
    result = await client.call({
        "model": "anthropic/claude-sonnet-4-20250514",
        "messages": [
            {"role": "system", "content": "Be concise."},
            {"role": "user", "content": "ping"},
        ],
    })

    # Verify auth header
    assert seen_headers["authorization"] == "Bearer sk-ant-oat-test-token"

    # Verify Claude Code identity headers
    assert "claude-code" in seen_headers.get("anthropic-beta", "")
    assert "oauth-2025-04-20" in seen_headers.get("anthropic-beta", "")
    assert "claude-cli/" in seen_headers.get("user-agent", "")
    assert seen_headers.get("x-app") == "cli"

    # Verify system prompt injection
    system_blocks = seen_body["system"]
    assert system_blocks[0]["text"] == CLAUDE_CODE_IDENTITY
    assert system_blocks[1]["text"] == "Be concise."

    # Verify model name normalization
    assert seen_body["model"] == "claude-sonnet-4-20250514"

    # Verify result
    assert result.content == "hello"
    assert result.response_status_code == 200
    assert result.request_meta["method"] == "POST"
    assert result.request_meta["url"].endswith("/v1/messages")
    assert result.request_meta["headers"]["Authorization"] == "Bearer ***"


@pytest.mark.asyncio
async def test_retry_on_429_then_success(tmp_path: Path) -> None:
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(
                429,
                text=json.dumps({"error": {"type": "rate_limit_error", "message": "slow down"}}),
            )
        return httpx.Response(
            200,
            text=_sse_ok("retried"),
            headers={"content-type": "text/event-stream"},
        )

    client = _build_client(tmp_path, httpx.MockTransport(handler))
    result = await client.call({
        "model": "claude-sonnet-4-20250514",
        "messages": [{"role": "user", "content": "ping"}],
    })

    assert attempts == 2
    assert result.content == "retried"


@pytest.mark.asyncio
async def test_retry_on_500_then_success(tmp_path: Path) -> None:
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(500, text="internal error")
        return httpx.Response(
            200,
            text=_sse_ok("recovered"),
            headers={"content-type": "text/event-stream"},
        )

    client = _build_client(tmp_path, httpx.MockTransport(handler))
    result = await client.call({
        "model": "claude-sonnet-4-20250514",
        "messages": [{"role": "user", "content": "ping"}],
    })

    assert attempts == 2
    assert result.content == "recovered"


@pytest.mark.asyncio
async def test_refresh_success_after_initial_401(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    auth_headers: list = []

    async def handler(request: httpx.Request) -> httpx.Response:
        auth_headers.append(request.headers.get("authorization"))
        if len(auth_headers) == 1:
            return httpx.Response(
                401,
                text=json.dumps({"error": {"type": "authentication_error", "message": "expired"}}),
            )
        return httpx.Response(
            200,
            text=_sse_ok("refreshed"),
            headers={"content-type": "text/event-stream"},
        )

    async def fake_refresh(*args, **kwargs):
        return ClaudeCodeOAuthCredential(
            access="sk-ant-oat-fresh-token",
            refresh="refresh-new",
            expires=9_999_999_999_999,
        )

    monkeypatch.setattr(
        "flatagents.providers.anthropic_claude_code_client.refresh_claude_code_credential",
        fake_refresh,
    )

    client = _build_client(tmp_path, httpx.MockTransport(handler))
    result = await client.call({
        "model": "claude-sonnet-4-20250514",
        "messages": [{"role": "user", "content": "ping"}],
    })

    assert result.content == "refreshed"
    assert auth_headers[0] == "Bearer sk-ant-oat-test-token"
    assert auth_headers[1] == "Bearer sk-ant-oat-fresh-token"


@pytest.mark.asyncio
async def test_refresh_failure_surfaces_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            text=json.dumps({"error": {"type": "authentication_error", "message": "expired"}}),
        )

    async def fake_refresh(*args, **kwargs):
        raise ClaudeCodeAuthError("refresh failed")

    monkeypatch.setattr(
        "flatagents.providers.anthropic_claude_code_client.refresh_claude_code_credential",
        fake_refresh,
    )

    client = _build_client(tmp_path, httpx.MockTransport(handler))
    with pytest.raises(ClaudeCodeAuthError):
        await client.call({
            "model": "claude-sonnet-4-20250514",
            "messages": [{"role": "user", "content": "ping"}],
        })


@pytest.mark.asyncio
async def test_terminal_error_without_refresh(tmp_path: Path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            text=json.dumps({"error": {"type": "forbidden", "message": "denied"}}),
        )

    auth_file = tmp_path / "auth.json"
    write_auth_file(auth_file)

    client = ClaudeCodeClient(
        {
            "provider": "anthropic",
            "base_url": "https://api.anthropic.com",
            "oauth": {"auth_file": str(auth_file), "refresh": False},
        },
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ClaudeCodeClientError):
        await client.call({
            "model": "claude-sonnet-4-20250514",
            "messages": [{"role": "user", "content": "ping"}],
        })


@pytest.mark.asyncio
async def test_tool_name_round_trip(tmp_path: Path) -> None:
    """Verify tool names are mapped to CC names in request and back in response."""
    seen_body: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_body
        seen_body = json.loads(request.content.decode("utf-8"))
        # Response has a tool_use with CC name "Read"
        events = [
            {"type": "message_start", "message": {"usage": {"input_tokens": 5, "output_tokens": 0}}},
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "tool_use", "id": "toolu_1", "name": "Read", "input": {}},
            },
            {"type": "content_block_delta", "index": 0, "delta": {"type": "input_json_delta", "partial_json": '{"path":"test.txt"}'}},
            {"type": "content_block_stop", "index": 0},
            {"type": "message_delta", "delta": {"stop_reason": "tool_use"}, "usage": {"output_tokens": 5}},
        ]
        payload = "\n\n".join(f"data: {json.dumps(e)}" for e in events) + "\n\n"
        return httpx.Response(200, text=payload, headers={"content-type": "text/event-stream"})

    client = _build_client(tmp_path, httpx.MockTransport(handler))
    result = await client.call({
        "model": "claude-sonnet-4-20250514",
        "messages": [{"role": "user", "content": "read test.txt"}],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "read",
                    "description": "Read a file",
                    "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
                },
            }
        ],
    })

    # Request should have CC name
    assert seen_body["tools"][0]["name"] == "Read"

    # Response should map back to original name
    assert result.tool_calls[0].name == "read"
    assert result.finish_reason == "tool_calls"


@pytest.mark.asyncio
async def test_pre_request_refresh_on_expired_token(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Tokens expired before the call should be refreshed proactively."""
    auth_headers: list = []

    async def handler(request: httpx.Request) -> httpx.Response:
        auth_headers.append(request.headers.get("authorization"))
        return httpx.Response(
            200,
            text=_sse_ok("ok"),
            headers={"content-type": "text/event-stream"},
        )

    async def fake_refresh(*args, **kwargs):
        return ClaudeCodeOAuthCredential(
            access="sk-ant-oat-refreshed",
            refresh="refresh-new",
            expires=9_999_999_999_999,
        )

    monkeypatch.setattr(
        "flatagents.providers.anthropic_claude_code_client.refresh_claude_code_credential",
        fake_refresh,
    )

    # Credentials with expired timestamp
    client = _build_client(
        tmp_path,
        httpx.MockTransport(handler),
        expires=0,
    )

    result = await client.call({
        "model": "claude-sonnet-4-20250514",
        "messages": [{"role": "user", "content": "ping"}],
    })

    assert result.content == "ok"
    # Should have used the refreshed token
    assert auth_headers[0] == "Bearer sk-ant-oat-refreshed"

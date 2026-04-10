from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from flatagents.providers.github_copilot_auth import CopilotAuthError
from flatagents.providers.github_copilot_client import CopilotClient, CopilotClientError
from flatagents.providers.github_copilot_types import CopilotOAuthCredential
from _github_copilot_test_helpers import token_for_proxy_host, write_auth_file


def _build_client(
    tmp_path: Path,
    transport: httpx.AsyncBaseTransport,
    *,
    expires: int = 9_999_999_999_999,
) -> CopilotClient:
    auth_file = tmp_path / "auth.json"
    write_auth_file(auth_file, access_token=token_for_proxy_host(), expires=expires)
    return CopilotClient(
        {
            "provider": "github-copilot",
            "base_url": "https://api.individual.githubcopilot.com",
            "copilot_auth_file": str(auth_file),
            "copilot_max_retries": 2,
            "auth": {"type": "oauth", "provider": "github-copilot", "auth_file": str(auth_file)},
        },
        transport=transport,
    )


def _ok_payload(text: str = "ok") -> dict:
    return {
        "choices": [
            {
                "message": {"content": text},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


@pytest.mark.asyncio
async def test_happy_path_success(tmp_path: Path) -> None:
    seen_headers = {}
    seen_body = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_headers, seen_body
        seen_headers = dict(request.headers)
        seen_body = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json=_ok_payload("hello"), headers={"content-type": "application/json"})

    client = _build_client(tmp_path, httpx.MockTransport(handler))
    result = await client.call(
        {
            "model": "github-copilot/gpt-4o",
            "messages": [{"role": "user", "content": "ping"}],
        }
    )

    normalized_headers = {str(k).lower(): str(v) for k, v in seen_headers.items()}
    assert normalized_headers["copilot-integration-id"] == "vscode-chat"
    assert normalized_headers["x-initiator"] == "user"
    assert seen_body["model"] == "gpt-4o"
    assert result.content == "hello"
    assert result.response_status_code == 200
    assert result.request_meta["url"].endswith("/chat/completions")
    assert result.request_meta["headers"]["Authorization"] == "Bearer ***"


@pytest.mark.asyncio
async def test_retry_on_429_then_success(tmp_path: Path) -> None:
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, json={"error": {"message": "busy"}})
        return httpx.Response(200, json=_ok_payload("retried"), headers={"content-type": "application/json"})

    client = _build_client(tmp_path, httpx.MockTransport(handler))
    result = await client.call(
        {
            "model": "github-copilot/gpt-4o",
            "messages": [{"role": "user", "content": "ping"}],
        }
    )

    assert attempts == 2
    assert result.content == "retried"


@pytest.mark.asyncio
async def test_refresh_success_after_initial_401(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    auth_headers = []
    stale_token = token_for_proxy_host("proxy.old.example.com")
    fresh_token = token_for_proxy_host("proxy.new.example.com")

    async def handler(request: httpx.Request) -> httpx.Response:
        auth_headers.append(request.headers.get("Authorization"))
        if len(auth_headers) == 1:
            return httpx.Response(401, json={"error": {"message": "expired"}})
        return httpx.Response(200, json=_ok_payload("refreshed"), headers={"content-type": "application/json"})

    async def fake_refresh(*args, **kwargs):
        return CopilotOAuthCredential(
            access=fresh_token,
            refresh="refresh-new",
            expires=9_999_999_999_999,
            enterprise_url=None,
            base_url="https://api.new.example.com",
        )

    monkeypatch.setattr("flatagents.providers.github_copilot_client.load_copilot_credential", lambda *args, **kwargs: CopilotOAuthCredential(
        access=stale_token,
        refresh="refresh-old",
        expires=9_999_999_999_999,
        enterprise_url=None,
        base_url="https://api.old.example.com",
    ))
    monkeypatch.setattr("flatagents.providers.github_copilot_client.refresh_copilot_credential", fake_refresh)

    client = _build_client(tmp_path, httpx.MockTransport(handler))
    result = await client.call(
        {
            "model": "github-copilot/gpt-4o",
            "messages": [{"role": "user", "content": "ping"}],
        }
    )

    assert result.content == "refreshed"
    assert auth_headers[0] == f"Bearer {stale_token}"
    assert auth_headers[1] == f"Bearer {fresh_token}"


@pytest.mark.asyncio
async def test_refresh_failure_surfaces_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "expired"}})

    async def fake_refresh(*args, **kwargs):
        raise CopilotAuthError("refresh failed")

    monkeypatch.setattr("flatagents.providers.github_copilot_client.refresh_copilot_credential", fake_refresh)

    client = _build_client(tmp_path, httpx.MockTransport(handler))
    with pytest.raises(CopilotAuthError):
        await client.call(
            {
                "model": "github-copilot/gpt-4o",
                "messages": [{"role": "user", "content": "ping"}],
            }
        )


@pytest.mark.asyncio
async def test_terminal_error_without_refresh_is_user_friendly(tmp_path: Path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": {"message": "denied"}})

    auth_file = tmp_path / "auth.json"
    write_auth_file(auth_file, access_token=token_for_proxy_host(), expires=9_999_999_999_999)

    client = CopilotClient(
        {
            "provider": "github-copilot",
            "base_url": "https://api.individual.githubcopilot.com",
            "copilot_auth_file": str(auth_file),
            "copilot_refresh": False,
            "auth": {"type": "oauth", "provider": "github-copilot", "auth_file": str(auth_file)},
        },
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(CopilotClientError) as exc:
        await client.call(
            {
                "model": "github-copilot/gpt-4o",
                "messages": [{"role": "user", "content": "ping"}],
            }
        )

    assert "authentication" in str(exc.value).lower() or "denied" in str(exc.value).lower()

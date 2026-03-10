from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from openai_codex_oauth_example.openai_codex_auth import CodexAuthError
from openai_codex_oauth_example.openai_codex_client import CodexClient, CodexClientError
from openai_codex_oauth_example.openai_codex_types import CodexOAuthCredential
from conftest import token_for_account, write_auth_file


def _build_client(tmp_path: Path, transport: httpx.AsyncBaseTransport) -> CodexClient:
    auth_file = tmp_path / "auth.json"
    write_auth_file(auth_file, access_token=token_for_account("acc_start"), expires=0)
    return CodexClient(
        {
            "provider": "openai-codex",
            "base_url": "https://chatgpt.com/backend-api",
            "codex_auth_file": str(auth_file),
            "codex_originator": "pi",
            "codex_max_retries": 2,
            "auth": {"type": "oauth", "provider": "openai-codex", "auth_file": str(auth_file)},
        },
        transport=transport,
    )


def _sse_ok(text: str = "ok") -> str:
    return "\n\n".join(
        [
            f"data: {json.dumps({'type': 'response.output_text.delta', 'delta': text})}",
            f"data: {json.dumps({'type': 'response.completed', 'response': {'status': 'completed', 'usage': {'input_tokens': 1, 'output_tokens': 1, 'total_tokens': 2}}})}",
        ]
    ) + "\n\n"


@pytest.mark.asyncio
async def test_happy_path_stream_success(tmp_path: Path) -> None:
    seen_headers = {}
    seen_body = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_headers, seen_body
        seen_headers = dict(request.headers)
        seen_body = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, text=_sse_ok("hello"), headers={"content-type": "text/event-stream"})

    client = _build_client(tmp_path, httpx.MockTransport(handler))
    result = await client.call(
        {
            "model": "openai-codex/gpt-5.4",
            "messages": [{"role": "system", "content": "sys"}, {"role": "user", "content": "ping"}],
            "session_id": "sess-1",
        }
    )

    assert seen_headers["chatgpt-account-id"] == "acc_start"
    assert seen_headers["session_id"] == "sess-1"
    assert seen_body["prompt_cache_key"] == "sess-1"
    assert result.content == "hello"


@pytest.mark.asyncio
async def test_retry_on_429_then_success(tmp_path: Path) -> None:
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, text=json.dumps({"error": {"code": "rate_limit_exceeded"}}))
        return httpx.Response(200, text=_sse_ok("retried"), headers={"content-type": "text/event-stream"})

    client = _build_client(tmp_path, httpx.MockTransport(handler))
    result = await client.call(
        {
            "model": "openai-codex/gpt-5.4",
            "messages": [{"role": "user", "content": "ping"}],
        }
    )

    assert attempts == 2
    assert result.content == "retried"


@pytest.mark.asyncio
async def test_refresh_success_after_initial_401(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    auth_headers = []
    stale_token = token_for_account("acc_start")
    fresh_token = token_for_account("acc_fresh")

    async def handler(request: httpx.Request) -> httpx.Response:
        auth_headers.append(request.headers.get("Authorization"))
        if len(auth_headers) == 1:
            return httpx.Response(401, text=json.dumps({"error": {"message": "expired"}}))
        return httpx.Response(200, text=_sse_ok("refreshed"), headers={"content-type": "text/event-stream"})

    async def fake_refresh(*args, **kwargs):
        return CodexOAuthCredential(
            access=fresh_token,
            refresh="refresh-new",
            expires=9_999_999_999_999,
            account_id="acc_fresh",
        )

    monkeypatch.setattr("openai_codex_oauth_example.openai_codex_client.refresh_codex_credential", fake_refresh)

    client = _build_client(tmp_path, httpx.MockTransport(handler))
    result = await client.call(
        {
            "model": "openai-codex/gpt-5.4",
            "messages": [{"role": "user", "content": "ping"}],
        }
    )

    assert result.content == "refreshed"
    assert auth_headers[0] == f"Bearer {stale_token}"
    assert auth_headers[1] == f"Bearer {fresh_token}"


@pytest.mark.asyncio
async def test_refresh_success_via_auth_module_persists_new_tokens(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    auth_file = tmp_path / "auth.json"
    stale_token = token_for_account("acc_start")
    fresh_token = token_for_account("acc_fresh")
    write_auth_file(auth_file, access_token=stale_token, refresh_token="refresh-old", expires=0)

    auth_headers = []

    async def handler(request: httpx.Request) -> httpx.Response:
        auth_headers.append(request.headers.get("Authorization"))
        if len(auth_headers) == 1:
            return httpx.Response(401, text=json.dumps({"error": {"message": "expired"}}))
        return httpx.Response(200, text=_sse_ok("refreshed"), headers={"content-type": "text/event-stream"})

    async def fake_refresh_openai_codex_token(*args, **kwargs):
        return {
            "access": fresh_token,
            "refresh": "refresh-new",
            "expires": 9_999_999_999_999,
        }

    monkeypatch.setattr(
        "openai_codex_oauth_example.openai_codex_auth.refresh_openai_codex_token",
        fake_refresh_openai_codex_token,
    )

    client = CodexClient(
        {
            "provider": "openai-codex",
            "base_url": "https://chatgpt.com/backend-api",
            "codex_auth_file": str(auth_file),
            "codex_originator": "pi",
            "auth": {"type": "oauth", "provider": "openai-codex", "auth_file": str(auth_file)},
        },
        transport=httpx.MockTransport(handler),
    )

    result = await client.call(
        {
            "model": "openai-codex/gpt-5.4",
            "messages": [{"role": "user", "content": "ping"}],
        }
    )

    assert result.content == "refreshed"
    assert auth_headers[0] == f"Bearer {stale_token}"
    assert auth_headers[1] == f"Bearer {fresh_token}"

    disk = json.loads(auth_file.read_text(encoding="utf-8"))
    assert disk["openai-codex"]["access"] == fresh_token
    assert disk["openai-codex"]["refresh"] == "refresh-new"
    assert disk["openai-codex"]["accountId"] == "acc_fresh"


@pytest.mark.asyncio
async def test_refresh_failure_surfaces_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text=json.dumps({"error": {"message": "expired"}}))

    async def fake_refresh(*args, **kwargs):
        raise CodexAuthError("refresh failed")

    monkeypatch.setattr("openai_codex_oauth_example.openai_codex_client.refresh_codex_credential", fake_refresh)

    client = _build_client(tmp_path, httpx.MockTransport(handler))
    with pytest.raises(CodexAuthError):
        await client.call(
            {
                "model": "openai-codex/gpt-5.4",
                "messages": [{"role": "user", "content": "ping"}],
            }
        )


@pytest.mark.asyncio
async def test_terminal_error_without_refresh_is_user_friendly(tmp_path: Path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            text=json.dumps({"error": {"message": "denied", "code": "usage_not_included", "plan_type": "PLUS"}}),
        )

    auth_file = tmp_path / "auth.json"
    write_auth_file(auth_file, access_token=token_for_account("acc_start"), expires=9_999_999_999_999)

    client = CodexClient(
        {
            "provider": "openai-codex",
            "base_url": "https://chatgpt.com/backend-api",
            "codex_auth_file": str(auth_file),
            "codex_refresh": False,
            "auth": {"type": "oauth", "provider": "openai-codex", "auth_file": str(auth_file)},
        },
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(CodexClientError) as exc:
        await client.call(
            {
                "model": "openai-codex/gpt-5.4",
                "messages": [{"role": "user", "content": "ping"}],
            }
        )

    assert "usage limit" in str(exc.value).lower() or "denied" in str(exc.value).lower()

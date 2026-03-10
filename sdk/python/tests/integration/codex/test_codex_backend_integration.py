from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx
import pytest

from flatagents import FlatAgent
from flatagents.providers.openai_codex_auth import CodexAuthError
from flatagents.providers.openai_codex_client import CodexClient, CodexClientError
from flatagents.providers.openai_codex_types import CodexOAuthCredential, CodexResult, CodexUsage


def _token_for_account(account_id: str) -> str:
    payload = {"https://api.openai.com/auth": {"chatgpt_account_id": account_id}}
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8").rstrip("=")
    return f"aaa.{encoded}.bbb"


def _write_auth_file(path: Path, token: str, expires: int = 9_999_999_999_999) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "openai-codex": {
                    "type": "oauth",
                    "access": token,
                    "refresh": "refresh-token",
                    "expires": expires,
                },
                "other-provider": {"type": "api_key", "key": "abc"},
            }
        ),
        encoding="utf-8",
    )


def _sse_ok(text: str = "ok") -> str:
    return "\n\n".join(
        [
            f"data: {json.dumps({'type': 'response.output_text.delta', 'delta': text})}",
            f"data: {json.dumps({'type': 'response.completed', 'response': {'status': 'completed', 'usage': {'input_tokens': 1, 'output_tokens': 1, 'total_tokens': 2}}})}",
        ]
    ) + "\n\n"


@pytest.mark.asyncio
async def test_codex_client_happy_path_stream_success(tmp_path: Path) -> None:
    token = _token_for_account("acc_123")
    auth_file = tmp_path / "auth.json"
    _write_auth_file(auth_file, token)

    seen_headers = {}
    seen_body = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_headers, seen_body
        seen_headers = dict(request.headers)
        seen_body = json.loads(request.content.decode("utf-8"))
        return httpx.Response(status_code=200, text=_sse_ok("Hello world"), headers={"content-type": "text/event-stream"})

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
            "messages": [
                {"role": "system", "content": "You are concise."},
                {"role": "user", "content": "Say hi."},
            ],
            "temperature": 0.2,
            "session_id": "sess-1",
        }
    )

    assert seen_headers["chatgpt-account-id"] == "acc_123"
    assert seen_headers["originator"] == "pi"
    assert seen_headers["session_id"] == "sess-1"
    assert seen_body["model"] == "gpt-5.4"
    assert seen_body["prompt_cache_key"] == "sess-1"
    assert seen_body["instructions"] == "You are concise."
    assert result.content == "Hello world"
    assert result.usage.total_tokens == 2
    assert result.response_headers.get("content-type") == "text/event-stream"
    assert result.response_status_code == 200
    assert result.request_meta["method"] == "POST"
    assert result.request_meta["url"].endswith("/codex/responses")
    assert result.request_meta["headers"]["Authorization"] == "Bearer ***"


@pytest.mark.asyncio
async def test_codex_client_refreshes_after_auth_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    stale_token = _token_for_account("acc_old")
    fresh_token = _token_for_account("acc_new")
    auth_file = tmp_path / "auth.json"
    _write_auth_file(auth_file, stale_token, expires=9_999_999_999_999)

    auth_headers = []

    async def handler(request: httpx.Request) -> httpx.Response:
        auth_headers.append(request.headers.get("Authorization"))
        if len(auth_headers) == 1:
            return httpx.Response(status_code=401, text=json.dumps({"error": {"message": "expired"}}))
        return httpx.Response(status_code=200, text=_sse_ok("ok"), headers={"content-type": "text/event-stream"})

    async def fake_refresh(*args, **kwargs):
        return CodexOAuthCredential(
            access=fresh_token,
            refresh="refresh-token-new",
            expires=9_999_999_999_999,
            account_id="acc_new",
        )

    monkeypatch.setattr("flatagents.providers.openai_codex_client.refresh_codex_credential", fake_refresh)

    client = CodexClient(
        {
            "provider": "openai-codex",
            "base_url": "https://chatgpt.com/backend-api",
            "codex_auth_file": str(auth_file),
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

    assert len(auth_headers) == 2
    assert auth_headers[0] == f"Bearer {stale_token}"
    assert auth_headers[1] == f"Bearer {fresh_token}"
    assert result.content == "ok"


@pytest.mark.asyncio
async def test_flatagent_codex_backend_end_to_end(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    token = _token_for_account("acc_agent")
    auth_file = tmp_path / "auth.json"
    _write_auth_file(auth_file, token)

    async def fake_call(self, params):
        return CodexResult(
            content="Codex says hi",
            usage=CodexUsage(input_tokens=10, output_tokens=5, total_tokens=15),
            finish_reason="stop",
        )

    monkeypatch.setattr("flatagents.providers.openai_codex_client.CodexClient.call", fake_call)

    agent = FlatAgent(
        config_dict={
            "spec": "flatagent",
            "spec_version": "2.2.2",
            "data": {
                "name": "codex-integration-agent",
                "model": {
                    "provider": "openai-codex",
                    "name": "gpt-5.4",
                    "backend": "codex",
                    "codex_auth_file": str(auth_file),
                    "auth": {"type": "oauth", "provider": "openai-codex", "auth_file": str(auth_file)},
                },
                "system": "You are concise.",
                "user": "{{ input.prompt }}",
            },
        }
    )

    result = await agent.call(prompt="Say hi")
    assert result.content == "Codex says hi"
    assert result.finish_reason is not None


@pytest.mark.asyncio
async def test_codex_client_terminal_error_without_refresh_is_user_friendly(tmp_path: Path) -> None:
    token = _token_for_account("acc_limit")
    auth_file = tmp_path / "auth.json"
    _write_auth_file(auth_file, token)

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            text=json.dumps({"error": {"message": "denied", "code": "usage_not_included", "plan_type": "PLUS"}}),
        )

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

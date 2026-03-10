from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx
import pytest

from openai_codex_oauth_example.openai_codex_auth import (
    PiAuthStore,
    extract_account_id_from_access_token,
)
from openai_codex_oauth_example.openai_codex_client import CodexClient
from openai_codex_oauth_example.openai_codex_types import CodexOAuthCredential


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


@pytest.mark.asyncio
async def test_account_id_extraction_and_store_preserves_other_entries(tmp_path: Path) -> None:
    token = _token_for_account("acc_test")
    assert extract_account_id_from_access_token(token) == "acc_test"

    auth_file = tmp_path / "auth.json"
    _write_auth_file(auth_file, token)

    store = PiAuthStore(str(auth_file))
    loaded = store.load_provider("openai-codex")
    loaded["accountId"] = "acc_test"
    store.save_provider("openai-codex", loaded)

    data = json.loads(auth_file.read_text(encoding="utf-8"))
    assert data["openai-codex"]["accountId"] == "acc_test"
    assert data["other-provider"]["key"] == "abc"


@pytest.mark.asyncio
async def test_codex_client_builds_expected_headers_and_body_and_parses_sse(tmp_path: Path) -> None:
    token = _token_for_account("acc_123")
    auth_file = tmp_path / "auth.json"
    _write_auth_file(auth_file, token)

    seen_headers = {}
    seen_body = {}

    sse_payload = "\n\n".join(
        [
            f"data: {json.dumps({'type': 'response.output_text.delta', 'delta': 'Hello'})}",
            f"data: {json.dumps({'type': 'response.output_text.delta', 'delta': ' world'})}",
            f"data: {json.dumps({'type': 'response.completed', 'response': {'status': 'completed', 'usage': {'input_tokens': 5, 'output_tokens': 3, 'total_tokens': 8, 'input_tokens_details': {'cached_tokens': 1}}}})}",
            "data: [DONE]",
        ]
    ) + "\n\n"

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_headers, seen_body
        seen_headers = dict(request.headers)
        seen_body = json.loads(request.content.decode("utf-8"))
        return httpx.Response(status_code=200, text=sse_payload, headers={"content-type": "text/event-stream"})

    transport = httpx.MockTransport(handler)
    client = CodexClient(
        {
            "provider": "openai-codex",
            "base_url": "https://chatgpt.com/backend-api",
            "codex_auth_file": str(auth_file),
            "codex_originator": "pi",
            "auth": {"type": "oauth", "provider": "openai-codex", "auth_file": str(auth_file)},
        },
        transport=transport,
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
    assert result.usage.total_tokens == 8
    assert result.usage.cached_tokens == 1


@pytest.mark.asyncio
async def test_codex_client_refreshes_after_auth_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    stale_token = _token_for_account("acc_old")
    fresh_token = _token_for_account("acc_new")
    auth_file = tmp_path / "auth.json"
    _write_auth_file(auth_file, stale_token, expires=0)

    auth_headers = []

    sse_payload = "\n\n".join(
        [
            f"data: {json.dumps({'type': 'response.output_text.delta', 'delta': 'ok'})}",
            f"data: {json.dumps({'type': 'response.completed', 'response': {'status': 'completed', 'usage': {'input_tokens': 1, 'output_tokens': 1, 'total_tokens': 2}}})}",
        ]
    ) + "\n\n"

    async def handler(request: httpx.Request) -> httpx.Response:
        auth_headers.append(request.headers.get("Authorization"))
        if len(auth_headers) == 1:
            return httpx.Response(status_code=401, text=json.dumps({"error": {"message": "expired"}}))
        return httpx.Response(status_code=200, text=sse_payload, headers={"content-type": "text/event-stream"})

    async def fake_refresh(*args, **kwargs):
        return CodexOAuthCredential(
            access=fresh_token,
            refresh="refresh-token-new",
            expires=9_999_999_999_999,
            account_id="acc_new",
        )

    monkeypatch.setattr("openai_codex_oauth_example.openai_codex_client.refresh_codex_credential", fake_refresh)

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

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from flatagents import FlatAgent
from flatagents.providers.github_copilot_client import CopilotClient, CopilotClientError
from flatagents.providers.github_copilot_types import CopilotOAuthCredential, CopilotResult, CopilotUsage


def _token(proxy_host: str = "proxy.individual.githubcopilot.com") -> str:
    return f"tid=test;exp=9999999999;proxy-ep={proxy_host};foo=bar"


def _write_auth_file(path: Path, token: str, expires: int = 9_999_999_999_999) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "github-copilot": {
                    "type": "oauth",
                    "access": token,
                    "refresh": "github-access-token",
                    "expires": expires,
                },
                "other-provider": {"type": "api_key", "key": "abc"},
            }
        ),
        encoding="utf-8",
    )


def _ok_payload(text: str = "ok") -> dict:
    return {
        "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


@pytest.mark.asyncio
async def test_copilot_client_happy_path_success(tmp_path: Path) -> None:
    auth_file = tmp_path / "auth.json"
    _write_auth_file(auth_file, _token())

    seen_headers = {}
    seen_body = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_headers, seen_body
        seen_headers = dict(request.headers)
        seen_body = json.loads(request.content.decode("utf-8"))
        return httpx.Response(status_code=200, json=_ok_payload("Hello world"), headers={"content-type": "application/json"})

    client = CopilotClient(
        {
            "provider": "github-copilot",
            "base_url": "https://api.individual.githubcopilot.com",
            "copilot_auth_file": str(auth_file),
            "auth": {"type": "oauth", "provider": "github-copilot", "auth_file": str(auth_file)},
        },
        transport=httpx.MockTransport(handler),
    )

    result = await client.call(
        {
            "model": "github-copilot/gpt-4o",
            "messages": [{"role": "user", "content": "Say hi."}],
            "temperature": 0.2,
        }
    )

    normalized_headers = {str(k).lower(): str(v) for k, v in seen_headers.items()}
    assert normalized_headers["copilot-integration-id"] == "vscode-chat"
    assert normalized_headers["x-initiator"] == "user"
    assert seen_body["model"] == "gpt-4o"
    assert result.content == "Hello world"
    assert result.usage.total_tokens == 2
    assert result.response_status_code == 200
    assert result.request_meta["method"] == "POST"
    assert result.request_meta["url"].endswith("/chat/completions")


@pytest.mark.asyncio
async def test_copilot_client_refreshes_after_auth_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    stale_token = _token("proxy.old.example.com")
    fresh_token = _token("proxy.new.example.com")
    auth_file = tmp_path / "auth.json"
    _write_auth_file(auth_file, stale_token, expires=9_999_999_999_999)

    auth_headers = []

    async def handler(request: httpx.Request) -> httpx.Response:
        auth_headers.append(request.headers.get("Authorization"))
        if len(auth_headers) == 1:
            return httpx.Response(status_code=401, json={"error": {"message": "expired"}})
        return httpx.Response(status_code=200, json=_ok_payload("ok"), headers={"content-type": "application/json"})

    async def fake_refresh(*args, **kwargs):
        return CopilotOAuthCredential(
            access=fresh_token,
            refresh="refresh-token-new",
            expires=9_999_999_999_999,
            enterprise_url=None,
            base_url="https://api.new.example.com",
        )

    monkeypatch.setattr("flatagents.providers.github_copilot_client.refresh_copilot_credential", fake_refresh)

    client = CopilotClient(
        {
            "provider": "github-copilot",
            "base_url": "https://api.individual.githubcopilot.com",
            "copilot_auth_file": str(auth_file),
            "auth": {"type": "oauth", "provider": "github-copilot", "auth_file": str(auth_file)},
        },
        transport=httpx.MockTransport(handler),
    )

    result = await client.call(
        {
            "model": "github-copilot/gpt-4o",
            "messages": [{"role": "user", "content": "ping"}],
        }
    )

    assert len(auth_headers) == 2
    assert auth_headers[0] == f"Bearer {stale_token}"
    assert auth_headers[1] == f"Bearer {fresh_token}"
    assert result.content == "ok"


@pytest.mark.asyncio
async def test_flatagent_copilot_backend_end_to_end(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    auth_file = tmp_path / "auth.json"
    _write_auth_file(auth_file, _token())

    async def fake_call(self, params):
        return CopilotResult(
            content="Copilot says hi",
            usage=CopilotUsage(input_tokens=10, output_tokens=5, total_tokens=15),
            finish_reason="stop",
        )

    monkeypatch.setattr("flatagents.providers.github_copilot_client.CopilotClient.call", fake_call)

    agent = FlatAgent(
        config_dict={
            "spec": "flatagent",
            "spec_version": "2.2.2",
            "data": {
                "name": "copilot-integration-agent",
                "model": {
                    "provider": "github-copilot",
                    "name": "gpt-4o",
                    "backend": "copilot",
                    "oauth": {"provider": "github-copilot", "auth_file": str(auth_file)},
                },
                "system": "You are concise.",
                "user": "{{ input.prompt }}",
            },
        }
    )

    result = await agent.call(prompt="Say hi")
    assert result.content == "Copilot says hi"
    assert result.finish_reason is not None


@pytest.mark.asyncio
async def test_copilot_client_terminal_error_without_refresh_is_user_friendly(tmp_path: Path) -> None:
    auth_file = tmp_path / "auth.json"
    _write_auth_file(auth_file, _token())

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={"error": {"message": "denied"}},
        )

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

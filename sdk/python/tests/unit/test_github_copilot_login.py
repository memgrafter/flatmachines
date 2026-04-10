from __future__ import annotations

import json
from pathlib import Path

import pytest

from flatagents.providers.github_copilot_login import (
    CopilotLoginError,
    DeviceCodeResponse,
    login_github_copilot,
    poll_for_github_access_token,
    start_device_flow,
)
from _github_copilot_test_helpers import token_for_proxy_host


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None, text: str = ""):
        self.status_code = status_code
        self.reason_phrase = "ERR"
        self.text = text
        self._payload = payload or {}

    def json(self):
        return self._payload


class _FakeAsyncClient:
    def __init__(self, responses: list[_FakeResponse]):
        self._responses = responses

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def request(self, *args, **kwargs):
        if not self._responses:
            raise RuntimeError("No more fake responses")
        return self._responses.pop(0)


@pytest.mark.asyncio
async def test_start_device_flow_validates_response(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_client = _FakeAsyncClient(
        [
            _FakeResponse(
                200,
                {
                    "device_code": "dev-1",
                    "user_code": "CODE-1",
                    "verification_uri": "https://github.com/login/device",
                    "interval": 2,
                    "expires_in": 900,
                },
            )
        ]
    )

    monkeypatch.setattr(
        "flatagents.providers.github_copilot_login.httpx.AsyncClient",
        lambda *args, **kwargs: fake_client,
    )

    flow = await start_device_flow("github.com")
    assert isinstance(flow, DeviceCodeResponse)
    assert flow.device_code == "dev-1"


@pytest.mark.asyncio
async def test_poll_for_github_access_token_handles_pending_then_success(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_client = _FakeAsyncClient(
        [
            _FakeResponse(200, {"error": "authorization_pending"}),
            _FakeResponse(200, {"access_token": "gh-token"}),
        ]
    )

    monkeypatch.setattr(
        "flatagents.providers.github_copilot_login.httpx.AsyncClient",
        lambda *args, **kwargs: fake_client,
    )

    token = await poll_for_github_access_token(
        "github.com",
        device_code="dev-1",
        interval_seconds=0,
        expires_in=30,
    )
    assert token == "gh-token"


@pytest.mark.asyncio
async def test_poll_for_github_access_token_denied_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_client = _FakeAsyncClient([_FakeResponse(200, {"error": "access_denied"})])
    monkeypatch.setattr(
        "flatagents.providers.github_copilot_login.httpx.AsyncClient",
        lambda *args, **kwargs: fake_client,
    )

    with pytest.raises(CopilotLoginError):
        await poll_for_github_access_token(
            "github.com",
            device_code="dev-1",
            interval_seconds=1,
            expires_in=30,
        )


@pytest.mark.asyncio
async def test_login_github_copilot_saves_auth_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    auth_file = tmp_path / "auth.json"

    async def fake_start(*args, **kwargs):
        return DeviceCodeResponse(
            device_code="dev-1",
            user_code="CODE-1",
            verification_uri="https://github.com/login/device",
            interval=1,
            expires_in=900,
        )

    async def fake_poll(*args, **kwargs):
        return "gh-access"

    async def fake_refresh(*args, **kwargs):
        return {
            "access": token_for_proxy_host("proxy.enterprise.example.com"),
            "refresh": "gh-access",
            "expires": 9_999_999_999_999,
            "baseUrl": "https://api.enterprise.example.com",
            "enterpriseUrl": "ghe.example.com",
        }

    monkeypatch.setattr("flatagents.providers.github_copilot_login.start_device_flow", fake_start)
    monkeypatch.setattr("flatagents.providers.github_copilot_login.poll_for_github_access_token", fake_poll)
    monkeypatch.setattr("flatagents.providers.github_copilot_login.refresh_github_copilot_token", fake_refresh)
    monkeypatch.setattr("flatagents.providers.github_copilot_login.webbrowser.open", lambda *args, **kwargs: True)

    creds = await login_github_copilot(
        auth_file=str(auth_file),
        enterprise_domain="ghe.example.com",
        open_browser=False,
    )

    stored = json.loads(auth_file.read_text(encoding="utf-8"))
    assert stored["github-copilot"]["type"] == "oauth"
    assert stored["github-copilot"]["refresh"] == "gh-access"
    assert stored["github-copilot"]["baseUrl"] == "https://api.enterprise.example.com"
    assert creds.base_url == "https://api.enterprise.example.com"

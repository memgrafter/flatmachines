from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from flatagents.providers.anthropic_claude_code_login import (
    ClaudeCodeLoginError,
    OAuthCredentials,
    create_authorization_flow,
    exchange_authorization_code,
    login_anthropic_claude_code,
    parse_authorization_input,
)


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class _FakeAsyncClient:
    def __init__(self, response: _FakeResponse):
        self._response = response
        self.last_post = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def post(self, *args, **kwargs):
        self.last_post = (args, kwargs)
        return self._response


def test_parse_authorization_input_code_hash_state() -> None:
    code, state = parse_authorization_input("abc123#verifier456")
    assert code == "abc123"
    assert state == "verifier456"


def test_parse_authorization_input_url() -> None:
    code, state = parse_authorization_input(
        "https://console.anthropic.com/oauth/code/callback?code=abc&state=xyz"
    )
    assert code == "abc"
    assert state == "xyz"


def test_parse_authorization_input_query_string() -> None:
    code, state = parse_authorization_input("code=abc&state=xyz")
    assert code == "abc"
    assert state == "xyz"


def test_parse_authorization_input_raw_code() -> None:
    code, state = parse_authorization_input("rawcode")
    assert code == "rawcode"
    assert state is None


def test_parse_authorization_input_empty() -> None:
    code, state = parse_authorization_input("")
    assert code is None
    assert state is None


def test_create_authorization_flow_contains_anthropic_params() -> None:
    flow = create_authorization_flow()
    parsed = urlparse(flow.url)
    query = parse_qs(parsed.query)

    assert parsed.scheme == "https"
    assert "claude.ai" in parsed.netloc
    assert query["client_id"][0] == "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
    assert query["scope"][0] == "org:create_api_key user:profile user:inference"
    assert (
        query["redirect_uri"][0]
        == "https://console.anthropic.com/oauth/code/callback"
    )
    assert query["code_challenge_method"][0] == "S256"
    assert query["response_type"][0] == "code"
    assert query["code"][0] == "true"
    # state should equal verifier
    assert query["state"][0] == flow.verifier


def test_create_authorization_flow_pkce_verifier_and_challenge_differ() -> None:
    flow = create_authorization_flow()
    assert flow.verifier != flow.challenge
    assert len(flow.verifier) > 40
    assert len(flow.challenge) > 20


@pytest.mark.asyncio
async def test_exchange_authorization_code_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = _FakeAsyncClient(
        _FakeResponse(
            200,
            {
                "access_token": "sk-ant-oat-login-test",
                "refresh_token": "refresh-1",
                "expires_in": 3600,
            },
        )
    )

    monkeypatch.setattr(
        "flatagents.providers.anthropic_claude_code_login.httpx.AsyncClient",
        lambda *args, **kwargs: fake_client,
    )

    creds = await exchange_authorization_code(code="auth-code", verifier="verifier-1")
    assert creds.access == "sk-ant-oat-login-test"
    assert creds.refresh == "refresh-1"
    assert isinstance(creds.expires, int)

    # Verify JSON content type (Anthropic uses JSON, not form-encoded)
    _, kwargs = fake_client.last_post
    assert "json" in kwargs


@pytest.mark.asyncio
async def test_exchange_authorization_code_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = _FakeAsyncClient(_FakeResponse(400, {}))
    monkeypatch.setattr(
        "flatagents.providers.anthropic_claude_code_login.httpx.AsyncClient",
        lambda *args, **kwargs: fake_client,
    )

    with pytest.raises(ClaudeCodeLoginError):
        await exchange_authorization_code(code="bad", verifier="verifier")


@pytest.mark.asyncio
async def test_exchange_authorization_code_missing_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = _FakeAsyncClient(
        _FakeResponse(200, {"access_token": "tok"})  # missing refresh + expires_in
    )
    monkeypatch.setattr(
        "flatagents.providers.anthropic_claude_code_login.httpx.AsyncClient",
        lambda *args, **kwargs: fake_client,
    )

    with pytest.raises(ClaudeCodeLoginError, match="missing required"):
        await exchange_authorization_code(code="code", verifier="v")


@pytest.mark.asyncio
async def test_login_anthropic_claude_code_saves_auth_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    auth_file = tmp_path / "auth.json"

    async def fake_exchange(*args, **kwargs):
        return OAuthCredentials(
            access="sk-ant-oat-saved",
            refresh="refresh-saved",
            expires=9_999_999_999_999,
        )

    monkeypatch.setattr(
        "flatagents.providers.anthropic_claude_code_login.exchange_authorization_code",
        fake_exchange,
    )
    monkeypatch.setattr(
        "flatagents.providers.anthropic_claude_code_login.webbrowser.open",
        lambda *args, **kwargs: True,
    )

    await login_anthropic_claude_code(
        auth_file=str(auth_file),
        open_browser=False,
        manual_input_provider=lambda: "manual-auth-code#verifier",
    )

    stored = json.loads(auth_file.read_text(encoding="utf-8"))
    assert stored["anthropic"]["type"] == "oauth"
    assert stored["anthropic"]["access"] == "sk-ant-oat-saved"
    assert stored["anthropic"]["refresh"] == "refresh-saved"


@pytest.mark.asyncio
async def test_login_missing_code_raises(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "flatagents.providers.anthropic_claude_code_login.webbrowser.open",
        lambda *args, **kwargs: True,
    )

    with pytest.raises(ClaudeCodeLoginError, match="Missing authorization code"):
        await login_anthropic_claude_code(
            auth_file=str(tmp_path / "auth.json"),
            open_browser=False,
            manual_input_provider=lambda: "",
        )

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from openai_codex_oauth_example.openai_codex_login import (
    CodexLoginError,
    OAuthCredentials,
    create_authorization_flow,
    exchange_authorization_code,
    login_openai_codex,
    parse_authorization_input,
)
from conftest import token_for_account


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


def test_parse_authorization_input_variants() -> None:
    code, state = parse_authorization_input("https://localhost/callback?code=abc&state=xyz")
    assert code == "abc"
    assert state == "xyz"

    code, state = parse_authorization_input("abc#xyz")
    assert code == "abc"
    assert state == "xyz"

    code, state = parse_authorization_input("code=abc&state=xyz")
    assert code == "abc"
    assert state == "xyz"

    code, state = parse_authorization_input("rawcode")
    assert code == "rawcode"
    assert state is None


def test_create_authorization_flow_contains_expected_openai_params() -> None:
    flow = create_authorization_flow(originator="pi")
    parsed = urlparse(flow.url)
    query = parse_qs(parsed.query)

    assert query["client_id"][0]
    assert query["scope"][0] == "openid profile email offline_access"
    assert query["redirect_uri"][0] == "http://localhost:1455/auth/callback"
    assert query["code_challenge_method"][0] == "S256"
    assert query["originator"][0] == "pi"
    assert query["id_token_add_organizations"][0] == "true"
    assert query["codex_cli_simplified_flow"][0] == "true"


@pytest.mark.asyncio
async def test_exchange_authorization_code_success(monkeypatch: pytest.MonkeyPatch) -> None:
    token = token_for_account("acc_login")
    fake_client = _FakeAsyncClient(
        _FakeResponse(
            200,
            {
                "access_token": token,
                "refresh_token": "refresh-1",
                "expires_in": 3600,
            },
        )
    )

    monkeypatch.setattr(
        "openai_codex_oauth_example.openai_codex_login.httpx.AsyncClient",
        lambda *args, **kwargs: fake_client,
    )

    creds = await exchange_authorization_code(code="auth-code", verifier="verifier-1")
    assert creds.access == token
    assert creds.refresh == "refresh-1"
    assert creds.account_id == "acc_login"


@pytest.mark.asyncio
async def test_exchange_authorization_code_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_client = _FakeAsyncClient(_FakeResponse(400, {}))
    monkeypatch.setattr(
        "openai_codex_oauth_example.openai_codex_login.httpx.AsyncClient",
        lambda *args, **kwargs: fake_client,
    )

    with pytest.raises(CodexLoginError):
        await exchange_authorization_code(code="bad", verifier="verifier")


@pytest.mark.asyncio
async def test_login_openai_codex_saves_auth_file_without_email_prompt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    auth_file = tmp_path / "auth.json"

    async def fake_exchange_authorization_code(*args, **kwargs):
        return OAuthCredentials(
            access=token_for_account("acc_saved"),
            refresh="refresh-saved",
            expires=9_999_999_999_999,
            account_id="acc_saved",
        )

    monkeypatch.setattr(
        "openai_codex_oauth_example.openai_codex_login.exchange_authorization_code",
        fake_exchange_authorization_code,
    )

    # Ensure we don't rely on browser popups in tests.
    monkeypatch.setattr("openai_codex_oauth_example.openai_codex_login.webbrowser.open", lambda *args, **kwargs: True)

    await login_openai_codex(
        auth_file=str(auth_file),
        allow_local_server=False,
        open_browser=False,
        manual_input_provider=lambda: "manual-auth-code",
    )

    stored = json.loads(auth_file.read_text(encoding="utf-8"))
    assert stored["openai-codex"]["type"] == "oauth"
    assert stored["openai-codex"]["refresh"] == "refresh-saved"
    assert stored["openai-codex"]["accountId"] == "acc_saved"

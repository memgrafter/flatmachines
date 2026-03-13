from __future__ import annotations

import json
from pathlib import Path

import pytest

from flatagents.providers.anthropic_claude_code_auth import (
    ClaudeCodeAuthError,
    PiAuthStore,
    is_claude_code_oauth_token,
    is_expired,
    load_claude_code_credential,
    refresh_anthropic_token,
    refresh_claude_code_credential,
)
from _claude_code_test_helpers import write_auth_file


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


class _FakeAsyncClient:
    def __init__(self, response: _FakeResponse):
        self._response = response
        self.last_post_kwargs = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def post(self, *args, **kwargs):
        self.last_post_kwargs = kwargs
        return self._response


def test_is_claude_code_oauth_token_positive() -> None:
    assert is_claude_code_oauth_token("sk-ant-oat-abc123") is True


def test_is_claude_code_oauth_token_negative() -> None:
    assert is_claude_code_oauth_token("sk-ant-api-key123") is False
    assert is_claude_code_oauth_token("sk-proj-abc123") is False
    assert is_claude_code_oauth_token("") is False


def test_load_claude_code_credential_happy_path(tmp_path: Path) -> None:
    auth_file = tmp_path / "auth.json"
    write_auth_file(auth_file, access_token="sk-ant-oat-test")

    store = PiAuthStore(str(auth_file))
    cred = load_claude_code_credential(store)
    assert cred.access == "sk-ant-oat-test"
    assert cred.refresh == "refresh-token"
    assert cred.expires == 9_999_999_999_999


def test_load_claude_code_credential_preserves_other_entries(tmp_path: Path) -> None:
    auth_file = tmp_path / "auth.json"
    write_auth_file(auth_file)

    store = PiAuthStore(str(auth_file))
    _ = load_claude_code_credential(store)

    # Verify other entries are untouched
    data = json.loads(auth_file.read_text(encoding="utf-8"))
    assert data["other-provider"]["key"] == "abc"


def test_missing_provider_credential_prompts_login_guidance(tmp_path: Path) -> None:
    auth_file = tmp_path / "auth.json"
    auth_file.write_text(
        json.dumps({"other": {"type": "api_key", "key": "x"}}), encoding="utf-8"
    )

    store = PiAuthStore(str(auth_file))
    with pytest.raises(ClaudeCodeAuthError) as exc:
        store.load_provider("anthropic")

    assert "claude-code-login" in str(exc.value)


def test_missing_access_token_raises(tmp_path: Path) -> None:
    auth_file = tmp_path / "auth.json"
    auth_file.write_text(
        json.dumps({"anthropic": {"type": "oauth", "refresh": "r", "expires": 999}}),
        encoding="utf-8",
    )
    store = PiAuthStore(str(auth_file))
    with pytest.raises(ClaudeCodeAuthError, match="access token"):
        load_claude_code_credential(store)


def test_wrong_credential_type_raises(tmp_path: Path) -> None:
    auth_file = tmp_path / "auth.json"
    auth_file.write_text(
        json.dumps({"anthropic": {"type": "api_key", "key": "sk-ant-api123"}}),
        encoding="utf-8",
    )
    store = PiAuthStore(str(auth_file))
    with pytest.raises(ClaudeCodeAuthError, match="oauth"):
        load_claude_code_credential(store)


def test_is_expired_uses_skew(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "flatagents.providers.anthropic_claude_code_auth.time.time", lambda: 1000.0
    )
    assert not is_expired(1_000_200, skew_ms=100)
    assert is_expired(1_000_050, skew_ms=100)


@pytest.mark.asyncio
async def test_refresh_anthropic_token_success(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_client = _FakeAsyncClient(
        _FakeResponse(
            200,
            payload={
                "access_token": "sk-ant-oat-new",
                "refresh_token": "refresh-new",
                "expires_in": 3600,
            },
        )
    )

    monkeypatch.setattr(
        "flatagents.providers.anthropic_claude_code_auth.httpx.AsyncClient",
        lambda *args, **kwargs: fake_client,
    )

    refreshed = await refresh_anthropic_token("refresh-old")
    assert refreshed["access"] == "sk-ant-oat-new"
    assert refreshed["refresh"] == "refresh-new"
    assert isinstance(refreshed["expires"], int)

    # Verify it uses JSON content type (not form-encoded like OpenAI)
    assert fake_client.last_post_kwargs is not None
    assert "json" in fake_client.last_post_kwargs


@pytest.mark.asyncio
async def test_refresh_anthropic_token_failure_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _FakeResponse(401, text="unauthorized")
    monkeypatch.setattr(
        "flatagents.providers.anthropic_claude_code_auth.httpx.AsyncClient",
        lambda *args, **kwargs: _FakeAsyncClient(response),
    )

    with pytest.raises(ClaudeCodeAuthError, match="claude-code-login"):
        await refresh_anthropic_token("refresh-old")


@pytest.mark.asyncio
async def test_refresh_claude_code_credential_updates_auth_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    auth_file = tmp_path / "auth.json"
    write_auth_file(
        auth_file,
        access_token="sk-ant-oat-stale",
        refresh_token="refresh-old",
        expires=0,
    )

    async def fake_refresh(*args, **kwargs):
        return {
            "access": "sk-ant-oat-fresh",
            "refresh": "refresh-new",
            "expires": 9_999_999_999_999,
        }

    monkeypatch.setattr(
        "flatagents.providers.anthropic_claude_code_auth.refresh_anthropic_token",
        fake_refresh,
    )

    store = PiAuthStore(str(auth_file))
    cred = await refresh_claude_code_credential(store)

    assert cred.access == "sk-ant-oat-fresh"
    assert cred.refresh == "refresh-new"

    disk = json.loads(auth_file.read_text(encoding="utf-8"))
    assert disk["anthropic"]["access"] == "sk-ant-oat-fresh"
    assert disk["anthropic"]["refresh"] == "refresh-new"
    # Other providers preserved
    assert disk["other-provider"]["key"] == "abc"


@pytest.mark.asyncio
async def test_refresh_claude_code_credential_failure_does_not_mutate_auth_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    auth_file = tmp_path / "auth.json"
    write_auth_file(
        auth_file,
        access_token="sk-ant-oat-stale",
        refresh_token="refresh-old",
        expires=0,
    )
    before = auth_file.read_text(encoding="utf-8")

    async def fake_refresh(*args, **kwargs):
        raise ClaudeCodeAuthError("refresh failed")

    monkeypatch.setattr(
        "flatagents.providers.anthropic_claude_code_auth.refresh_anthropic_token",
        fake_refresh,
    )

    store = PiAuthStore(str(auth_file))
    with pytest.raises(ClaudeCodeAuthError):
        await refresh_claude_code_credential(store)

    after = auth_file.read_text(encoding="utf-8")
    assert after == before


def test_save_provider_preserves_other_entries(tmp_path: Path) -> None:
    auth_file = tmp_path / "auth.json"
    write_auth_file(auth_file)

    store = PiAuthStore(str(auth_file))
    store.save_provider(
        "anthropic",
        {"type": "oauth", "access": "new", "refresh": "r", "expires": 999},
    )

    disk = json.loads(auth_file.read_text(encoding="utf-8"))
    assert disk["anthropic"]["access"] == "new"
    assert disk["other-provider"]["key"] == "abc"

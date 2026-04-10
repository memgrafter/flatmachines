from __future__ import annotations

import json
from pathlib import Path

import pytest

from flatagents.providers.github_copilot_auth import (
    CopilotAuthError,
    CopilotAuthStore,
    get_github_copilot_base_url,
    is_expired,
    load_copilot_credential,
    normalize_domain,
    refresh_copilot_credential,
    refresh_github_copilot_token,
)
from _github_copilot_test_helpers import token_for_proxy_host, write_auth_file


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text
        self.reason_phrase = "ERR"

    def json(self):
        return self._payload


class _FakeAsyncClient:
    def __init__(self, response: _FakeResponse):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def get(self, *args, **kwargs):
        return self._response


def test_normalize_domain_and_base_url_helpers() -> None:
    assert normalize_domain("github.com") == "github.com"
    assert normalize_domain("https://github.com") == "github.com"
    assert normalize_domain("not a url") is None

    token = token_for_proxy_host("proxy.enterprise.githubcopilot.com")
    assert get_github_copilot_base_url(token=token) == "https://api.enterprise.githubcopilot.com"
    assert get_github_copilot_base_url(token="tid=x;exp=1", enterprise_domain="ghe.example.com") == "https://copilot-api.ghe.example.com"


def test_load_copilot_credential_and_store_preserves_other_entries(tmp_path: Path) -> None:
    auth_file = tmp_path / "auth.json"
    write_auth_file(auth_file, access_token=token_for_proxy_host())

    store = CopilotAuthStore(str(auth_file))
    cred = load_copilot_credential(store)
    assert cred.base_url == "https://api.individual.githubcopilot.com"

    data = store.load_provider("github-copilot")
    data["enterpriseUrl"] = "ghe.example.com"
    store.save_provider("github-copilot", data)

    merged = json.loads(auth_file.read_text(encoding="utf-8"))
    assert merged["github-copilot"]["enterpriseUrl"] == "ghe.example.com"
    assert merged["other-provider"]["key"] == "abc"


def test_is_expired_uses_skew(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("flatagents.providers.github_copilot_auth.time.time", lambda: 1000.0)
    assert not is_expired(1_301_000, skew_ms=5 * 60 * 1000)
    assert is_expired(1_299_000, skew_ms=5 * 60 * 1000)


@pytest.mark.asyncio
async def test_refresh_github_copilot_token_success(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _FakeResponse(
        200,
        payload={
            "token": token_for_proxy_host("proxy.foo.example.com"),
            "expires_at": 2_000_000,
        },
    )

    monkeypatch.setattr(
        "flatagents.providers.github_copilot_auth.httpx.AsyncClient",
        lambda *args, **kwargs: _FakeAsyncClient(response),
    )

    refreshed = await refresh_github_copilot_token("gh-refresh", enterprise_domain="ghe.example.com")
    assert refreshed["refresh"] == "gh-refresh"
    assert refreshed["baseUrl"] == "https://api.foo.example.com"
    assert isinstance(refreshed["expires"], int)


@pytest.mark.asyncio
async def test_refresh_github_copilot_token_failure_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _FakeResponse(401, text="unauthorized")
    monkeypatch.setattr(
        "flatagents.providers.github_copilot_auth.httpx.AsyncClient",
        lambda *args, **kwargs: _FakeAsyncClient(response),
    )

    with pytest.raises(CopilotAuthError):
        await refresh_github_copilot_token("gh-refresh")


@pytest.mark.asyncio
async def test_refresh_copilot_credential_updates_auth_file_and_preserves_other_entries(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    stale_token = token_for_proxy_host("proxy.old.example.com")
    fresh_token = token_for_proxy_host("proxy.new.example.com")
    auth_file = tmp_path / "auth.json"
    write_auth_file(auth_file, access_token=stale_token, refresh_token="refresh-old", expires=0)

    async def fake_refresh_github_copilot_token(*args, **kwargs):
        return {
            "access": fresh_token,
            "refresh": "refresh-new",
            "expires": 9_999_999_999_999,
            "baseUrl": "https://api.new.example.com",
        }

    monkeypatch.setattr(
        "flatagents.providers.github_copilot_auth.refresh_github_copilot_token",
        fake_refresh_github_copilot_token,
    )

    store = CopilotAuthStore(str(auth_file))
    cred = await refresh_copilot_credential(store)

    assert cred.access == fresh_token
    assert cred.refresh == "refresh-new"
    assert cred.base_url == "https://api.new.example.com"

    disk = json.loads(auth_file.read_text(encoding="utf-8"))
    assert disk["github-copilot"]["access"] == fresh_token
    assert disk["github-copilot"]["refresh"] == "refresh-new"
    assert disk["other-provider"]["key"] == "abc"


@pytest.mark.asyncio
async def test_refresh_copilot_credential_failure_does_not_mutate_auth_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    auth_file = tmp_path / "auth.json"
    write_auth_file(auth_file, access_token=token_for_proxy_host("proxy.old.example.com"), refresh_token="refresh-old", expires=0)
    before = auth_file.read_text(encoding="utf-8")

    async def fake_refresh_github_copilot_token(*args, **kwargs):
        raise CopilotAuthError("refresh failed")

    monkeypatch.setattr(
        "flatagents.providers.github_copilot_auth.refresh_github_copilot_token",
        fake_refresh_github_copilot_token,
    )

    store = CopilotAuthStore(str(auth_file))
    with pytest.raises(CopilotAuthError):
        await refresh_copilot_credential(store)

    after = auth_file.read_text(encoding="utf-8")
    assert after == before

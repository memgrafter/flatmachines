from __future__ import annotations

import json
from pathlib import Path

import pytest

from flatagents.providers.openai_codex_auth import (
    CodexAuthError,
    PiAuthStore,
    extract_account_id_from_access_token,
    is_expired,
    load_codex_credential,
    refresh_codex_credential,
    refresh_openai_codex_token,
)
from _codex_test_helpers import token_for_account, write_auth_file


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

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def post(self, *args, **kwargs):
        return self._response


def test_extract_account_id_from_access_token_happy_path() -> None:
    token = token_for_account("acc_test")
    assert extract_account_id_from_access_token(token) == "acc_test"


def test_extract_account_id_from_access_token_missing_claim_raises() -> None:
    token = "aaa.eyJmb28iOiJiYXIifQ.bbb"  # {"foo":"bar"}
    with pytest.raises(CodexAuthError):
        extract_account_id_from_access_token(token)


def test_load_codex_credential_and_store_preserves_other_entries(tmp_path: Path) -> None:
    auth_file = tmp_path / "auth.json"
    write_auth_file(auth_file, access_token=token_for_account("acc_1"))

    store = PiAuthStore(str(auth_file))
    cred = load_codex_credential(store)
    assert cred.account_id == "acc_1"

    data = store.load_provider("openai-codex")
    data["accountId"] = "acc_2"
    store.save_provider("openai-codex", data)

    merged = json.loads(auth_file.read_text(encoding="utf-8"))
    assert merged["openai-codex"]["accountId"] == "acc_2"
    assert merged["other-provider"]["key"] == "abc"


def test_is_expired_uses_skew(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("flatagents.providers.openai_codex_auth.time.time", lambda: 1000.0)
    assert not is_expired(1_000_200, skew_ms=100)
    assert is_expired(1_000_050, skew_ms=100)


@pytest.mark.asyncio
async def test_refresh_openai_codex_token_success(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _FakeResponse(
        200,
        payload={
            "access_token": "access-new",
            "refresh_token": "refresh-new",
            "expires_in": 3600,
        },
    )

    monkeypatch.setattr(
        "flatagents.providers.openai_codex_auth.httpx.AsyncClient",
        lambda *args, **kwargs: _FakeAsyncClient(response),
    )

    refreshed = await refresh_openai_codex_token("refresh-old")
    assert refreshed["access"] == "access-new"
    assert refreshed["refresh"] == "refresh-new"
    assert isinstance(refreshed["expires"], int)


@pytest.mark.asyncio
async def test_refresh_openai_codex_token_failure_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _FakeResponse(401, text="unauthorized")
    monkeypatch.setattr(
        "flatagents.providers.openai_codex_auth.httpx.AsyncClient",
        lambda *args, **kwargs: _FakeAsyncClient(response),
    )

    with pytest.raises(CodexAuthError):
        await refresh_openai_codex_token("refresh-old")


def test_missing_provider_credential_prompts_login_guidance(tmp_path: Path) -> None:
    auth_file = tmp_path / "auth.json"
    auth_file.write_text(json.dumps({"other": {"type": "api_key", "key": "x"}}), encoding="utf-8")

    store = PiAuthStore(str(auth_file))
    with pytest.raises(CodexAuthError) as exc:
        store.load_provider("openai-codex")

    assert "Run codex login first" in str(exc.value)


@pytest.mark.asyncio
async def test_refresh_codex_credential_updates_auth_file_and_preserves_other_entries(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    stale_token = token_for_account("acc_old")
    fresh_token = token_for_account("acc_new")
    auth_file = tmp_path / "auth.json"
    write_auth_file(auth_file, access_token=stale_token, refresh_token="refresh-old", expires=0)

    async def fake_refresh_openai_codex_token(*args, **kwargs):
        return {
            "access": fresh_token,
            "refresh": "refresh-new",
            "expires": 9_999_999_999_999,
        }

    monkeypatch.setattr(
        "flatagents.providers.openai_codex_auth.refresh_openai_codex_token",
        fake_refresh_openai_codex_token,
    )

    store = PiAuthStore(str(auth_file))
    cred = await refresh_codex_credential(store)

    assert cred.access == fresh_token
    assert cred.refresh == "refresh-new"
    assert cred.account_id == "acc_new"

    disk = json.loads(auth_file.read_text(encoding="utf-8"))
    assert disk["openai-codex"]["access"] == fresh_token
    assert disk["openai-codex"]["refresh"] == "refresh-new"
    assert disk["openai-codex"]["accountId"] == "acc_new"
    assert disk["other-provider"]["key"] == "abc"


@pytest.mark.asyncio
async def test_refresh_codex_credential_failure_does_not_mutate_auth_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    stale_token = token_for_account("acc_old")
    auth_file = tmp_path / "auth.json"
    write_auth_file(auth_file, access_token=stale_token, refresh_token="refresh-old", expires=0)
    before = auth_file.read_text(encoding="utf-8")

    async def fake_refresh_openai_codex_token(*args, **kwargs):
        raise CodexAuthError("refresh failed")

    monkeypatch.setattr(
        "flatagents.providers.openai_codex_auth.refresh_openai_codex_token",
        fake_refresh_openai_codex_token,
    )

    store = PiAuthStore(str(auth_file))
    with pytest.raises(CodexAuthError):
        await refresh_codex_credential(store)

    after = auth_file.read_text(encoding="utf-8")
    assert after == before

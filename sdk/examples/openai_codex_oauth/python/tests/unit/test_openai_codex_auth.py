from __future__ import annotations

import json
from pathlib import Path

import pytest

from openai_codex_oauth_example.openai_codex_auth import (
    CodexAuthError,
    PiAuthStore,
    extract_account_id_from_access_token,
    is_expired,
    load_codex_credential,
    refresh_openai_codex_token,
)
from conftest import token_for_account, write_auth_file


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
    monkeypatch.setattr("openai_codex_oauth_example.openai_codex_auth.time.time", lambda: 1000.0)
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
        "openai_codex_oauth_example.openai_codex_auth.httpx.AsyncClient",
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
        "openai_codex_oauth_example.openai_codex_auth.httpx.AsyncClient",
        lambda *args, **kwargs: _FakeAsyncClient(response),
    )

    with pytest.raises(CodexAuthError):
        await refresh_openai_codex_token("refresh-old")

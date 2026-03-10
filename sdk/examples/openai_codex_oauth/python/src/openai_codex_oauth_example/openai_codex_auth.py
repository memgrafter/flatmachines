from __future__ import annotations

import base64
import json
import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

import httpx

from .openai_codex_types import CodexOAuthCredential

DEFAULT_AUTH_FILE = "~/.pi/agent/auth.json"
DEFAULT_PROVIDER = "openai-codex"
TOKEN_URL = "https://auth.openai.com/oauth/token"
OPENAI_CODEX_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
JWT_CLAIM_PATH = "https://api.openai.com/auth"


class CodexAuthError(RuntimeError):
    pass


def resolve_auth_file(explicit_path: Optional[str] = None) -> str:
    path = explicit_path or os.environ.get("FLATAGENTS_CODEX_AUTH_FILE") or DEFAULT_AUTH_FILE
    return os.path.expanduser(path)


def _urlsafe_b64decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def decode_jwt_payload(token: str) -> Dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 3:
        raise CodexAuthError("Invalid access token format")
    try:
        return json.loads(_urlsafe_b64decode(parts[1]).decode("utf-8"))
    except Exception as exc:  # pragma: no cover - defensive
        raise CodexAuthError("Failed to decode access token payload") from exc


def extract_account_id_from_access_token(token: str) -> str:
    payload = decode_jwt_payload(token)
    account_id = payload.get(JWT_CLAIM_PATH, {}).get("chatgpt_account_id")
    if isinstance(account_id, str) and account_id:
        return account_id
    raise CodexAuthError(
        "Could not find chatgpt account id in token (expected payload['https://api.openai.com/auth'].chatgpt_account_id)"
    )


def is_expired(expires_ms: int, skew_ms: int = 60_000) -> bool:
    return int(time.time() * 1000) >= int(expires_ms) - skew_ms


class PiAuthStore:
    def __init__(self, auth_file: Optional[str] = None):
        self.auth_file = resolve_auth_file(auth_file)
        self.lock_file = f"{self.auth_file}.lock"

    def _ensure_paths(self) -> None:
        auth_path = Path(self.auth_file)
        auth_path.parent.mkdir(parents=True, exist_ok=True)
        if not auth_path.exists():
            auth_path.write_text("{}", encoding="utf-8")
            os.chmod(auth_path, 0o600)

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self._ensure_paths()
        import fcntl

        with open(self.lock_file, "a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _read_all_unlocked(self) -> Dict[str, Any]:
        try:
            return json.loads(Path(self.auth_file).read_text(encoding="utf-8") or "{}")
        except json.JSONDecodeError as exc:
            raise CodexAuthError(f"Invalid JSON in auth file: {self.auth_file}") from exc

    def _write_all_unlocked(self, data: Dict[str, Any]) -> None:
        target = Path(self.auth_file)
        fd, tmp_path = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp", dir=str(target.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2)
                handle.write("\n")
            os.chmod(tmp_path, 0o600)
            os.replace(tmp_path, target)
            os.chmod(target, 0o600)
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def load_all(self) -> Dict[str, Any]:
        with self._locked():
            return self._read_all_unlocked()

    def load_provider(self, provider: str = DEFAULT_PROVIDER) -> Dict[str, Any]:
        data = self.load_all()
        cred = data.get(provider)
        if not isinstance(cred, dict):
            raise CodexAuthError(
                f"No credentials for provider '{provider}' in {self.auth_file}. Run pi login first."
            )
        return cred

    def save_provider(self, provider: str, credentials: Dict[str, Any]) -> None:
        with self._locked():
            data = self._read_all_unlocked()
            data[provider] = credentials
            self._write_all_unlocked(data)


def _credential_from_dict(data: Dict[str, Any]) -> CodexOAuthCredential:
    if data.get("type") != "oauth":
        raise CodexAuthError("Expected oauth credentials in auth.json")
    access = data.get("access")
    refresh = data.get("refresh")
    expires = data.get("expires")
    if not isinstance(access, str) or not access:
        raise CodexAuthError("Missing access token in oauth credentials")
    if not isinstance(refresh, str) or not refresh:
        raise CodexAuthError("Missing refresh token in oauth credentials")
    if not isinstance(expires, int):
        raise CodexAuthError("Missing expires timestamp in oauth credentials")

    account_id = data.get("accountId") if isinstance(data.get("accountId"), str) else None
    if not account_id:
        account_id = extract_account_id_from_access_token(access)

    return CodexOAuthCredential(access=access, refresh=refresh, expires=expires, account_id=account_id)


async def refresh_openai_codex_token(
    refresh_token: str,
    *,
    timeout_seconds: float = 20.0,
    token_url: str = TOKEN_URL,
    client_id: str = OPENAI_CODEX_CLIENT_ID,
) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        response = await client.post(
            token_url,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": client_id,
            },
        )

    if response.status_code >= 400:
        raise CodexAuthError(f"Token refresh failed ({response.status_code}). Please run pi login again.")

    payload = response.json()
    access = payload.get("access_token")
    new_refresh = payload.get("refresh_token")
    expires_in = payload.get("expires_in")
    if not isinstance(access, str) or not access:
        raise CodexAuthError("Token refresh response missing access_token")
    if not isinstance(new_refresh, str) or not new_refresh:
        raise CodexAuthError("Token refresh response missing refresh_token")
    if not isinstance(expires_in, int):
        raise CodexAuthError("Token refresh response missing expires_in")

    return {
        "access": access,
        "refresh": new_refresh,
        "expires": int(time.time() * 1000) + expires_in * 1000,
    }


def load_codex_credential(
    store: PiAuthStore,
    provider: str = DEFAULT_PROVIDER,
) -> CodexOAuthCredential:
    return _credential_from_dict(store.load_provider(provider))


async def refresh_codex_credential(
    store: PiAuthStore,
    provider: str = DEFAULT_PROVIDER,
    *,
    timeout_seconds: float = 20.0,
    token_url: str = TOKEN_URL,
    client_id: str = OPENAI_CODEX_CLIENT_ID,
) -> CodexOAuthCredential:
    current = store.load_provider(provider)
    credential = _credential_from_dict(current)

    refreshed = await refresh_openai_codex_token(
        credential.refresh,
        timeout_seconds=timeout_seconds,
        token_url=token_url,
        client_id=client_id,
    )

    # Re-read after network call: another process may have refreshed already.
    latest = store.load_provider(provider)
    latest_credential = _credential_from_dict(latest)
    if latest_credential.access != credential.access and not is_expired(latest_credential.expires, skew_ms=0):
        return latest_credential

    merged = dict(latest)
    merged.update(refreshed)
    merged["type"] = "oauth"
    merged["accountId"] = extract_account_id_from_access_token(merged["access"])
    store.save_provider(provider, merged)
    return _credential_from_dict(merged)

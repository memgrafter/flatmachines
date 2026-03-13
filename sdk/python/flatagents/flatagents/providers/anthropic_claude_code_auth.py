"""
Anthropic Claude Code OAuth credential management.

Handles loading, saving, and refreshing OAuth credentials for the
Anthropic Claude Code backend. Uses the shared PiAuthStore for
cross-process safe credential persistence.

Auth file precedence:
  oauth.auth_file → auth.auth_file → FLATAGENTS_CLAUDE_CODE_AUTH_FILE → ~/.pi/agent/auth.json
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

import httpx

from .anthropic_claude_code_types import ClaudeCodeOAuthCredential

DEFAULT_AUTH_FILE = "~/.pi/agent/auth.json"
DEFAULT_PROVIDER = "anthropic"
TOKEN_URL = "https://console.anthropic.com/v1/oauth/token"
CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"

# Token prefix used by Anthropic OAuth access tokens
OAUTH_TOKEN_PREFIX = "sk-ant-oat"

# Buffer subtracted from expires_in to ensure tokens are refreshed before
# they actually expire (5 minutes in milliseconds).
EXPIRY_BUFFER_MS = 5 * 60 * 1000


class ClaudeCodeAuthError(RuntimeError):
    """Raised for authentication failures with the Anthropic Claude Code backend."""
    pass


def resolve_auth_file(
    *,
    model_config: Optional[Dict[str, Any]] = None,
    explicit_path: Optional[str] = None,
    config_dir: Optional[str] = None,
) -> str:
    """Resolve the auth file path from config, env vars, or default.

    Precedence:
      1. explicit_path argument
      2. model_config.oauth.auth_file
      3. model_config.auth.auth_file
      4. FLATAGENTS_CLAUDE_CODE_AUTH_FILE env var
      5. FLATAGENTS_CODEX_AUTH_FILE env var (shared)
      6. ~/.pi/agent/auth.json
    """
    oauth_cfg = (
        model_config.get("oauth")
        if isinstance(model_config, dict) and isinstance(model_config.get("oauth"), dict)
        else {}
    )
    auth_cfg = (
        model_config.get("auth")
        if isinstance(model_config, dict) and isinstance(model_config.get("auth"), dict)
        else {}
    )

    path = (
        explicit_path
        or oauth_cfg.get("auth_file")
        or auth_cfg.get("auth_file")
        or os.environ.get("FLATAGENTS_CLAUDE_CODE_AUTH_FILE")
        or os.environ.get("FLATAGENTS_CODEX_AUTH_FILE")
        or DEFAULT_AUTH_FILE
    )

    expanded = os.path.expanduser(str(path))
    if not os.path.isabs(expanded) and config_dir:
        expanded = os.path.join(config_dir, expanded)
    return os.path.abspath(expanded)


def is_claude_code_oauth_token(token: str) -> bool:
    """Check whether a token is an Anthropic OAuth access token."""
    return token.startswith(OAUTH_TOKEN_PREFIX)


def is_expired(expires_ms: int, skew_ms: int = 60_000) -> bool:
    """Check whether a credential has expired (with configurable skew)."""
    return int(time.time() * 1000) >= int(expires_ms) - skew_ms


class PiAuthStore:
    """File-backed credential store with cross-process locking.

    Shares the same auth.json format as the Codex backend so both
    providers can coexist in a single file under different keys.
    """

    def __init__(
        self,
        auth_file: Optional[str] = None,
        *,
        model_config: Optional[Dict[str, Any]] = None,
        config_dir: Optional[str] = None,
    ):
        self.auth_file = resolve_auth_file(
            model_config=model_config,
            explicit_path=auth_file,
            config_dir=config_dir,
        )
        self.lock_file = f"{self.auth_file}.flatagents.lock"

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
            raise ClaudeCodeAuthError(f"Invalid JSON in auth file: {self.auth_file}") from exc

    def _write_all_unlocked(self, data: Dict[str, Any]) -> None:
        target = Path(self.auth_file)
        fd, tmp_path = tempfile.mkstemp(
            prefix=target.name + ".", suffix=".tmp", dir=str(target.parent)
        )
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
            raise ClaudeCodeAuthError(
                f"No credentials for provider '{provider}' in {self.auth_file}. "
                f"Run claude-code-login first."
            )
        return cred

    def save_provider(self, provider: str, credentials: Dict[str, Any]) -> None:
        with self._locked():
            data = self._read_all_unlocked()
            data[provider] = credentials
            self._write_all_unlocked(data)


def _credential_from_dict(data: Dict[str, Any]) -> ClaudeCodeOAuthCredential:
    """Parse a raw dict from auth.json into a typed credential."""
    if data.get("type") != "oauth":
        raise ClaudeCodeAuthError("Expected oauth credentials in auth.json")

    access = data.get("access")
    refresh = data.get("refresh")
    expires = data.get("expires")

    if not isinstance(access, str) or not access:
        raise ClaudeCodeAuthError("Missing access token in oauth credentials")
    if not isinstance(refresh, str) or not refresh:
        raise ClaudeCodeAuthError("Missing refresh token in oauth credentials")
    if not isinstance(expires, int):
        raise ClaudeCodeAuthError("Missing expires timestamp in oauth credentials")

    return ClaudeCodeOAuthCredential(access=access, refresh=refresh, expires=expires)


async def refresh_anthropic_token(
    refresh_token: str,
    *,
    timeout_seconds: float = 20.0,
    token_url: str = TOKEN_URL,
    client_id: str = CLIENT_ID,
) -> Dict[str, Any]:
    """Exchange a refresh token for a new access + refresh token pair.

    Returns a dict with ``access``, ``refresh``, and ``expires`` (ms timestamp)
    suitable for merging into the auth store.

    Note: Anthropic uses ``application/json`` for token requests (not
    ``application/x-www-form-urlencoded`` like OpenAI).
    """
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        response = await client.post(
            token_url,
            headers={"Content-Type": "application/json"},
            json={
                "grant_type": "refresh_token",
                "client_id": client_id,
                "refresh_token": refresh_token,
            },
        )

    if response.status_code >= 400:
        raise ClaudeCodeAuthError(
            f"Token refresh failed ({response.status_code}). "
            f"Please run claude-code-login again."
        )

    payload = response.json()
    access = payload.get("access_token")
    new_refresh = payload.get("refresh_token")
    expires_in = payload.get("expires_in")

    if not isinstance(access, str) or not access:
        raise ClaudeCodeAuthError("Token refresh response missing access_token")
    if not isinstance(new_refresh, str) or not new_refresh:
        raise ClaudeCodeAuthError("Token refresh response missing refresh_token")
    if not isinstance(expires_in, int):
        raise ClaudeCodeAuthError("Token refresh response missing expires_in")

    return {
        "access": access,
        "refresh": new_refresh,
        "expires": int(time.time() * 1000) + expires_in * 1000 - EXPIRY_BUFFER_MS,
    }


def load_claude_code_credential(
    store: PiAuthStore,
    provider: str = DEFAULT_PROVIDER,
) -> ClaudeCodeOAuthCredential:
    """Load an Anthropic OAuth credential from the auth store."""
    return _credential_from_dict(store.load_provider(provider))


async def refresh_claude_code_credential(
    store: PiAuthStore,
    provider: str = DEFAULT_PROVIDER,
    *,
    timeout_seconds: float = 20.0,
    token_url: str = TOKEN_URL,
    client_id: str = CLIENT_ID,
) -> ClaudeCodeOAuthCredential:
    """Refresh an Anthropic OAuth credential with cross-process safety.

    1. Load current credential from disk.
    2. Call the token endpoint.
    3. Re-read the file to check if another process refreshed first.
    4. If the on-disk credential changed and is still valid, use it.
    5. Otherwise, merge the refreshed tokens and persist.
    """
    current = store.load_provider(provider)
    credential = _credential_from_dict(current)

    refreshed = await refresh_anthropic_token(
        credential.refresh,
        timeout_seconds=timeout_seconds,
        token_url=token_url,
        client_id=client_id,
    )

    # Cross-process check: re-read to see if someone else refreshed.
    latest = store.load_provider(provider)
    latest_credential = _credential_from_dict(latest)
    if (
        latest_credential.access != credential.access
        and not is_expired(latest_credential.expires, skew_ms=0)
    ):
        return latest_credential

    # Merge and persist.
    merged = dict(latest)
    merged.update(refreshed)
    merged["type"] = "oauth"
    store.save_provider(provider, merged)
    return _credential_from_dict(merged)

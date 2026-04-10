from __future__ import annotations

import json
import os
import re
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, Optional
from urllib.parse import urlparse

import httpx

from .github_copilot_types import CopilotOAuthCredential

DEFAULT_AUTH_FILE = "~/.agents/flatmachines/auth.json"
DEFAULT_PROVIDER = "github-copilot"
DEFAULT_DOMAIN = "github.com"
DEFAULT_BASE_URL = "https://api.individual.githubcopilot.com"
REFRESH_SKEW_MS = 5 * 60 * 1000

COPILOT_STATIC_HEADERS: Dict[str, str] = {
    "User-Agent": "GitHubCopilotChat/0.35.0",
    "Editor-Version": "vscode/1.107.0",
    "Editor-Plugin-Version": "copilot-chat/0.35.0",
    "Copilot-Integration-Id": "vscode-chat",
}


class CopilotAuthError(RuntimeError):
    pass


def normalize_domain(input_value: str) -> Optional[str]:
    trimmed = str(input_value or "").strip()
    if not trimmed or any(ch.isspace() for ch in trimmed):
        return None

    try:
        parsed = urlparse(trimmed if "://" in trimmed else f"https://{trimmed}")
    except Exception:
        return None

    hostname = parsed.hostname
    return hostname if isinstance(hostname, str) and hostname else None


def get_urls(domain: str) -> Dict[str, str]:
    normalized = normalize_domain(domain) or DEFAULT_DOMAIN
    return {
        "device_code_url": f"https://{normalized}/login/device/code",
        "access_token_url": f"https://{normalized}/login/oauth/access_token",
        "copilot_token_url": f"https://api.{normalized}/copilot_internal/v2/token",
    }


def get_base_url_from_token(token: str) -> Optional[str]:
    match = re.search(r"proxy-ep=([^;]+)", token)
    if not match:
        return None

    proxy_host = match.group(1)
    if not proxy_host:
        return None

    api_host = proxy_host.replace("proxy.", "api.", 1)
    return f"https://{api_host}"


def get_github_copilot_base_url(
    token: Optional[str] = None,
    enterprise_domain: Optional[str] = None,
) -> str:
    if token:
        from_token = get_base_url_from_token(token)
        if from_token:
            return from_token

    normalized_enterprise = normalize_domain(enterprise_domain or "")
    if normalized_enterprise:
        return f"https://copilot-api.{normalized_enterprise}"

    return DEFAULT_BASE_URL


def resolve_auth_file(
    *,
    model_config: Optional[Dict[str, Any]] = None,
    explicit_path: Optional[str] = None,
    config_dir: Optional[str] = None,
) -> str:
    oauth_cfg = model_config.get("oauth") if isinstance(model_config, dict) and isinstance(model_config.get("oauth"), dict) else {}
    auth_cfg = model_config.get("auth") if isinstance(model_config, dict) and isinstance(model_config.get("auth"), dict) else {}

    path = (
        explicit_path
        or oauth_cfg.get("auth_file")
        or (model_config.get("copilot_auth_file") if isinstance(model_config, dict) else None)
        or auth_cfg.get("auth_file")
        or os.environ.get("FLATAGENTS_COPILOT_AUTH_FILE")
        or DEFAULT_AUTH_FILE
    )

    expanded = os.path.expanduser(str(path))
    if not os.path.isabs(expanded) and config_dir:
        expanded = os.path.join(config_dir, expanded)
    return os.path.abspath(expanded)


def is_expired(expires_ms: int, skew_ms: int = REFRESH_SKEW_MS) -> bool:
    return int(time.time() * 1000) >= int(expires_ms) - skew_ms


class CopilotAuthStore:
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
            raise CopilotAuthError(f"Invalid JSON in auth file: {self.auth_file}") from exc

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
            raise CopilotAuthError(
                f"No credentials for provider '{provider}' in {self.auth_file}. Run Copilot login first."
            )
        return cred

    def save_provider(self, provider: str, credentials: Dict[str, Any]) -> None:
        with self._locked():
            data = self._read_all_unlocked()
            data[provider] = credentials
            self._write_all_unlocked(data)


def _credential_from_dict(data: Dict[str, Any]) -> CopilotOAuthCredential:
    if data.get("type") != "oauth":
        raise CopilotAuthError("Expected oauth credentials in auth.json")

    access = data.get("access")
    refresh = data.get("refresh")
    expires = data.get("expires")

    if not isinstance(access, str) or not access:
        raise CopilotAuthError("Missing access token in oauth credentials")
    if not isinstance(refresh, str) or not refresh:
        raise CopilotAuthError("Missing refresh token in oauth credentials")
    if not isinstance(expires, int):
        raise CopilotAuthError("Missing expires timestamp in oauth credentials")

    enterprise_url = data.get("enterpriseUrl") if isinstance(data.get("enterpriseUrl"), str) else None
    enterprise_domain = normalize_domain(enterprise_url or "")
    base_url = data.get("baseUrl") if isinstance(data.get("baseUrl"), str) else None
    if not base_url:
        base_url = get_github_copilot_base_url(access, enterprise_domain)

    return CopilotOAuthCredential(
        access=access,
        refresh=refresh,
        expires=expires,
        enterprise_url=enterprise_domain,
        base_url=base_url,
    )


async def refresh_github_copilot_token(
    refresh_token: str,
    *,
    enterprise_domain: Optional[str] = None,
    timeout_seconds: float = 20.0,
    copilot_token_url: Optional[str] = None,
) -> Dict[str, Any]:
    normalized_enterprise = normalize_domain(enterprise_domain or "")
    domain = normalized_enterprise or DEFAULT_DOMAIN
    url = copilot_token_url or get_urls(domain)["copilot_token_url"]

    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        response = await client.get(
            url,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {refresh_token}",
                **COPILOT_STATIC_HEADERS,
            },
        )

    if response.status_code >= 400:
        raise CopilotAuthError(
            f"Copilot token refresh failed ({response.status_code}). Please run Copilot login again."
        )

    payload = response.json()
    token = payload.get("token")
    expires_at = payload.get("expires_at")

    if not isinstance(token, str) or not token:
        raise CopilotAuthError("Copilot token response missing token")
    if not isinstance(expires_at, (int, float)):
        raise CopilotAuthError("Copilot token response missing expires_at")

    refreshed: Dict[str, Any] = {
        "access": token,
        "refresh": refresh_token,
        "expires": int(expires_at * 1000) - REFRESH_SKEW_MS,
        "baseUrl": get_github_copilot_base_url(token, normalized_enterprise),
    }
    if normalized_enterprise:
        refreshed["enterpriseUrl"] = normalized_enterprise
    return refreshed


def load_copilot_credential(
    store: CopilotAuthStore,
    provider: str = DEFAULT_PROVIDER,
) -> CopilotOAuthCredential:
    return _credential_from_dict(store.load_provider(provider))


async def refresh_copilot_credential(
    store: CopilotAuthStore,
    provider: str = DEFAULT_PROVIDER,
    *,
    timeout_seconds: float = 20.0,
) -> CopilotOAuthCredential:
    current = store.load_provider(provider)
    credential = _credential_from_dict(current)

    refreshed = await refresh_github_copilot_token(
        credential.refresh,
        enterprise_domain=credential.enterprise_url,
        timeout_seconds=timeout_seconds,
    )

    latest = store.load_provider(provider)
    latest_credential = _credential_from_dict(latest)
    if latest_credential.access != credential.access and not is_expired(latest_credential.expires, skew_ms=0):
        return latest_credential

    merged = dict(latest)
    merged.update(refreshed)
    merged["type"] = "oauth"
    store.save_provider(provider, merged)
    return _credential_from_dict(merged)

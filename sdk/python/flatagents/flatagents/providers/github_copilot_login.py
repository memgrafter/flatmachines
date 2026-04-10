from __future__ import annotations

import argparse
import asyncio
import webbrowser
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

import httpx

from .github_copilot_auth import (
    COPILOT_STATIC_HEADERS,
    DEFAULT_PROVIDER,
    CopilotAuthStore,
    get_urls,
    normalize_domain,
    refresh_github_copilot_token,
    resolve_auth_file,
)
from .github_copilot_types import CopilotOAuthCredential

COPILOT_CLIENT_ID = "Iv1.b507a08c87ecfe98"
DEVICE_FLOW_SCOPE = "read:user"
DEVICE_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:device_code"


class CopilotLoginError(RuntimeError):
    pass


@dataclass
class DeviceCodeResponse:
    device_code: str
    user_code: str
    verification_uri: str
    interval: int
    expires_in: int


async def _fetch_json(
    url: str,
    *,
    method: str = "GET",
    headers: Optional[Dict[str, str]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    timeout_seconds: float = 20.0,
) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        response = await client.request(method, url, headers=headers, json=json_body)

    if response.status_code >= 400:
        raise CopilotLoginError(f"{response.status_code} {response.reason_phrase}: {response.text}")

    payload = response.json()
    if not isinstance(payload, dict):
        raise CopilotLoginError("OAuth endpoint returned non-object JSON")
    return payload


async def start_device_flow(
    domain: str,
    *,
    timeout_seconds: float = 20.0,
    client_id: str = COPILOT_CLIENT_ID,
) -> DeviceCodeResponse:
    urls = get_urls(domain)
    payload = await _fetch_json(
        urls["device_code_url"],
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": COPILOT_STATIC_HEADERS["User-Agent"],
        },
        json_body={"client_id": client_id, "scope": DEVICE_FLOW_SCOPE},
        timeout_seconds=timeout_seconds,
    )

    device_code = payload.get("device_code")
    user_code = payload.get("user_code")
    verification_uri = payload.get("verification_uri")
    interval = payload.get("interval")
    expires_in = payload.get("expires_in")

    if not isinstance(device_code, str) or not device_code:
        raise CopilotLoginError("Invalid device code response: missing device_code")
    if not isinstance(user_code, str) or not user_code:
        raise CopilotLoginError("Invalid device code response: missing user_code")
    if not isinstance(verification_uri, str) or not verification_uri:
        raise CopilotLoginError("Invalid device code response: missing verification_uri")
    if not isinstance(interval, int) or interval <= 0:
        raise CopilotLoginError("Invalid device code response: missing interval")
    if not isinstance(expires_in, int) or expires_in <= 0:
        raise CopilotLoginError("Invalid device code response: missing expires_in")

    return DeviceCodeResponse(
        device_code=device_code,
        user_code=user_code,
        verification_uri=verification_uri,
        interval=interval,
        expires_in=expires_in,
    )


async def poll_for_github_access_token(
    domain: str,
    *,
    device_code: str,
    interval_seconds: int,
    expires_in: int,
    timeout_seconds: float = 20.0,
    client_id: str = COPILOT_CLIENT_ID,
) -> str:
    urls = get_urls(domain)
    deadline = asyncio.get_running_loop().time() + expires_in
    interval = max(1, int(interval_seconds))

    while asyncio.get_running_loop().time() < deadline:
        payload = await _fetch_json(
            urls["access_token_url"],
            method="POST",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": COPILOT_STATIC_HEADERS["User-Agent"],
            },
            json_body={
                "client_id": client_id,
                "device_code": device_code,
                "grant_type": DEVICE_GRANT_TYPE,
            },
            timeout_seconds=timeout_seconds,
        )

        access_token = payload.get("access_token")
        if isinstance(access_token, str) and access_token:
            return access_token

        err = payload.get("error")
        if isinstance(err, str):
            if err == "authorization_pending":
                await asyncio.sleep(interval)
                continue
            if err == "slow_down":
                interval += 5
                await asyncio.sleep(interval)
                continue
            if err == "expired_token":
                raise CopilotLoginError("Device flow expired before authorization completed")
            if err == "access_denied":
                raise CopilotLoginError("Device flow was denied by user")
            raise CopilotLoginError(f"Device flow failed: {err}")

        await asyncio.sleep(interval)

    raise CopilotLoginError("Device flow timed out")


async def login_github_copilot(
    *,
    auth_file: Optional[str] = None,
    provider: str = DEFAULT_PROVIDER,
    enterprise_domain: Optional[str] = None,
    prompt_for_enterprise: bool = False,
    open_browser: bool = True,
    timeout_seconds: float = 20.0,
    input_provider: Optional[Callable[[str], str]] = None,
) -> CopilotOAuthCredential:
    if prompt_for_enterprise and enterprise_domain is None:
        prompt_input = input_provider or input
        entered = prompt_input("GitHub Enterprise URL/domain (blank for github.com): ")
        enterprise_domain = entered.strip() if entered else None

    normalized_enterprise = normalize_domain(enterprise_domain or "")
    if enterprise_domain and not normalized_enterprise:
        raise CopilotLoginError("Invalid GitHub Enterprise URL/domain")

    domain = normalized_enterprise or "github.com"

    device = await start_device_flow(domain, timeout_seconds=timeout_seconds)

    print("Open this URL to authorize GitHub Copilot:")
    print(device.verification_uri)
    print(f"Enter code: {device.user_code}")

    if open_browser:
        try:
            webbrowser.open(device.verification_uri)
        except Exception:
            pass

    github_access_token = await poll_for_github_access_token(
        domain,
        device_code=device.device_code,
        interval_seconds=device.interval,
        expires_in=device.expires_in,
        timeout_seconds=timeout_seconds,
    )

    refreshed = await refresh_github_copilot_token(
        github_access_token,
        enterprise_domain=normalized_enterprise,
        timeout_seconds=timeout_seconds,
    )

    resolved_auth_file = resolve_auth_file(explicit_path=auth_file)
    store = CopilotAuthStore(resolved_auth_file)

    to_save: Dict[str, Any] = {
        "type": "oauth",
        "access": refreshed["access"],
        "refresh": refreshed["refresh"],
        "expires": refreshed["expires"],
        "baseUrl": refreshed.get("baseUrl"),
    }
    if normalized_enterprise:
        to_save["enterpriseUrl"] = normalized_enterprise

    store.save_provider(provider, to_save)

    print(f"Saved GitHub Copilot OAuth credentials for '{provider}' to {resolved_auth_file}")
    return CopilotOAuthCredential(
        access=str(to_save["access"]),
        refresh=str(to_save["refresh"]),
        expires=int(to_save["expires"]),
        enterprise_url=normalized_enterprise,
        base_url=str(to_save["baseUrl"]) if isinstance(to_save.get("baseUrl"), str) else None,
    )


def cli() -> None:
    parser = argparse.ArgumentParser(description="GitHub Copilot OAuth login (device code)")
    parser.add_argument("--auth-file", default=None, help="Override auth.json path")
    parser.add_argument("--provider", default=DEFAULT_PROVIDER, help="Credential provider key")
    parser.add_argument("--enterprise-domain", default=None, help="GitHub Enterprise domain")
    parser.add_argument(
        "--prompt-enterprise",
        action="store_true",
        help="Prompt for GitHub Enterprise domain (blank means github.com)",
    )
    parser.add_argument("--no-browser", action="store_true", help="Do not auto-open browser")
    parser.add_argument("--timeout", type=float, default=20.0, help="HTTP timeout in seconds")
    args = parser.parse_args()

    asyncio.run(
        login_github_copilot(
            auth_file=args.auth_file,
            provider=args.provider,
            enterprise_domain=args.enterprise_domain,
            prompt_for_enterprise=args.prompt_enterprise,
            open_browser=not args.no_browser,
            timeout_seconds=args.timeout,
        )
    )


if __name__ == "__main__":
    cli()

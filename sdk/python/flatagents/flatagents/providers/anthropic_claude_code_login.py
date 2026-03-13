"""
Anthropic Claude Code OAuth login flow.

Implements the PKCE authorization code flow for Anthropic's Claude Code OAuth.
The user authenticates via claude.ai and pastes back the ``code#state`` string.

Usage:
    claude-code-login                    # Interactive login
    claude-code-login --no-browser       # Print URL only
    claude-code-login --auth-file /path  # Custom auth file
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import secrets
import time
import urllib.parse
import webbrowser
from dataclasses import dataclass
from typing import Callable, Optional

import httpx

from .anthropic_claude_code_auth import (
    CLIENT_ID,
    DEFAULT_PROVIDER,
    EXPIRY_BUFFER_MS,
    TOKEN_URL,
    ClaudeCodeAuthError,
    PiAuthStore,
    resolve_auth_file,
)

AUTHORIZE_URL = "https://claude.ai/oauth/authorize"
REDIRECT_URI = "https://console.anthropic.com/oauth/code/callback"
SCOPES = "org:create_api_key user:profile user:inference"


class ClaudeCodeLoginError(RuntimeError):
    """Raised when the login flow fails."""
    pass


@dataclass
class AuthorizationFlow:
    verifier: str
    challenge: str
    state: str
    url: str


@dataclass
class OAuthCredentials:
    access: str
    refresh: str
    expires: int


def _base64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def generate_pkce() -> tuple[str, str]:
    """Generate a PKCE code verifier and S256 challenge."""
    verifier = _base64url(secrets.token_bytes(64))[:128]
    challenge = _base64url(hashlib.sha256(verifier.encode("utf-8")).digest())
    return verifier, challenge


def create_authorization_flow() -> AuthorizationFlow:
    """Build a complete PKCE authorization URL for Anthropic Claude Code.

    The Anthropic OAuth flow uses the verifier itself as the ``state``
    parameter (matching the pi-mono TypeScript implementation).
    """
    verifier, challenge = generate_pkce()

    params = {
        "code": "true",
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": verifier,
    }
    url = AUTHORIZE_URL + "?" + urllib.parse.urlencode(params)
    return AuthorizationFlow(verifier=verifier, challenge=challenge, state=verifier, url=url)


def parse_authorization_input(value: str) -> tuple[Optional[str], Optional[str]]:
    """Parse user-pasted authorization input.

    Accepts:
      - ``code#state``  (Anthropic redirect format)
      - Full URL with ``?code=…&state=…``
      - ``code=…&state=…`` query string
      - Raw code string
    """
    raw = value.strip()
    if not raw:
        return None, None

    # Try as full URL
    try:
        parsed = urllib.parse.urlparse(raw)
        if parsed.scheme and parsed.netloc:
            query = urllib.parse.parse_qs(parsed.query)
            code = query.get("code", [None])[0]
            state = query.get("state", [None])[0]
            return code, state
    except Exception:
        pass

    # code#state
    if "#" in raw:
        code, state = raw.split("#", 1)
        return code or None, state or None

    # code=…&state=…
    if "code=" in raw:
        query = urllib.parse.parse_qs(raw)
        code = query.get("code", [None])[0]
        state = query.get("state", [None])[0]
        return code, state

    # Raw code
    return raw, None


async def exchange_authorization_code(
    *,
    code: str,
    verifier: str,
    redirect_uri: str = REDIRECT_URI,
    token_url: str = TOKEN_URL,
    client_id: str = CLIENT_ID,
) -> OAuthCredentials:
    """Exchange an authorization code for access and refresh tokens.

    Note: Anthropic uses ``application/json`` for the token endpoint
    (not ``application/x-www-form-urlencoded`` like OpenAI).
    """
    # The Anthropic flow includes the state in the exchange request.
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            token_url,
            headers={"Content-Type": "application/json"},
            json={
                "grant_type": "authorization_code",
                "client_id": client_id,
                "code": code,
                "state": verifier,
                "redirect_uri": redirect_uri,
                "code_verifier": verifier,
            },
        )

    if response.status_code >= 400:
        raise ClaudeCodeLoginError(f"Token exchange failed ({response.status_code})")

    payload = response.json()
    access = payload.get("access_token")
    refresh = payload.get("refresh_token")
    expires_in = payload.get("expires_in")
    if not isinstance(access, str) or not isinstance(refresh, str) or not isinstance(expires_in, int):
        raise ClaudeCodeLoginError("Token exchange response missing required fields")

    expires = int(time.time() * 1000) + expires_in * 1000 - EXPIRY_BUFFER_MS
    return OAuthCredentials(access=access, refresh=refresh, expires=expires)


async def login_anthropic_claude_code(
    *,
    auth_file: Optional[str] = None,
    provider: str = DEFAULT_PROVIDER,
    open_browser: bool = True,
    manual_input_provider: Optional[Callable[[], str]] = None,
) -> OAuthCredentials:
    """Run the interactive Anthropic Claude Code OAuth login flow.

    1. Generate PKCE challenge.
    2. Print authorization URL (and optionally open browser).
    3. Wait for user to paste ``code#state``.
    4. Exchange code for tokens.
    5. Save credentials to auth store.

    Args:
        auth_file: Override path to auth.json.
        provider: Key under which credentials are stored (default: ``anthropic``).
        open_browser: Whether to auto-open the browser.
        manual_input_provider: Optional callable returning the pasted code string.
            When ``None``, reads from stdin via ``input()``.
    """
    flow = create_authorization_flow()

    print("Open this URL to authenticate with Anthropic:")
    print(flow.url)
    if open_browser:
        try:
            webbrowser.open(flow.url)
        except Exception:
            pass

    if manual_input_provider is not None:
        raw_input = manual_input_provider()
    else:
        raw_input = input("Paste the authorization code (code#state): ")

    parsed_code, parsed_state = parse_authorization_input(raw_input)

    if not parsed_code:
        raise ClaudeCodeLoginError("Missing authorization code")

    credentials = await exchange_authorization_code(
        code=parsed_code,
        verifier=flow.verifier,
    )

    resolved_auth_file = resolve_auth_file(explicit_path=auth_file)
    store = PiAuthStore(resolved_auth_file)
    store.save_provider(
        provider,
        {
            "type": "oauth",
            "access": credentials.access,
            "refresh": credentials.refresh,
            "expires": credentials.expires,
        },
    )

    print(f"Saved Anthropic Claude Code OAuth credentials for '{provider}' to {resolved_auth_file}")
    return credentials


def cli() -> None:
    """Entry point for the ``claude-code-login`` CLI command."""
    parser = argparse.ArgumentParser(description="Anthropic Claude Code OAuth login")
    parser.add_argument("--auth-file", default=None, help="Override auth.json path")
    parser.add_argument(
        "--provider",
        default=DEFAULT_PROVIDER,
        help=f"Credential provider key (default: {DEFAULT_PROVIDER})",
    )
    parser.add_argument("--no-browser", action="store_true", help="Do not auto-open browser")
    args = parser.parse_args()

    asyncio.run(
        login_anthropic_claude_code(
            auth_file=args.auth_file,
            provider=args.provider,
            open_browser=not args.no_browser,
        )
    )


if __name__ == "__main__":
    cli()

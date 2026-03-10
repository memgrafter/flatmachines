from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import secrets
import threading
import time
import urllib.parse
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Callable, Optional

import httpx

from .openai_codex_auth import (
    DEFAULT_PROVIDER,
    OPENAI_CODEX_CLIENT_ID,
    TOKEN_URL,
    PiAuthStore,
    extract_account_id_from_access_token,
    resolve_auth_file,
)

AUTHORIZE_URL = "https://auth.openai.com/oauth/authorize"
REDIRECT_URI = "http://localhost:1455/auth/callback"
SCOPE = "openid profile email offline_access"
SUCCESS_HTML = """<!doctype html>
<html><body><p>Authentication successful. Return to your terminal.</p></body></html>
"""


class CodexLoginError(RuntimeError):
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
    account_id: str


def _base64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def generate_pkce() -> tuple[str, str]:
    verifier = _base64url(secrets.token_bytes(64))
    verifier = verifier[:128]
    challenge = _base64url(hashlib.sha256(verifier.encode("utf-8")).digest())
    return verifier, challenge


def create_authorization_flow(originator: str = "pi") -> AuthorizationFlow:
    verifier, challenge = generate_pkce()
    state = secrets.token_hex(16)

    params = {
        "response_type": "code",
        "client_id": OPENAI_CODEX_CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPE,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
        "id_token_add_organizations": "true",
        "codex_cli_simplified_flow": "true",
        "originator": originator,
    }
    url = AUTHORIZE_URL + "?" + urllib.parse.urlencode(params)
    return AuthorizationFlow(verifier=verifier, challenge=challenge, state=state, url=url)


def parse_authorization_input(value: str) -> tuple[Optional[str], Optional[str]]:
    raw = value.strip()
    if not raw:
        return None, None

    try:
        parsed = urllib.parse.urlparse(raw)
        if parsed.scheme and parsed.netloc:
            query = urllib.parse.parse_qs(parsed.query)
            code = query.get("code", [None])[0]
            state = query.get("state", [None])[0]
            return code, state
    except Exception:
        pass

    if "#" in raw:
        code, state = raw.split("#", 1)
        return code or None, state or None

    if "code=" in raw:
        query = urllib.parse.parse_qs(raw)
        code = query.get("code", [None])[0]
        state = query.get("state", [None])[0]
        return code, state

    return raw, None


class _CallbackHandler(BaseHTTPRequestHandler):
    shared: dict = {}

    def do_GET(self):  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/auth/callback":
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not found")
            return

        params = urllib.parse.parse_qs(parsed.query)
        expected_state = self.shared.get("state")
        state = params.get("state", [None])[0]
        code = params.get("code", [None])[0]

        if expected_state and state != expected_state:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"State mismatch")
            return

        if not code:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Missing code")
            return

        self.shared["code"] = code
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(SUCCESS_HTML.encode("utf-8"))

    def log_message(self, format, *args):  # noqa: A003
        return


class LocalCallbackServer:
    def __init__(self, expected_state: str):
        self._expected_state = expected_state
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> bool:
        _CallbackHandler.shared = {"state": self._expected_state, "code": None}
        try:
            self._server = HTTPServer(("127.0.0.1", 1455), _CallbackHandler)
        except OSError:
            self._server = None
            return False

        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return True

    def get_code(self) -> Optional[str]:
        return _CallbackHandler.shared.get("code")

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None


async def exchange_authorization_code(
    *,
    code: str,
    verifier: str,
    redirect_uri: str = REDIRECT_URI,
    token_url: str = TOKEN_URL,
    client_id: str = OPENAI_CODEX_CLIENT_ID,
) -> OAuthCredentials:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            token_url,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "authorization_code",
                "client_id": client_id,
                "code": code,
                "code_verifier": verifier,
                "redirect_uri": redirect_uri,
            },
        )

    if response.status_code >= 400:
        raise CodexLoginError(f"Token exchange failed ({response.status_code})")

    payload = response.json()
    access = payload.get("access_token")
    refresh = payload.get("refresh_token")
    expires_in = payload.get("expires_in")
    if not isinstance(access, str) or not isinstance(refresh, str) or not isinstance(expires_in, int):
        raise CodexLoginError("Token exchange response missing required fields")

    account_id = extract_account_id_from_access_token(access)
    expires = int(time.time() * 1000) + expires_in * 1000
    return OAuthCredentials(access=access, refresh=refresh, expires=expires, account_id=account_id)


async def login_openai_codex(
    *,
    auth_file: str | None = None,
    originator: str = "pi",
    provider: str = DEFAULT_PROVIDER,
    open_browser: bool = True,
    allow_local_server: bool = True,
    callback_timeout_seconds: int = 300,
    manual_input_provider: Callable[[], str] | None = None,
) -> OAuthCredentials:
    flow = create_authorization_flow(originator=originator)

    callback = LocalCallbackServer(flow.state)
    callback_started = allow_local_server and callback.start()

    print("Open this URL to authenticate:")
    print(flow.url)
    if open_browser:
        try:
            webbrowser.open(flow.url)
        except Exception:
            pass

    code: Optional[str] = None
    try:
        if callback_started:
            deadline = time.time() + callback_timeout_seconds
            while time.time() < deadline:
                code = callback.get_code()
                if code:
                    break
                await asyncio.sleep(0.1)

        if not code:
            if manual_input_provider is not None:
                manual_input = manual_input_provider()
            else:
                manual_input = input("Paste authorization code (or full redirect URL): ")
            parsed_code, parsed_state = parse_authorization_input(manual_input)
            if parsed_state and parsed_state != flow.state:
                raise CodexLoginError("State mismatch")
            code = parsed_code

        if not code:
            raise CodexLoginError("Missing authorization code")

        credentials = await exchange_authorization_code(code=code, verifier=flow.verifier)

        resolved_auth_file = resolve_auth_file(explicit_path=auth_file)
        store = PiAuthStore(resolved_auth_file)
        store.save_provider(
            provider,
            {
                "type": "oauth",
                "access": credentials.access,
                "refresh": credentials.refresh,
                "expires": credentials.expires,
                "accountId": credentials.account_id,
            },
        )

        print(f"Saved OpenAI Codex OAuth credentials for '{provider}' to {resolved_auth_file}")
        return credentials
    finally:
        callback.stop()


def cli() -> None:
    parser = argparse.ArgumentParser(description="OpenAI Codex OAuth login")
    parser.add_argument("--auth-file", default=None, help="Override auth.json path")
    parser.add_argument("--originator", default="pi", help="OAuth originator value (default: pi)")
    parser.add_argument("--provider", default=DEFAULT_PROVIDER, help="Credential provider key (default: openai-codex)")
    parser.add_argument("--no-browser", action="store_true", help="Do not auto-open browser")
    parser.add_argument("--no-local-server", action="store_true", help="Disable localhost callback and use manual paste")
    parser.add_argument("--timeout", type=int, default=300, help="Callback wait timeout in seconds")
    args = parser.parse_args()

    asyncio.run(
        login_openai_codex(
            auth_file=args.auth_file,
            originator=args.originator,
            provider=args.provider,
            open_browser=not args.no_browser,
            allow_local_server=not args.no_local_server,
            callback_timeout_seconds=args.timeout,
        )
    )


if __name__ == "__main__":
    cli()

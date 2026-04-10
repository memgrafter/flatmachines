from __future__ import annotations

import json
from pathlib import Path


def token_for_proxy_host(proxy_host: str = "proxy.individual.githubcopilot.com") -> str:
    return f"tid=test;exp=9999999999;proxy-ep={proxy_host};foo=bar"


def write_auth_file(
    path: Path,
    *,
    access_token: str,
    refresh_token: str = "github-access-token",
    expires: int = 9_999_999_999_999,
    enterprise_url: str | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    oauth: dict = {
        "type": "oauth",
        "access": access_token,
        "refresh": refresh_token,
        "expires": expires,
    }
    if enterprise_url:
        oauth["enterpriseUrl"] = enterprise_url

    path.write_text(
        json.dumps(
            {
                "github-copilot": oauth,
                "other-provider": {"type": "api_key", "key": "abc"},
            }
        ),
        encoding="utf-8",
    )

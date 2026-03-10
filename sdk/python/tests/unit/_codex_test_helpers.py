from __future__ import annotations

import base64
import json
from pathlib import Path


def token_for_account(account_id: str) -> str:
    payload = {"https://api.openai.com/auth": {"chatgpt_account_id": account_id}}
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8").rstrip("=")
    return f"aaa.{encoded}.bbb"


def write_auth_file(
    path: Path,
    *,
    access_token: str,
    refresh_token: str = "refresh-token",
    expires: int = 9_999_999_999_999,
    account_id: str | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    oauth = {
        "type": "oauth",
        "access": access_token,
        "refresh": refresh_token,
        "expires": expires,
    }
    if account_id:
        oauth["accountId"] = account_id

    path.write_text(
        json.dumps(
            {
                "openai-codex": oauth,
                "other-provider": {"type": "api_key", "key": "abc"},
            }
        ),
        encoding="utf-8",
    )

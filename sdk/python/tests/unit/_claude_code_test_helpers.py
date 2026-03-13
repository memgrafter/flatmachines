from __future__ import annotations

import json
from pathlib import Path


def write_auth_file(
    path: Path,
    *,
    access_token: str = "sk-ant-oat-test-access-token",
    refresh_token: str = "refresh-token",
    expires: int = 9_999_999_999_999,
    provider: str = "anthropic",
) -> None:
    """Write a minimal auth.json with Anthropic OAuth credentials."""
    path.parent.mkdir(parents=True, exist_ok=True)
    oauth = {
        "type": "oauth",
        "access": access_token,
        "refresh": refresh_token,
        "expires": expires,
    }

    path.write_text(
        json.dumps(
            {
                provider: oauth,
                "other-provider": {"type": "api_key", "key": "abc"},
            }
        ),
        encoding="utf-8",
    )

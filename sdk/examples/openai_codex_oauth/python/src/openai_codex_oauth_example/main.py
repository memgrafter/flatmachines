"""
OpenAI Codex OAuth diagnostics.

This demo does not make API calls. It only resolves auth file path and,
optionally, validates that OAuth credentials are present.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from flatagents.providers.openai_codex_auth import (
    DEFAULT_PROVIDER,
    PiAuthStore,
    is_expired,
    load_codex_credential,
    resolve_auth_file,
)


def run(auth_file: str | None, provider: str, require_credential: bool) -> int:
    resolved = resolve_auth_file(explicit_path=auth_file)
    store = PiAuthStore(resolved)

    output = {
        "provider": provider,
        "auth_file": str(Path(resolved).resolve()),
        "credential_loaded": False,
        "expired": None,
        "account_id": None,
    }

    try:
        cred = load_codex_credential(store, provider)
        output["credential_loaded"] = True
        output["expired"] = is_expired(cred.expires)
        output["account_id"] = cred.account_id
    except Exception as exc:
        output["error"] = str(exc)

    print(json.dumps(output, indent=2))

    if require_credential and not output["credential_loaded"]:
        return 1
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="OpenAI Codex OAuth diagnostics")
    parser.add_argument("--auth-file", default=None, help="Override auth file path")
    parser.add_argument("--provider", default=DEFAULT_PROVIDER)
    parser.add_argument("--require-credential", action="store_true")
    args = parser.parse_args()

    raise SystemExit(run(args.auth_file, args.provider, args.require_credential))


if __name__ == "__main__":
    main()

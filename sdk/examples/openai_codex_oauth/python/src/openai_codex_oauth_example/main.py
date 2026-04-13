from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict

import yaml

from flatagents import FlatAgent
from flatagents.providers.openai_codex_auth import (
    DEFAULT_PROVIDER,
    PiAuthStore,
    is_expired,
    load_codex_credential,
    resolve_auth_file,
)
from flatagents.providers.openai_codex_login import CodexLoginError, login_openai_codex

DEFAULT_AUTH_FILE = "~/.agents/flatmachines/auth.json"


def _config_paths() -> tuple[Path, Path]:
    root = Path(__file__).resolve().parents[3]
    config_dir = root / "config"
    return config_dir / "agent.yml", config_dir / "profiles.yml"


def check_auth(auth_file: str | None, provider: str, require_credential: bool) -> int:
    resolved = resolve_auth_file(explicit_path=auth_file)
    store = PiAuthStore(resolved)

    output: Dict[str, Any] = {
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
    except Exception as exc:  # noqa: BLE001
        output["error"] = str(exc)

    print(json.dumps(output, indent=2))

    if require_credential and not output["credential_loaded"]:
        return 1
    return 0


async def run_agent(prompt: str, profile: str) -> int:
    agent_path, profiles_path = _config_paths()
    config = yaml.safe_load(agent_path.read_text(encoding="utf-8")) or {}
    config.setdefault("data", {})
    config["data"]["model"] = profile

    agent = FlatAgent(config_dict=config, profiles_file=str(profiles_path))
    result = await agent.call(task=prompt)

    output = {
        "content": result.content,
        "error": asdict(result.error) if result.error else None,
        "finish_reason": result.finish_reason.value if result.finish_reason else None,
        "usage": asdict(result.usage) if result.usage else None,
    }
    print(json.dumps(output, indent=2))
    return 1 if result.error else 0


async def async_main(args: argparse.Namespace) -> int:
    if args.login_codex:
        allow_local_server = not args.no_local_server
        manual_input_provider = None

        if args.callback_url:
            pasted = args.callback_url
            allow_local_server = False
            manual_input_provider = lambda: pasted
        elif args.paste_callback_url:
            allow_local_server = False
            manual_input_provider = lambda: input("Paste authorization callback URL (or code): ")

        try:
            await login_openai_codex(
                auth_file=args.auth_file,
                originator=args.originator,
                provider=args.provider,
                open_browser=not args.no_browser,
                allow_local_server=allow_local_server,
                callback_timeout_seconds=args.timeout,
                manual_input_provider=manual_input_provider,
            )
            return 0
        except CodexLoginError as exc:
            message = str(exc)
            if "State mismatch" in message:
                print("ERROR: State mismatch. Use a callback URL/code from the SAME login attempt.")
                print("Hint: you can paste only the `code` value to skip state parsing.")
                print("Example: --callback-url \"ac_xxx...\"")
                return 1
            print(f"ERROR: {message}")
            return 1

    if args.run:
        return await run_agent(args.prompt, args.profile)

    return check_auth(args.auth_file, args.provider, args.require_credential)


def main() -> None:
    parser = argparse.ArgumentParser(description="OpenAI Codex OAuth example")
    parser.add_argument("--login-codex", action="store_true", help="Run browser/callback login")
    parser.add_argument("--check-codex-auth", action="store_true", help="Run auth diagnostics")
    parser.add_argument("--run", action="store_true", help="Run a real FlatAgent call using backend: codex")

    parser.add_argument("--auth-file", default=DEFAULT_AUTH_FILE, help="Override auth file path")
    parser.add_argument("--provider", default=DEFAULT_PROVIDER)
    parser.add_argument("--profile", default="codex", help="Model profile name in config/profiles.yml")
    parser.add_argument("--prompt", default="Reply with exactly CODEX_OK", help="Prompt for --run")
    parser.add_argument("--require-credential", action="store_true", help="Exit 1 when credential is missing")

    parser.add_argument("--originator", default="pi")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--no-local-server", action="store_true")
    parser.add_argument(
        "--paste-callback-url",
        action="store_true",
        help="Prompt immediately to paste callback URL/code (remote-friendly)",
    )
    parser.add_argument(
        "--callback-url",
        default=None,
        help="Provide callback URL/code directly (implies --no-local-server)",
    )
    parser.add_argument("--timeout", type=int, default=300, help="Callback wait timeout in seconds")

    args = parser.parse_args()

    if not (args.login_codex or args.check_codex_auth or args.run):
        args.check_codex_auth = True

    raise SystemExit(asyncio.run(async_main(args)))


if __name__ == "__main__":
    main()

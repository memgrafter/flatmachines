from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict

import yaml

from flatagents import FlatAgent
from flatagents.providers.github_copilot_auth import (
    DEFAULT_PROVIDER,
    CopilotAuthStore,
    is_expired,
    load_copilot_credential,
    resolve_auth_file,
)
from flatagents.providers.github_copilot_login import login_github_copilot


def _config_paths() -> tuple[Path, Path]:
    root = Path(__file__).resolve().parents[3]
    config_dir = root / "config"
    return config_dir / "agent.yml", config_dir / "profiles.yml"


def check_auth(auth_file: str | None, provider: str, require_credential: bool) -> int:
    resolved = resolve_auth_file(explicit_path=auth_file)
    store = CopilotAuthStore(resolved)

    output: Dict[str, Any] = {
        "provider": provider,
        "auth_file": str(Path(resolved).resolve()),
        "credential_loaded": False,
        "expired": None,
        "base_url": None,
        "enterprise_url": None,
    }

    try:
        cred = load_copilot_credential(store, provider)
        output["credential_loaded"] = True
        output["expired"] = is_expired(cred.expires)
        output["base_url"] = cred.base_url
        output["enterprise_url"] = cred.enterprise_url
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
    if args.login_copilot:
        await login_github_copilot(
            auth_file=args.auth_file,
            provider=args.provider,
            enterprise_domain=args.enterprise_domain,
            prompt_for_enterprise=args.prompt_enterprise,
            open_browser=not args.no_browser,
            timeout_seconds=args.timeout,
        )
        return 0

    if args.run:
        return await run_agent(args.prompt, args.profile)

    return check_auth(args.auth_file, args.provider, args.require_credential)


def main() -> None:
    parser = argparse.ArgumentParser(description="GitHub Copilot OAuth example")
    parser.add_argument("--login-copilot", action="store_true", help="Run device-code login")
    parser.add_argument("--check-copilot-auth", action="store_true", help="Run auth diagnostics")
    parser.add_argument("--run", action="store_true", help="Run a real FlatAgent call using backend: copilot")

    parser.add_argument("--auth-file", default=None, help="Override auth file path")
    parser.add_argument("--provider", default=DEFAULT_PROVIDER)
    parser.add_argument("--profile", default="copilot", help="Model profile name in config/profiles.yml")
    parser.add_argument("--prompt", default="Reply with exactly COPILOT_OK", help="Prompt for --run")
    parser.add_argument("--require-credential", action="store_true", help="Exit 1 when credential is missing")

    parser.add_argument("--enterprise-domain", default=None)
    parser.add_argument("--prompt-enterprise", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--timeout", type=float, default=20.0)

    args = parser.parse_args()

    if not (args.login_copilot or args.check_copilot_auth or args.run):
        args.check_copilot_auth = True

    raise SystemExit(asyncio.run(async_main(args)))


if __name__ == "__main__":
    main()

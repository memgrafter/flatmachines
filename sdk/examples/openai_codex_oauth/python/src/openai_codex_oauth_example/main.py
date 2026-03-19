from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from flatagents import setup_logging

from .codex_flatagent import CodexFlatAgent
from .openai_codex_login import login_openai_codex


async def run(prompt: str) -> None:
    setup_logging(level="INFO")

    config_file = Path(__file__).parent.parent.parent / "config" / "agent.yml"
    agent = CodexFlatAgent(config_file=str(config_file))

    response = await agent.call(prompt=prompt)
    print("\n=== Assistant ===")
    print(response.content)

    if response.usage:
        print("\n=== Usage ===")
        print(f"input_tokens: {response.usage.input_tokens}")
        print(f"output_tokens: {response.usage.output_tokens}")
        print(f"total_tokens: {response.usage.total_tokens}")
        print(f"cached_tokens: {response.usage.cache_read_tokens}")


async def run_login(auth_file: str | None, originator: str, no_browser: bool) -> None:
    default_auth_file = Path(__file__).parent.parent.parent / "config" / "auth.json"
    target_auth_file = auth_file or str(default_auth_file)
    await login_openai_codex(
        auth_file=target_auth_file,
        originator=originator,
        open_browser=not no_browser,
    )


def cli() -> None:
    parser = argparse.ArgumentParser(description="OpenAI Codex OAuth FlatAgent example")
    parser.add_argument("--login", action="store_true", help="Run OpenAI Codex OAuth login and store credentials")
    parser.add_argument("--auth-file", default=None, help="Override auth.json path for login")
    parser.add_argument("--originator", default="pi", help="OAuth originator value (default: pi)")
    parser.add_argument("--no-browser", action="store_true", help="Do not auto-open browser during login")
    parser.add_argument("--prompt", default=None)
    args = parser.parse_args()

    if args.login:
        asyncio.run(run_login(args.auth_file, args.originator, args.no_browser))
        return

    prompt = args.prompt or "Give me one short sentence explaining FlatAgents."
    asyncio.run(run(prompt))


if __name__ == "__main__":
    cli()

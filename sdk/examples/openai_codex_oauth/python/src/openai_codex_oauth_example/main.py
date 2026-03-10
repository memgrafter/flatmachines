from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from flatagents import setup_logging

from .codex_flatagent import CodexFlatAgent


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


def cli() -> None:
    parser = argparse.ArgumentParser(description="OpenAI Codex OAuth FlatAgent example")
    parser.add_argument("--prompt", default="Give me one short sentence explaining FlatAgents.")
    args = parser.parse_args()
    asyncio.run(run(args.prompt))


if __name__ == "__main__":
    cli()

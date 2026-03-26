"""
Tool Loop Example — demonstrates ToolLoopAgent with two simple tools.

The agent answers a user question by calling get_weather and/or get_time,
then provides a natural-language summary.

Usage:
    python -m flatagent_tool_loop.main
    python -m flatagent_tool_loop.main "What time is it in Tokyo?"
    python -m flatagent_tool_loop.main "What's the weather in London and the time in UTC?"
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from flatagents import FlatAgent, setup_logging, get_logger
from flatagents.tool_loop import ToolLoopAgent, Guardrails, StopReason

from .tools import ALL_TOOLS


setup_logging(level="INFO")
logger = get_logger(__name__)

DEFAULT_QUESTION = "What's the weather in Tokyo and the current time there?"


async def run(question: str) -> None:
    logger.info("--- Starting ToolLoopAgent Demo ---")
    logger.info(f"Question: {question}")

    config_path = Path(__file__).parent.parent.parent.parent / "config" / "agent.yml"
    agent = FlatAgent(config_file=str(config_path))

    loop = ToolLoopAgent(
        agent=agent,
        tools=ALL_TOOLS,
        guardrails=Guardrails(
            max_turns=5,
            max_tool_calls=10,
            tool_timeout=10.0,
            total_timeout=60.0,
        ),
    )

    result = await loop.run(question=question)

    logger.info("--- Execution Complete ---")
    logger.info(f"Stop reason : {result.stop_reason.value}")
    logger.info(f"Turns       : {result.turns}")
    logger.info(f"Tool calls  : {result.tool_calls_count}")
    logger.info(f"API calls   : {result.usage.api_calls}")
    logger.info(f"Total tokens: {result.usage.total_tokens}")
    logger.info(f"Total cost  : ${result.usage.total_cost:.6f}")

    if result.error:
        logger.error(f"Error: {result.error}")

    print()
    print("=== Answer ===")
    print(result.content or "(no content)")
    print()

    if result.stop_reason != StopReason.COMPLETE:
        logger.warning(f"Loop did not complete normally (reason: {result.stop_reason.value})")


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] in {"-h", "--help"}:
        print(__doc__.strip())
        return

    question = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else DEFAULT_QUESTION
    asyncio.run(run(question))


if __name__ == "__main__":
    main()

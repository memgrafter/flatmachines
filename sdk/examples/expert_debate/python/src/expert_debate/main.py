"""Run the expert_debate FlatMachine demo."""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path
from typing import Any, Dict

from flatmachines import FlatMachine, HooksRegistry, get_logger, setup_logging

from .hooks import ExpertDebateHooks

_log_level = os.environ.get("LOG_LEVEL") or os.environ.get("FLATAGENTS_LOG_LEVEL") or "INFO"
setup_logging(level=_log_level)
logger = get_logger(__name__)


def _config_path() -> Path:
    # .../expert_debate/python/src/expert_debate/main.py -> parents[3] == .../expert_debate
    return Path(__file__).resolve().parents[3] / "config" / "machine.yml"


async def run(args: argparse.Namespace) -> Dict[str, Any]:
    registry = HooksRegistry()
    registry.register("expert_debate_hooks", lambda: ExpertDebateHooks(output_dir=args.output_dir or None))

    machine = FlatMachine(
        config_file=str(_config_path()),
        hooks_registry=registry,
    )

    payload = {
        "topic": args.topic or "",
        "audience": args.audience,
        "learning_goal": args.learning_goal,
        "master_a_name": args.master_a_name,
        "master_a_domain": args.master_a_domain,
        "master_a_viewpoint": args.master_a_viewpoint,
        "master_b_name": args.master_b_name,
        "master_b_domain": args.master_b_domain,
        "master_b_viewpoint": args.master_b_viewpoint,
        "round_count": args.round_count,
    }

    logger.info("Starting expert_debate machine...")
    result = await machine.execute(input=payload)

    logger.info("Done.")
    logger.info("Markdown file: %s", result.get("markdown_file"))
    logger.info("Rounds completed: %s", result.get("rounds_completed"))

    print(f"\nMarkdown file: {result.get('markdown_file')}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Expert debate FlatMachine demo")
    parser.add_argument("--topic", default="", help="Debate topic (if omitted, prompted interactively)")
    parser.add_argument("--audience", default="curious generalist")
    parser.add_argument("--learning-goal", default="understand breadth, nuance, and tradeoffs")
    parser.add_argument("--master-a-name", default="Master A")
    parser.add_argument("--master-a-domain", default="systems thinking")
    parser.add_argument(
        "--master-a-viewpoint",
        default="emphasize structural constraints and first principles",
    )
    parser.add_argument("--master-b-name", default="Master B")
    parser.add_argument("--master-b-domain", default="historical and empirical analysis")
    parser.add_argument(
        "--master-b-viewpoint",
        default="emphasize evidence, context, and practical outcomes",
    )
    parser.add_argument("--round-count", type=int, default=2)
    parser.add_argument("--output-dir", default="", help="Optional output directory for markdown transcript")

    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()

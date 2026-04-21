"""
Human-in-the-Loop Demo for FlatAgents.

Demonstrates a workflow where an AI generates content,
then pauses for human approval before completing.
The human can either approve the draft or provide feedback
for the AI to revise.

Usage:
    python -m human_in_loop.main
    # or via run.sh:
    ./run.sh
"""

import argparse
import asyncio
import json
import os
from pathlib import Path
from decimal import Decimal
from typing import Dict, Any, Optional

from flatmachines import FlatMachine, HooksRegistry, setup_logging, get_logger
from .hooks import HumanInLoopHooks

# Configure logging
setup_logging(level='INFO')
logger = get_logger(__name__)


async def run(topic: str = "the benefits of daily exercise", max_revisions: int = 3):
    """
    Run the human-in-the-loop workflow via FlatMachine.

    Args:
        topic: The topic to write about
        max_revisions: Maximum number of revision rounds
    """
    logger.info("=" * 60)
    logger.info("Human-in-the-Loop Demo (FlatMachine)")
    logger.info("=" * 60)

    # Load machine from YAML
    config_path = Path(__file__).parent.parent.parent.parent / 'config' / 'machine.yml'
    hooks = HumanInLoopHooks()
    registry = HooksRegistry()
    registry.register("human-in-loop-hooks", lambda: hooks)
    machine = FlatMachine(
        config_file=str(config_path),
        hooks_registry=registry
    )

    logger.info(f"Machine: {machine.machine_name}")
    logger.info(f"States: {list(machine.states.keys())}")
    logger.info(f"Topic: {topic}")
    logger.info(f"Max Revisions: {max_revisions}")
    logger.info("-" * 60)

    # Execute machine
    result = await machine.execute(input={
        "topic": topic,
        "max_revisions": max_revisions
    })

    # Results
    logger.info("=" * 60)
    logger.info("RESULTS")
    logger.info("=" * 60)
    logger.info(f"Status: {result.get('status', 'unknown')}")
    logger.info(f"Revisions: {result.get('revisions', 0)}")
    logger.info("Final Content:")
    logger.info("-" * 40)
    logger.info(result.get('content', ''))
    logger.info("-" * 40)

    logger.info("--- Statistics ---")
    logger.info(f"Total API calls: {machine.total_api_calls}")
    logger.info(f"Estimated cost: ${machine.total_cost:.4f}")

    return result


def main():
    """Synchronous entry point with CLI args."""
    parser = argparse.ArgumentParser(
        description="Human-in-the-loop content generation"
    )
    parser.add_argument(
        "--topic",
        default="the benefits of daily exercise",
        help="Topic to write about"
    )
    parser.add_argument(
        "--max-revisions",
        type=int,
        default=3,
        help="Maximum number of revisions (default: 3)"
    )
    args = parser.parse_args()
    
    asyncio.run(run(topic=args.topic, max_revisions=args.max_revisions))


if __name__ == "__main__":
    main()

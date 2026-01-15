"""
Parallelism Demo for FlatAgents.

Demonstrates different parallel execution patterns:
1. Parallel machines execution with machine: [a, b, c]
2. Dynamic parallelism with foreach
3. Fire-and-forget launches

Usage:
    python -m parallelism.main
    ./run.sh
"""

import asyncio
import time
from pathlib import Path

from flatagents import FlatMachine, LoggingHooks, setup_logging, get_logger

# Configure logging
setup_logging(level="INFO")
logger = get_logger(__name__)


async def run_basic_parallel():
    """Demonstrate basic parallel machine execution."""
    logger.info("=== Basic Parallel Execution ===")

    config_path = Path(__file__).parent.parent.parent / "config" / "machine.yml"
    machine = FlatMachine(config_file=str(config_path), hooks=LoggingHooks())

    # Run parallel aggregation task
    result = await machine.execute(
        input={
            "type": "parallel_aggregation",
            "texts": [
                "Machine learning is transforming technology",
                "Quantum computing promises exponential speedup",
                "AI assistants are becoming ubiquitous",
            ],
        }
    )

    logger.info(f"Parallel result: {result}")
    logger.info(
        f"API calls: {machine.total_api_calls}, Cost: ${machine.total_cost:.4f}"
    )
    return result


async def run_foreach():
    """Demonstrate dynamic parallelism with foreach."""
    logger.info("=== Dynamic Parallelism (foreach) ===")

    config_path = Path(__file__).parent.parent.parent / "config" / "machine.yml"
    machine = FlatMachine(config_file=str(config_path), hooks=LoggingHooks())

    # Run sentiment analysis on multiple texts
    result = await machine.execute(
        input={
            "type": "foreach_sentiment",
            "texts": [
                "I love this new feature!",
                "This is absolutely terrible.",
                "It's okay, nothing special.",
                "Amazing work, keep it up!",
            ],
        }
    )

    logger.info(f"Foreach result: {result}")
    logger.info(
        f"API calls: {machine.total_api_calls}, Cost: ${machine.total_cost:.4f}"
    )
    return result


async def run_fire_and_forget():
    """Demonstrate fire-and-forget launches."""
    logger.info("=== Fire-and-Forget Launches ===")

    config_path = Path(__file__).parent.parent.parent / "config" / "machine.yml"
    machine = FlatMachine(config_file=str(config_path), hooks=LoggingHooks())

    # Launch background notifications
    result = await machine.execute(
        input={
            "type": "background_notifications",
            "message": "System maintenance scheduled",
        }
    )

    logger.info(f"Fire-and-forget result: {result}")
    logger.info(
        f"API calls: {machine.total_api_calls}, Cost: ${machine.total_cost:.4f}"
    )
    return result


async def run():
    """Run all parallelism examples."""
    logger.info("Starting FlatAgents Parallelism Demo")
    logger.info("====================================")

    start_time = time.time()

    # Run each example
    await run_basic_parallel()
    print()

    await run_foreach()
    print()

    await run_fire_and_forget()

    total_time = time.time() - start_time
    logger.info(f"Completed all examples in {total_time:.2f} seconds")


def main():
    """Main entry point."""
    asyncio.run(run())


if __name__ == "__main__":
    main()

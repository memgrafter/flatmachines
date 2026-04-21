"""
Writer-Critic Demo for FlatAgents.

Demonstrates a multi-agent loop orchestrated by FlatMachine:
1. A writer agent generates marketing taglines
2. A critic agent provides feedback and scores
3. Loop continues until score >= target OR max rounds reached

All orchestration is declarative in machine.yml - no Python loop needed.

Usage:
    python -m writer_critic.main
    # or via run.sh:
    ./run.sh
"""

import asyncio
from pathlib import Path

from flatmachines import FlatMachine, LoggingHooks, setup_logging, get_logger

# Configure logging
setup_logging(level='INFO')
logger = get_logger(__name__)


async def run(product: str = "a CLI tool for AI agents", max_rounds: int = 4, target_score: int = 8):
    """
    Run the writer-critic loop via FlatMachine.

    Args:
        product: The product to write taglines for
        max_rounds: Maximum number of revision rounds
        target_score: Stop when score reaches this threshold
    """
    logger.info("=" * 60)
    logger.info("Writer-Critic Demo (FlatMachine)")
    logger.info("=" * 60)

    # Load machine from YAML - all loop logic is declarative
    config_path = Path(__file__).parent.parent.parent.parent / 'config' / 'machine.yml'
    machine = FlatMachine(
        config_file=str(config_path),
        lifecycle_hooks=LoggingHooks()
    )

    logger.info(f"Machine: {machine.machine_name}")
    logger.info(f"States: {list(machine.states.keys())}")
    logger.info(f"Product: {product}")
    logger.info(f"Target Score: {target_score}/10")
    logger.info(f"Max Rounds: {max_rounds}")
    logger.info("-" * 60)

    # Execute machine - all orchestration is in the YAML
    result = await machine.execute(input={
        "product": product,
        "target_score": target_score,
        "max_rounds": max_rounds
    })

    # Results
    logger.info("=" * 60)
    logger.info("RESULTS")
    logger.info("=" * 60)
    logger.info(f"Final Tagline: \"{result.get('tagline', '')}\"")
    logger.info(f"Final Score: {result.get('score', 0)}/10")
    logger.info(f"Rounds: {result.get('rounds', 0)}")

    logger.info("--- Statistics ---")
    logger.info(f"Total API calls: {machine.total_api_calls}")
    logger.info(f"Estimated cost: ${machine.total_cost:.4f}")

    return result


def main():
    """Synchronous entry point."""
    asyncio.run(run())


if __name__ == "__main__":
    main()

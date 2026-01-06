"""
Support Triage JSON Demo for FlatAgents.

Demonstrates:
- FlatMachine + FlatAgent configs written in JSON
- Hierarchical state machine (parent -> child)
- Agent-only execution states (no custom hooks)

Usage:
    python -m support_triage_json.main
    ./run.sh
"""

import asyncio
from pathlib import Path

from flatagents import FlatMachine, LoggingHooks, setup_logging, get_logger

# Configure logging
setup_logging(level="INFO")
logger = get_logger(__name__)


async def run():
    """Run the support triage demo."""
    logger.info("=" * 60)
    logger.info("Support Triage JSON Demo (FlatMachine)")
    logger.info("=" * 60)

    config_path = Path(__file__).parent.parent.parent / "config" / "machine.json"
    machine = FlatMachine(config_file=str(config_path), hooks=LoggingHooks())

    input_data = {
        "ticket_id": "TCK-1042",
        "customer_message": "My account was charged twice for last month.",
        "customer_tier": "pro",
        "preferred_tone": "friendly"
    }

    logger.info(f"Machine: {machine.machine_name}")
    logger.info(f"States: {list(machine.states.keys())}")
    logger.info(f"Input: {input_data}")
    logger.info("-" * 60)

    result = await machine.execute(input=input_data)

    logger.info("=" * 60)
    logger.info("RESULT")
    logger.info("=" * 60)
    logger.info(result)

    logger.info("--- Statistics ---")
    logger.info(f"Total API calls: {machine.total_api_calls}")
    logger.info(f"Estimated cost: ${machine.total_cost:.4f}")

    return result


def main():
    """Synchronous entry point."""
    asyncio.run(run())


if __name__ == "__main__":
    main()

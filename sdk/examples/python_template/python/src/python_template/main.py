"""
Python Template for FlatMachines.

Demonstrates:
  - Sequential state transitions
  - Parallel fan-out with foreach (map-reduce pattern)
  - SQLite persistence, locking, and config store

Usage:
    python -m python_template.main
    python -m python_template.main --mock
    ./run.sh
    ./run.sh --mock
"""

import argparse
import asyncio
import json
import time
from pathlib import Path

from flatmachines import FlatMachine, LoggingHooks, setup_logging, get_logger

setup_logging(level="INFO")
logger = get_logger(__name__)

SAMPLE_DOCUMENTS = [
    "Python 3.12 introduces significant performance improvements through "
    "the implementation of a specialized adaptive interpreter. The PEP 709 "
    "inlined comprehensions reduce function call overhead substantially.",

    "Q3 revenue increased 15% year-over-year driven by enterprise adoption. "
    "The board approved a $500M share buyback program and raised the dividend "
    "by 8% reflecting strong cash flow generation.",

    "CRISPR-Cas9 gene editing achieved 94% efficiency in the latest clinical "
    "trials for sickle cell disease treatment. The modified cells showed stable "
    "expression at the 18-month follow-up across all patient cohorts.",
]


async def run(use_mock: bool = False):
    logger.info("=== Python Template Demo ===")

    if use_mock:
        logger.info("Using mock LLM backend (no API calls)")
        from python_template.mock_provider import install_mock
        install_mock()

    config_path = Path(__file__).parent.parent.parent.parent / "config" / "machine.yml"
    machine = FlatMachine(
        config_file=str(config_path),
        hooks=LoggingHooks(),
    )

    start = time.time()
    result = await machine.execute(
        input={"documents": SAMPLE_DOCUMENTS},
        max_agent_calls=50,
    )
    elapsed = time.time() - start

    logger.info(f"Completed in {elapsed:.2f}s")
    logger.info(f"API calls: {machine.total_api_calls}, Cost: ${machine.total_cost:.4f}")
    logger.info(f"Result:\n{json.dumps(result, indent=2, default=str)}")

    return result


def main():
    parser = argparse.ArgumentParser(description="FlatMachines Python Template")
    parser.add_argument("--mock", action="store_true", help="Use mock LLM backend")
    args = parser.parse_args()
    asyncio.run(run(use_mock=args.mock))


if __name__ == "__main__":
    main()

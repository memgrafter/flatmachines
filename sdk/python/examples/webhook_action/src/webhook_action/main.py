"""
Webhook Action Demo for FlatAgents.

Demonstrates how to integrate external webhook services using hook actions.
The workflow sends text to a sentiment analysis webhook, receives the results,
and uses an AI agent to provide detailed analysis.

Usage:
    python -m webhook_action.main "Your text here"
    # or via run.sh:
    ./run.sh

Example with custom endpoint:
    python -m webhook_action.main "Great product!" --endpoint https://api.example.com/sentiment

Mock mode (no external calls):
    python -m webhook_action.main "Testing the system" --mock
"""

import argparse
import asyncio
from pathlib import Path
from typing import Optional

from flatagents import FlatMachine, setup_logging, get_logger
from .hooks import WebhookActionHooks

# Configure logging
setup_logging(level='INFO')
logger = get_logger(__name__)


async def run(
    text: str = "I absolutely love this product! It exceeded all my expectations.",
    webhook_endpoint: str = "http://localhost:8000/analyze",
    max_retries: int = 2,
    mock_mode: bool = False
):
    """
    Run the webhook action workflow via FlatMachine.

    Args:
        text: The text to analyze
        webhook_endpoint: URL of the sentiment analysis webhook
        max_retries: Maximum number of webhook retry attempts
        mock_mode: Use mock responses instead of real HTTP calls
    """
    logger.info("=" * 60)
    logger.info("Webhook Action Demo (FlatMachine)")
    logger.info("=" * 60)

    # Load machine from YAML
    config_path = Path(__file__).parent.parent.parent / 'config' / 'machine.yml'
    machine = FlatMachine(
        config_file=str(config_path),
        hooks=WebhookActionHooks(timeout=10.0, mock_mode=mock_mode)
    )

    logger.info(f"Machine: {machine.machine_name}")
    logger.info(f"States: {list(machine.states.keys())}")
    logger.info(f"Webhook Endpoint: {webhook_endpoint}")
    logger.info(f"Mock Mode: {mock_mode}")
    logger.info(f"Text: {text[:100]}...")
    logger.info("-" * 60)

    # Execute machine
    result = await machine.execute(input={
        "text": text,
        "webhook_endpoint": webhook_endpoint,
        "max_retries": max_retries
    })

    # Display results
    logger.info("=" * 60)
    logger.info("RESULTS")
    logger.info("=" * 60)

    status = result.get('status', 'unknown')
    logger.info(f"Status: {status}")

    if status == "success":
        logger.info(f"Sentiment: {result.get('sentiment_label', 'N/A')}")
        logger.info(f"Score: {result.get('sentiment_score', 'N/A')}")
        logger.info(f"Retries: {result.get('retries', 0)}")
        logger.info(f"Timestamp: {result.get('webhook_timestamp', 'N/A')}")
        logger.info("")
        logger.info("Analysis:")
        logger.info("-" * 40)
        logger.info(result.get('analysis', 'N/A'))
        logger.info("-" * 40)
        logger.info("")
        logger.info("Recommendations:")
        logger.info("-" * 40)
        logger.info(result.get('recommendations', 'N/A'))
        logger.info("-" * 40)
    else:
        logger.error(f"Error: {result.get('error', 'Unknown error')}")

    logger.info("")
    logger.info("--- Statistics ---")
    logger.info(f"Total API calls: {machine.total_api_calls}")
    logger.info(f"Estimated cost: ${machine.total_cost:.4f}")

    return result


def main():
    """Synchronous entry point with CLI args."""
    parser = argparse.ArgumentParser(
        description="Webhook action example for sentiment analysis"
    )
    parser.add_argument(
        "text",
        nargs="?",
        default="I absolutely love this product! It exceeded all my expectations.",
        help="Text to analyze for sentiment"
    )
    parser.add_argument(
        "--endpoint",
        default="http://localhost:8000/analyze",
        help="Webhook endpoint URL (default: http://localhost:8000/analyze)"
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=2,
        help="Maximum number of retry attempts (default: 2)"
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Use mock mode (simulate webhook responses)"
    )

    args = parser.parse_args()

    asyncio.run(run(
        text=args.text,
        webhook_endpoint=args.endpoint,
        max_retries=args.max_retries,
        mock_mode=args.mock
    ))


if __name__ == "__main__":
    main()

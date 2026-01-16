"""
Long-Running Job with Callback Demo

Demonstrates checkpoint-safe polling for jobs that take minutes or hours.

Key features:
- Pluggable backends (mock, polling, webhook)
- Survives restarts via checkpointing
- State-based polling loop (not blocking hook)
- Clean separation of concerns

Usage:
    # Mock backend (no external dependencies)
    python -m webhook_callback.main "Process this data" --backend mock

    # Polling backend (real HTTP calls)
    python -m webhook_callback.main "Process this data" \
        --backend polling \
        --endpoint http://localhost:8000/jobs/submit

    # Webhook backend (embedded server)
    python -m webhook_callback.main "Process this data" \
        --backend webhook \
        --endpoint http://localhost:8000/jobs/submit
"""

import argparse
import asyncio
from pathlib import Path
from typing import Optional

from flatagents import FlatMachine, setup_logging, get_logger
from .hooks import LongRunningJobHooks
from .backends import MockBackend, PollingBackend, WebhookServerBackend

# Configure logging
setup_logging(level='INFO')
logger = get_logger(__name__)


async def run(
    text: str = "Analyze this large dataset and extract key insights",
    backend_type: str = "mock",
    job_endpoint: str = "http://localhost:8000/jobs/submit",
    max_polls: int = 20,
    poll_interval: int = 5,
    checkpoint_dir: Optional[str] = None,
):
    """
    Run the long-running job workflow.

    Args:
        text: Data to process
        backend_type: Backend to use (mock, polling, webhook)
        job_endpoint: Job submission endpoint URL
        max_polls: Maximum number of status checks before timeout
        poll_interval: Seconds between status checks
        checkpoint_dir: Directory for checkpoints (enables persistence)
    """
    logger.info("=" * 70)
    logger.info("Long-Running Job with Callback Demo")
    logger.info("=" * 70)

    # Create backend based on type
    if backend_type == "mock":
        backend = MockBackend(
            checks_until_complete=5,  # Completes after 5 checks
            simulate_progress=True
        )
        logger.info("Using MockBackend (simulates long job)")
    elif backend_type == "polling":
        backend = PollingBackend(timeout=30.0)
        logger.info("Using PollingBackend (real HTTP polling)")
    elif backend_type == "webhook":
        backend = WebhookServerBackend(
            host="localhost",
            port=8765,
            fallback_polling=True
        )
        logger.info("Using WebhookServerBackend (embedded HTTP server)")
    else:
        raise ValueError(f"Unknown backend type: {backend_type}")

    # Load machine from YAML
    config_path = Path(__file__).parent.parent.parent / 'config' / 'machine.yml'
    machine = FlatMachine(
        config_file=str(config_path),
        hooks=LongRunningJobHooks(backend=backend),
        checkpoint_dir=checkpoint_dir  # Enable checkpointing if specified
    )

    logger.info(f"Machine: {machine.machine_name}")
    logger.info(f"States: {list(machine.states.keys())}")
    logger.info(f"Backend: {backend.get_backend_type()}")
    logger.info(f"Endpoint: {job_endpoint}")
    logger.info(f"Max Polls: {max_polls}")
    logger.info(f"Poll Interval: {poll_interval}s")
    if checkpoint_dir:
        logger.info(f"Checkpoints: {checkpoint_dir}")
    logger.info("-" * 70)

    # Execute machine
    result = await machine.execute(input={
        "text": text,
        "job_endpoint": job_endpoint,
        "max_polls": max_polls,
        "poll_interval": poll_interval,
    })

    # Display results
    logger.info("=" * 70)
    logger.info("RESULTS")
    logger.info("=" * 70)

    status = result.get('status', 'unknown')
    logger.info(f"Status: {status}")

    if status == "success":
        logger.info(f"Job ID: {result.get('job_id', 'N/A')}")
        logger.info(f"Polls Required: {result.get('polls_required', 0)}")
        logger.info(f"Total Time: {result.get('total_time', 'N/A')}")
        logger.info("")
        logger.info("Job Result:")
        logger.info("-" * 50)
        logger.info(f"{result.get('result', 'N/A')}")
        logger.info("-" * 50)
        logger.info("")
        logger.info("Analysis:")
        logger.info("-" * 50)
        logger.info(result.get('analysis', 'N/A'))
        logger.info("-" * 50)
        logger.info("")
        logger.info("Summary:")
        logger.info("-" * 50)
        logger.info(result.get('summary', 'N/A'))
        logger.info("-" * 50)

    elif status == "timeout":
        logger.warning(f"Job timed out after {result.get('polls_attempted', 0)} polls")
        logger.warning(f"Last status: {result.get('last_status', 'unknown')}")
        logger.warning(f"Last progress: {result.get('last_progress', 0)}%")
        logger.warning(f"Total errors encountered: {result.get('total_errors', 0)}")

    elif status == "polling_error_limit":
        logger.error(f"Polling failed: {result.get('message', 'Unknown error')}")
        logger.error(f"Last error: {result.get('last_error', 'N/A')}")
        logger.error(f"Error type: {result.get('error_type', 'N/A')}")
        logger.error(f"Polls attempted: {result.get('polls_attempted', 0)}")
        logger.error(f"Total errors: {result.get('total_errors', 0)}")

    elif status == "auth_intervention_required":
        logger.warning("=" * 70)
        logger.warning("⚠️  AUTHENTICATION/PAYMENT REQUIRED")
        logger.warning("=" * 70)
        logger.warning(f"Error: {result.get('error', 'N/A')}")
        logger.warning(f"Job ID: {result.get('job_id', 'N/A')}")
        logger.warning(f"Polls attempted: {result.get('polls_attempted', 0)}")
        logger.warning("")
        logger.warning("📋 TO RESUME:")
        logger.warning("1. Fix the authentication or payment issue")
        logger.warning("2. Re-run with the SAME checkpoint directory:")
        logger.warning(f"   python -m webhook_callback.main --checkpoint-dir {checkpoint_dir or './checkpoints'}")
        logger.warning("3. The machine will resume polling the SAME job (no duplicate submission)")
        logger.warning("=" * 70)

    elif status == "polling_permanent_error":
        logger.error(f"Polling failed with permanent error")
        logger.error(f"Error: {result.get('error', 'N/A')}")
        logger.error(f"Error type: {result.get('error_type', 'N/A')}")
        logger.error(f"Job ID: {result.get('job_id', 'N/A')}")
        logger.error(f"Polls attempted: {result.get('polls_attempted', 0)}")
        logger.error("This is likely a configuration error (wrong URL, malformed request, etc)")

    elif status == "failed":
        logger.error(f"Job failed: {result.get('error', 'Unknown error')}")
        logger.error(f"Job ID: {result.get('job_id', 'N/A')}")
        logger.error(f"Polls attempted: {result.get('polls_attempted', 0)}")

    else:
        logger.error(f"Unexpected status: {status}")
        logger.error(f"Error: {result.get('error', 'N/A')}")

    logger.info("")
    logger.info("--- Statistics ---")
    logger.info(f"Total API calls: {machine.total_api_calls}")
    logger.info(f"Estimated cost: ${machine.total_cost:.4f}")

    return result


def main():
    """Synchronous entry point with CLI args."""
    parser = argparse.ArgumentParser(
        description="Long-running job with callback/polling demo",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Mock backend (no external dependencies)
  python -m webhook_callback.main "Process this data" --backend mock

  # Real polling backend
  python -m webhook_callback.main "Process this data" \\
      --backend polling \\
      --endpoint http://localhost:8000/jobs/submit

  # Webhook server backend
  python -m webhook_callback.main "Process this data" \\
      --backend webhook \\
      --endpoint http://localhost:8000/jobs/submit

  # With checkpointing (survives restarts)
  python -m webhook_callback.main "Process this data" \\
      --backend mock \\
      --checkpoint-dir ./checkpoints
        """
    )

    parser.add_argument(
        "text",
        nargs="?",
        default="Analyze this large dataset and extract key insights about customer behavior patterns",
        help="Text/data to process"
    )

    parser.add_argument(
        "--backend",
        choices=["mock", "polling", "webhook"],
        default="mock",
        help="Backend type (default: mock)"
    )

    parser.add_argument(
        "--endpoint",
        default="http://localhost:8000/jobs/submit",
        help="Job submission endpoint (default: http://localhost:8000/jobs/submit)"
    )

    parser.add_argument(
        "--max-polls",
        type=int,
        default=20,
        help="Maximum number of status checks (default: 20)"
    )

    parser.add_argument(
        "--poll-interval",
        type=int,
        default=5,
        help="Seconds between polls (default: 5)"
    )

    parser.add_argument(
        "--checkpoint-dir",
        help="Enable checkpointing to this directory"
    )

    args = parser.parse_args()

    asyncio.run(run(
        text=args.text,
        backend_type=args.backend,
        job_endpoint=args.endpoint,
        max_polls=args.max_polls,
        poll_interval=args.poll_interval,
        checkpoint_dir=args.checkpoint_dir,
    ))


if __name__ == "__main__":
    main()

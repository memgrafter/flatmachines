"""
Signal dispatcher runtime entrypoint.

Process target for systemd/launchd activation. Drains pending signals
and resumes waiting machines.

Usage:
    # One-shot: process all pending signals and exit
    python -m flatmachines.dispatch_signals --once

    # Long-running: listen on UDS for trigger notifications
    python -m flatmachines.dispatch_signals --listen

    # With explicit backends
    python -m flatmachines.dispatch_signals --once \\
        --signal-backend sqlite --db-path ./flatmachines.sqlite \\
        --persistence-backend sqlite --persistence-db-path ./flatmachines.sqlite

    # Listen with custom socket path
    python -m flatmachines.dispatch_signals --listen \\
        --socket-path /tmp/flatmachines/trigger.sock

See SIGNAL_TRIGGER_ACTIVATION_BACKENDS.md for activation recipes.
"""

import argparse
import asyncio
import json
import logging
import sys
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Dispatch pending signals to waiting FlatMachines",
        prog="python -m flatmachines.dispatch_signals",
    )

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--once",
        action="store_true",
        help="Process all pending signals and exit",
    )
    mode.add_argument(
        "--listen",
        action="store_true",
        help="Listen on UDS for trigger notifications (long-running)",
    )

    # Signal backend
    parser.add_argument(
        "--signal-backend",
        choices=["memory", "sqlite"],
        default="sqlite",
        help="Signal backend type (default: sqlite)",
    )
    parser.add_argument(
        "--db-path",
        default="flatmachines.sqlite",
        help="SQLite database path for signal backend (default: flatmachines.sqlite)",
    )

    # Persistence backend
    parser.add_argument(
        "--persistence-backend",
        choices=["memory", "local", "sqlite"],
        default="sqlite",
        help="Persistence backend type (default: sqlite)",
    )
    parser.add_argument(
        "--persistence-db-path",
        help="SQLite database path for persistence backend (defaults to --db-path)",
    )
    parser.add_argument(
        "--checkpoints-dir",
        default=".checkpoints",
        help="Directory for local file persistence backend (default: .checkpoints)",
    )

    # Listen mode options
    parser.add_argument(
        "--socket-path",
        default="/tmp/flatmachines/trigger.sock",
        help="UDS path for listen mode (default: /tmp/flatmachines/trigger.sock)",
    )

    # Logging
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose (DEBUG) logging",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Suppress output except errors",
    )

    return parser


def _setup_logging(verbose: bool = False, quiet: bool = False) -> None:
    level = logging.DEBUG if verbose else (logging.ERROR if quiet else logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )


def _create_signal_backend(backend_type: str, db_path: str):
    from .signals import create_signal_backend
    if backend_type == "sqlite":
        return create_signal_backend("sqlite", db_path=db_path)
    return create_signal_backend(backend_type)


def _create_persistence_backend(
    backend_type: str,
    db_path: Optional[str] = None,
    checkpoints_dir: str = ".checkpoints",
):
    from .persistence import MemoryBackend, LocalFileBackend, SQLiteCheckpointBackend

    if backend_type == "sqlite":
        return SQLiteCheckpointBackend(db_path=db_path or "flatmachines.sqlite")
    elif backend_type == "local":
        return LocalFileBackend(base_dir=checkpoints_dir)
    else:
        return MemoryBackend()


async def _default_resume_fn(execution_id: str, signal_data: Any) -> None:
    """Default resume: re-execute the machine from its checkpoint.

    This loads the machine config from the checkpoint's machine_name and
    resumes execution. For production use, callers should provide a custom
    resume_fn that knows how to reconstruct the full FlatMachine with the
    correct config, hooks, adapters, etc.
    """
    logger.info(f"Default resume: {execution_id} (signal data: {signal_data})")
    logger.warning(
        f"Using default resume_fn for {execution_id}. "
        f"In production, provide a custom resume_fn that reconstructs "
        f"the FlatMachine with appropriate config and backends."
    )


async def run_once(
    signal_backend,
    persistence_backend,
    resume_fn=None,
) -> dict:
    """Process all pending signals and return summary.

    Returns:
        Dict with channel -> list of resumed execution IDs.
    """
    from .dispatcher import SignalDispatcher

    dispatcher = SignalDispatcher(
        signal_backend=signal_backend,
        persistence_backend=persistence_backend,
        resume_fn=resume_fn or _default_resume_fn,
    )

    results = await dispatcher.dispatch_all()

    # Summary
    total_channels = len(results)
    total_resumed = sum(len(ids) for ids in results.values())

    logger.info(
        f"Dispatch complete: {total_channels} channel(s), "
        f"{total_resumed} machine(s) resumed"
    )

    for channel, ids in results.items():
        logger.info(f"  {channel}: {len(ids)} resumed ({', '.join(ids[:3])}{'...' if len(ids) > 3 else ''})")

    return results


async def run_listen(
    signal_backend,
    persistence_backend,
    socket_path: str = "/tmp/flatmachines/trigger.sock",
    resume_fn=None,
    stop_event: Optional[asyncio.Event] = None,
) -> None:
    """Listen on UDS for trigger notifications and dispatch signals.

    Runs until stop_event is set or the process is terminated.
    """
    from .dispatcher import SignalDispatcher

    dispatcher = SignalDispatcher(
        signal_backend=signal_backend,
        persistence_backend=persistence_backend,
        resume_fn=resume_fn or _default_resume_fn,
    )

    # Drain any pending signals before entering listen loop
    pending = await dispatcher.dispatch_all()
    if pending:
        total = sum(len(ids) for ids in pending.values())
        logger.info(f"Drained {total} pending signal(s) before listen")

    await dispatcher.listen(
        socket_path=socket_path,
        stop_event=stop_event,
    )


async def _async_main(args) -> int:
    """Async entry point. Returns exit code."""
    signal_backend = _create_signal_backend(args.signal_backend, args.db_path)
    persistence_backend = _create_persistence_backend(
        args.persistence_backend,
        db_path=args.persistence_db_path or args.db_path,
        checkpoints_dir=args.checkpoints_dir,
    )

    if args.once:
        results = await run_once(signal_backend, persistence_backend)
        total = sum(len(ids) for ids in results.values())
        return 0

    elif args.listen:
        await run_listen(
            signal_backend,
            persistence_backend,
            socket_path=args.socket_path,
        )
        return 0

    return 1


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    _setup_logging(verbose=args.verbose, quiet=args.quiet)

    try:
        exit_code = asyncio.run(_async_main(args))
        sys.exit(exit_code)
    except KeyboardInterrupt:
        logger.info("Interrupted")
        sys.exit(0)
    except Exception as e:
        logger.exception(f"Dispatcher failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

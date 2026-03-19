"""
Signal dispatcher runtime entrypoint.

Process target for systemd/launchd activation. Drains pending signals
and resumes waiting machines.

Usage:
    # One-shot: process all pending signals and exit
    python -m flatmachines.dispatch_signals --once --resumer config-store

    # Long-running: listen on UDS for trigger notifications
    python -m flatmachines.dispatch_signals --listen --resumer config-store

    # With explicit backends
    python -m flatmachines.dispatch_signals --once \\
        --resumer config-store \\
        --signal-backend sqlite --db-path ./flatmachines.sqlite \\
        --persistence-backend sqlite --persistence-db-path ./flatmachines.sqlite

    # Listen with custom socket path
    python -m flatmachines.dispatch_signals --listen \\
        --resumer config-store \\
        --socket-path /tmp/flatmachines/trigger.sock

    # Diagnostics only: allow no-op resume behavior
    python -m flatmachines.dispatch_signals --once --allow-noop-resume

See SIGNAL_TRIGGER_ACTIVATION_BACKENDS.md for activation recipes.
"""

import argparse
import asyncio
import logging
import sys
from typing import Any, Callable, Coroutine, Optional

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

    # Resume strategy
    parser.add_argument(
        "--resumer",
        choices=["config-store"],
        help=(
            "Resume strategy for reconstructing parked machines. "
            "Required unless --allow-noop-resume is set."
        ),
    )
    parser.add_argument(
        "--allow-noop-resume",
        action="store_true",
        help=(
            "Allow no-op fallback resume (diagnostics only). "
            "Without this flag, CLI fails fast when no --resumer is provided."
        ),
    )

    # Config-store resumer options
    parser.add_argument(
        "--config-store-backend",
        choices=["auto", "sqlite", "local", "memory"],
        default="auto",
        help=(
            "Config store backend for --resumer config-store "
            "(default: auto, derived from persistence backend)."
        ),
    )
    parser.add_argument(
        "--config-store-db-path",
        help=(
            "SQLite DB path for config-store backend. "
            "Defaults to --persistence-db-path (or --db-path)."
        ),
    )
    parser.add_argument(
        "--config-store-dir",
        default=".checkpoints",
        help=(
            "Directory for local config-store backend "
            "(default: .checkpoints)."
        ),
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


def _create_config_store(
    backend_type: str,
    persistence_backend,
    *,
    db_path: Optional[str],
    checkpoints_dir: str,
):
    """Create/configure a ConfigStore instance for CLI resumer wiring."""
    from .persistence import (
        LocalFileBackend,
        LocalFileConfigStore,
        MemoryConfigStore,
        SQLiteCheckpointBackend,
    )

    if backend_type == "auto":
        if hasattr(persistence_backend, "config_store"):
            return persistence_backend.config_store
        if isinstance(persistence_backend, SQLiteCheckpointBackend):
            return persistence_backend.config_store
        if isinstance(persistence_backend, LocalFileBackend):
            return LocalFileConfigStore(base_dir=checkpoints_dir)
        return MemoryConfigStore()

    if backend_type == "sqlite":
        sqlite_backend = (
            persistence_backend
            if isinstance(persistence_backend, SQLiteCheckpointBackend)
            else SQLiteCheckpointBackend(db_path=db_path or "flatmachines.sqlite")
        )
        return sqlite_backend.config_store

    if backend_type == "local":
        return LocalFileConfigStore(base_dir=checkpoints_dir)

    return MemoryConfigStore()


def _create_cli_resumer(args, signal_backend, persistence_backend):
    """Build a MachineResumer from CLI args, if configured."""
    if args.resumer != "config-store":
        return None

    from .resume import ConfigStoreResumer

    config_store_db_path = args.config_store_db_path or args.persistence_db_path or args.db_path
    config_store_dir = args.config_store_dir or args.checkpoints_dir
    config_store = _create_config_store(
        args.config_store_backend,
        persistence_backend,
        db_path=config_store_db_path,
        checkpoints_dir=config_store_dir,
    )

    return ConfigStoreResumer(signal_backend, persistence_backend, config_store)


async def _default_resume_fn(execution_id: str, signal_data: Any) -> None:
    """Fallback resume: logs a warning and does nothing.

    Intended for diagnostics/tests only. CLI users should provide a real
    resumer strategy (or explicitly opt in via ``--allow-noop-resume``).

    Used only when neither a ``MachineResumer`` nor a ``resume_fn`` is
    provided. In practice you should always pass one of:

    - ``resumer=ConfigFileResumer(signal_backend, persistence)``
    - ``resume_fn=my_custom_async_callback``
    """
    logger.info(f"Default resume: {execution_id} (signal data: {signal_data})")
    logger.warning(
        f"Using default resume_fn for {execution_id}. "
        f"Provide a MachineResumer (e.g. ConfigFileResumer) or a custom "
        f"resume_fn that reconstructs the FlatMachine with appropriate "
        f"config and backends."
    )


def _resolve_resume(
    signal_backend,
    persistence_backend,
    resumer=None,
    resume_fn=None,
):
    """Return (resumer, resume_fn) with sensible defaults.

    Priority:
      1. Explicit ``resumer`` — used as-is.
      2. Explicit ``resume_fn`` — used as-is.
      3. Neither — fall back to ``_default_resume_fn`` (logs warning).
    """
    from .resume import MachineResumer
    if resumer is not None:
        return resumer, None
    if resume_fn is not None:
        return None, resume_fn
    return None, _default_resume_fn


async def run_once(
    signal_backend,
    persistence_backend,
    resume_fn: Optional[Callable[[str, Any], Coroutine]] = None,
    *,
    resumer=None,
) -> dict:
    """Process all pending signals and return summary.

    Args:
        signal_backend: Where signals are stored.
        persistence_backend: Where machine checkpoints live.
        resume_fn: Async callback(execution_id, signal_data). Legacy API.
        resumer: A ``MachineResumer`` instance (preferred over resume_fn).

    Returns:
        Dict with channel -> list of resumed execution IDs.
    """
    from .dispatcher import SignalDispatcher

    resolved_resumer, resolved_fn = _resolve_resume(
        signal_backend, persistence_backend, resumer, resume_fn,
    )

    dispatcher = SignalDispatcher(
        signal_backend=signal_backend,
        persistence_backend=persistence_backend,
        resume_fn=resolved_fn,
        resumer=resolved_resumer,
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
    resume_fn: Optional[Callable[[str, Any], Coroutine]] = None,
    stop_event: Optional[asyncio.Event] = None,
    *,
    resumer=None,
) -> None:
    """Listen on UDS for trigger notifications and dispatch signals.

    Runs until stop_event is set or the process is terminated.

    Args:
        signal_backend: Where signals are stored.
        persistence_backend: Where machine checkpoints live.
        socket_path: Path for the Unix domain socket.
        resume_fn: Async callback(execution_id, signal_data). Legacy API.
        stop_event: Set to stop the listener.
        resumer: A ``MachineResumer`` instance (preferred over resume_fn).
    """
    from .dispatcher import SignalDispatcher

    resolved_resumer, resolved_fn = _resolve_resume(
        signal_backend, persistence_backend, resumer, resume_fn,
    )

    dispatcher = SignalDispatcher(
        signal_backend=signal_backend,
        persistence_backend=persistence_backend,
        resume_fn=resolved_fn,
        resumer=resolved_resumer,
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

    cli_resumer = _create_cli_resumer(args, signal_backend, persistence_backend)
    if cli_resumer is None and not args.allow_noop_resume:
        logger.error(
            "No resume strategy configured. "
            "Pass --resumer config-store (recommended) or explicitly opt in to "
            "diagnostic no-op mode with --allow-noop-resume."
        )
        return 2

    if args.once:
        await run_once(
            signal_backend,
            persistence_backend,
            resumer=cli_resumer,
        )
        return 0

    elif args.listen:
        await run_listen(
            signal_backend,
            persistence_backend,
            socket_path=args.socket_path,
            resumer=cli_resumer,
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

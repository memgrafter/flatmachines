"""
Lifecycle helpers for FlatMachine checkpoint and restore.

Three functions:
1. resilient_run()       — Run a machine with auto-retry via checkpoints.
2. list_executions()     — Scan a persistence backend for execution snapshots.
3. cleanup_executions()  — Remove old checkpoint data.
"""

import asyncio
import logging
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .persistence import (
    PersistenceBackend,
    LocalFileBackend,
    MemoryBackend,
    CheckpointManager,
    MachineSnapshot,
)
from .locking import ExecutionLock

logger = logging.getLogger(__name__)


async def resilient_run(
    *,
    config_file: Optional[str] = None,
    config_dict: Optional[Dict] = None,
    hooks=None,
    input: Optional[Dict[str, Any]] = None,
    max_steps: int = 1000,
    max_retries: int = 3,
    retry_delay: float = 1.0,
    hooks_factory: Optional[Callable] = None,
    backend: Optional[PersistenceBackend] = None,
    lock: Optional[ExecutionLock] = None,
    **machine_kwargs,
) -> Dict[str, Any]:
    """Run a machine with automatic checkpoint-based retry.

    On failure, resumes from the latest checkpoint so completed work
    is not repeated.

    Args:
        config_file: Path to machine YAML/JSON config.
        config_dict: Inline machine config dict.
        hooks: MachineHooks instance (reused across retries unless
            *hooks_factory* is provided).
        input: Input dict for the machine.
        max_steps: Max state transitions per attempt.
        max_retries: Retries after initial failure (default 3).
        retry_delay: Seconds between retries (default 1.0).
        hooks_factory: Callable returning fresh hooks per attempt
            (useful when hooks carry mutable state).
        backend: Persistence backend (default: ``LocalFileBackend``).
        lock: Execution lock.
        **machine_kwargs: Extra keyword arguments for FlatMachine.

    Returns:
        The final output dict from the machine.

    Raises:
        The last exception if all retries are exhausted.
    """
    from .flatmachine import FlatMachine

    backend = backend or LocalFileBackend()
    execution_id: Optional[str] = None
    last_error: Optional[Exception] = None

    for attempt in range(1 + max_retries):
        current_hooks = hooks_factory() if hooks_factory else hooks
        machine = FlatMachine(
            config_file=config_file,
            config_dict=config_dict,
            hooks=current_hooks,
            persistence=backend,
            lock=lock,
            **machine_kwargs,
        )
        if execution_id is None:
            execution_id = machine.execution_id

        try:
            if attempt == 0:
                return await machine.execute(input=input, max_steps=max_steps)
            else:
                return await machine.execute(
                    input=input, max_steps=max_steps,
                    resume_from=execution_id,
                )
        except Exception as exc:
            last_error = exc
            logger.warning(
                "Execution %s attempt %d/%d failed: %s",
                execution_id, attempt + 1, 1 + max_retries, exc,
            )
            if attempt < max_retries:
                await asyncio.sleep(retry_delay)

    raise last_error  # type: ignore[misc]


async def list_executions(
    backend: PersistenceBackend,
    execution_ids: List[str],
) -> List[MachineSnapshot]:
    """Load the latest snapshot for each execution ID.

    Returns snapshots sorted by created_at (newest first).
    Silently skips IDs with no checkpoint data.

    Args:
        backend: The persistence backend to read from.
        execution_ids: Execution IDs to look up.

    Returns:
        List of MachineSnapshot objects.
    """
    snapshots: List[MachineSnapshot] = []
    for eid in execution_ids:
        snap = await CheckpointManager(backend, eid).load_latest()
        if snap is not None:
            snapshots.append(snap)
    snapshots.sort(key=lambda s: s.created_at, reverse=True)
    return snapshots


async def cleanup_executions(
    backend: PersistenceBackend,
    execution_ids: List[str],
    *,
    older_than: Optional[timedelta] = None,
) -> List[str]:
    """Delete checkpoint data for executions matching criteria.

    For ``LocalFileBackend``, removes the execution's checkpoint directory.
    For ``MemoryBackend``, removes the ``latest`` pointer key (individual
    step keys are not discoverable without filesystem access).

    Args:
        backend: The persistence backend.
        execution_ids: Execution IDs to consider for removal.
        older_than: Only remove executions created before ``now - older_than``.
            If ``None``, removes all listed executions.

    Returns:
        List of removed execution IDs.
    """
    cutoff = (
        datetime.now(timezone.utc) - older_than
        if older_than is not None
        else None
    )
    removed: List[str] = []

    for eid in execution_ids:
        if cutoff is not None:
            snap = await CheckpointManager(backend, eid).load_latest()
            if snap is not None:
                try:
                    created = datetime.fromisoformat(snap.created_at)
                    if created.tzinfo is None:
                        created = created.replace(tzinfo=timezone.utc)
                    if created >= cutoff:
                        continue
                except (ValueError, TypeError):
                    pass  # Can't parse — skip time filter

        # Remove checkpoint data
        if isinstance(backend, LocalFileBackend):
            exec_dir = Path(backend.base_dir) / eid
            if exec_dir.exists() and exec_dir.is_dir():
                shutil.rmtree(exec_dir)
        elif isinstance(backend, MemoryBackend):
            # Remove known keys from the in-memory store
            keys_to_remove = [
                k for k in list(backend._store.keys())
                if k.startswith(f"{eid}/")
            ]
            for k in keys_to_remove:
                await backend.delete(k)
        else:
            # Generic fallback: delete the latest pointer
            await backend.delete(f"{eid}/latest")

        removed.append(eid)
        logger.info("Cleaned up execution %s", eid)

    return removed


__all__ = ["resilient_run", "list_executions", "cleanup_executions"]

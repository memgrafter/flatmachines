"""
Lifecycle helpers for FlatMachine checkpoint and restore.

Two functions:
1. list_executions()     — Scan a persistence backend for execution snapshots.
2. cleanup_executions()  — Remove old checkpoint data.

For resilient execution with auto-retry, use ``persistence.resume`` in your
machine config instead of wrapping execution externally::

    persistence:
      enabled: true
      backend: local
      resume:
        max_retries: 3
        backoffs: [2, 8, 16]
        jitter: 0.1
"""

import logging
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .persistence import (
    PersistenceBackend,
    LocalFileBackend,
    MemoryBackend,
    CheckpointManager,
    MachineSnapshot,
)

logger = logging.getLogger(__name__)


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


__all__ = ["list_executions", "cleanup_executions"]

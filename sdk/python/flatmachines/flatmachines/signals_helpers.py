"""
Composition helpers over signal and trigger backends.

This module provides convenience functions that combine SignalBackend and
TriggerBackend operations. It is intentionally separate from signals.py,
which defines the protocols and their implementations.

The primary helper — send_and_notify — eliminates the footgun where callers
persist a signal but forget to notify the trigger backend, leaving the
signal durable but undiscovered until the next poll/restart.
"""

import logging
from typing import Any

from .signals import SignalBackend, TriggerBackend

logger = logging.getLogger(__name__)

__all__ = ["send_and_notify"]


async def send_and_notify(
    signal_backend: SignalBackend,
    trigger_backend: TriggerBackend,
    channel: str,
    data: Any,
) -> str:
    """Persist a signal and notify the trigger backend in one call.

    The signal is persisted first (durability). The trigger notification is
    best-effort — if it fails, the signal is still durable in the signal
    backend and will be picked up on the next poll or dispatcher restart.

    Args:
        signal_backend: Where the signal is durably stored.
        trigger_backend: Wake hint transport (file touch, UDS datagram, etc.).
        channel: Named channel (e.g., "approval/task-001").
        data: Signal payload (JSON-serializable).

    Returns:
        Signal ID from the signal backend.
    """
    signal_id = await signal_backend.send(channel, data)
    logger.debug(f"Signal persisted: {channel} ({signal_id})")

    try:
        await trigger_backend.notify(channel)
        logger.debug(f"Trigger notified: {channel}")
    except Exception:
        # Trigger is best-effort — signal is already durable
        logger.debug(
            f"Trigger notify failed for {channel}, signal {signal_id} is still durable"
        )

    return signal_id

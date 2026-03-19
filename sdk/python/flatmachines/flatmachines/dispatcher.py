"""
Signal dispatcher — bridges signals to waiting machine resume.

The dispatcher queries the signal backend for pending signals, finds
machines blocked on matching channels, and resumes them.

Usage patterns:
  - Poll mode: call dispatch_all() on a timer or at startup
  - UDS listener: call listen() to bind a Unix domain socket and
    dispatch on each incoming datagram (SocketTrigger sends these)
"""

import asyncio
import logging
import socket
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, List, Optional

from .persistence import PersistenceBackend
from .resume import MachineResumer
from .signals import SignalBackend

logger = logging.getLogger(__name__)


class SignalDispatcher:
    """Dispatches signals to waiting machines.

    Consumes signals from the signal backend, finds machines whose latest
    checkpoint has a matching waiting_channel, and calls the resume callback.

    Resume can be provided as either:
    - A ``MachineResumer`` instance (preferred): ``resumer=ConfigFileResumer(...)``
    - A bare async callback: ``resume_fn=my_async_fn``

    If both are provided, ``resumer`` takes precedence.
    """

    def __init__(
        self,
        signal_backend: SignalBackend,
        persistence_backend: PersistenceBackend,
        resume_fn: Optional[Callable[[str, Any], Coroutine]] = None,
        *,
        resumer: Optional[MachineResumer] = None,
    ):
        """
        Args:
            signal_backend: Where signals are stored
            persistence_backend: Where machine checkpoints live
            resume_fn: async callback(execution_id, signal_data) to resume a machine.
                       If None, dispatcher just returns the IDs to resume.
            resumer: MachineResumer instance (preferred over resume_fn).
        """
        self.signal_backend = signal_backend
        self.persistence_backend = persistence_backend
        if resumer is not None:
            self.resume_fn = resumer.resume
        else:
            self.resume_fn = resume_fn

    async def dispatch(self, channel: str) -> List[str]:
        """Process one signal on a channel.

        If no machines are currently waiting on this channel, leaves queued
        signals untouched (durable backlog) and returns immediately.

        Otherwise consumes one signal, fans out one copy per waiting machine,
        then resumes each. Each machine consumes its copy on resume.

        Works for both addressed (1 waiter) and broadcast (N waiters).

        Returns:
            List of execution IDs that were resumed
        """
        # Find machines waiting on this channel first. If none, avoid
        # consume+requeue churn and preserve backlog order in signal storage.
        execution_ids = await self.persistence_backend.list_execution_ids(
            waiting_channel=channel
        )

        if not execution_ids:
            logger.debug(
                f"No waiting machines on '{channel}'. "
                f"Leaving queued signals untouched."
            )
            return []

        signal = await self.signal_backend.consume(channel)
        if signal is None:
            return []

        # Fan out: one copy per waiter so each machine can consume on resume
        for _ in execution_ids:
            await self.signal_backend.send(channel, signal.data)

        resumed = []
        for eid in execution_ids:
            logger.info(f"Resuming {eid} from signal on '{channel}'")
            if self.resume_fn:
                try:
                    await self.resume_fn(eid, signal.data)
                    resumed.append(eid)
                except Exception as e:
                    logger.error(f"Failed to resume {eid}: {e}")
            else:
                resumed.append(eid)

        return resumed

    async def dispatch_channel(
        self,
        channel: str,
        *,
        max_signals: Optional[int] = None,
    ) -> List[str]:
        """Drain a channel by dispatching until no progress is possible.

        Stops when:
        - no resume occurred for the next dispatch attempt, or
        - ``max_signals`` dispatches have been processed.

        Args:
            channel: Channel name to drain.
            max_signals: Optional per-call cap to prevent unbounded work.

        Returns:
            Flat list of resumed execution IDs across all drained dispatches.
        """
        resumed_all: List[str] = []
        processed = 0

        while True:
            if max_signals is not None and processed >= max_signals:
                break

            resumed = await self.dispatch(channel)
            if not resumed:
                break

            resumed_all.extend(resumed)
            processed += 1

        return resumed_all

    async def dispatch_all(self) -> Dict[str, List[str]]:
        """Process all pending signals across all channels.

        Drains each discovered channel until no further resumes are possible,
        allowing a single wake/run to clear backlog.

        To avoid pathological infinite loops with custom/non-consuming resume
        callbacks, each channel drain is capped to the channel's backlog size
        observed at the start of dispatch_all().

        Returns:
            Dict of channel -> list of resumed execution IDs
        """
        results = {}
        channels = await self.signal_backend.channels()
        for channel in channels:
            pending = await self.signal_backend.peek(channel)
            max_signals = len(pending) if pending else 1
            resumed = await self.dispatch_channel(channel, max_signals=max_signals)
            if resumed:
                results[channel] = resumed
        return results

    async def listen(
        self,
        socket_path: str = "/tmp/flatmachines/trigger.sock",
        stop_event: Optional[asyncio.Event] = None,
    ) -> None:
        """Listen on a Unix domain socket for trigger notifications.

        Binds a SOCK_DGRAM socket and dispatches on each incoming datagram.
        The datagram payload is the channel name (UTF-8 encoded).

        This is the receiver side of SocketTrigger.

        Args:
            socket_path: Path for the UDS
            stop_event: Set this to stop the listener
        """
        path = Path(socket_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        # Clean up stale socket
        if path.exists():
            path.unlink()

        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        sock.bind(str(path))
        # Blocking with timeout — recv blocks in executor thread, timeout
        # lets us check stop_event periodically
        sock.settimeout(1.0)

        loop = asyncio.get_event_loop()
        logger.info(f"Dispatcher listening on {socket_path}")

        def _recv():
            try:
                return sock.recv(4096)
            except socket.timeout:
                return None
            except OSError:
                return None

        try:
            while not (stop_event and stop_event.is_set()):
                data = await loop.run_in_executor(None, _recv)
                if data is None:
                    continue
                channel = data.decode("utf-8").strip()
                if channel:
                    logger.debug(f"Trigger received for channel: {channel}")
                    pending = await self.signal_backend.peek(channel)
                    max_signals = len(pending) if pending else 1
                    await self.dispatch_channel(channel, max_signals=max_signals)
        finally:
            sock.close()
            path.unlink(missing_ok=True)
            logger.info("Dispatcher stopped")


__all__ = ["SignalDispatcher"]

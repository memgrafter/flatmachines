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

from .persistence import PersistenceBackend, CheckpointManager
from .signals import SignalBackend, TriggerBackend

logger = logging.getLogger(__name__)


class SignalDispatcher:
    """Dispatches signals to waiting machines.

    Consumes signals from the signal backend, finds machines whose latest
    checkpoint has a matching waiting_channel, and calls the resume callback.
    """

    def __init__(
        self,
        signal_backend: SignalBackend,
        persistence_backend: PersistenceBackend,
        resume_fn: Optional[Callable[[str, Any], Coroutine]] = None,
    ):
        """
        Args:
            signal_backend: Where signals are stored
            persistence_backend: Where machine checkpoints live
            resume_fn: async callback(execution_id, signal_data) to resume a machine.
                       If None, dispatcher just returns the IDs to resume.
        """
        self.signal_backend = signal_backend
        self.persistence_backend = persistence_backend
        self.resume_fn = resume_fn

    async def dispatch(self, channel: str) -> List[str]:
        """Process one signal on a channel.

        Consumes the next signal, finds waiting machines, and resumes them.

        Returns:
            List of execution IDs that were resumed
        """
        signal = await self.signal_backend.consume(channel)
        if signal is None:
            return []

        # Find machines waiting on this channel
        execution_ids = await self.persistence_backend.list_execution_ids(
            waiting_channel=channel
        )

        if not execution_ids:
            logger.warning(
                f"Signal on '{channel}' but no waiting machines. "
                f"Re-queuing signal."
            )
            # Put it back — no one to consume it
            await self.signal_backend.send(channel, signal.data)
            return []

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

    async def dispatch_all(self) -> Dict[str, List[str]]:
        """Process all pending signals across all channels.

        Returns:
            Dict of channel -> list of resumed execution IDs
        """
        results = {}
        channels = await self.signal_backend.channels()
        for channel in channels:
            resumed = await self.dispatch(channel)
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
        sock.setblocking(False)

        loop = asyncio.get_event_loop()
        logger.info(f"Dispatcher listening on {socket_path}")

        try:
            while not (stop_event and stop_event.is_set()):
                try:
                    data = await asyncio.wait_for(
                        loop.run_in_executor(None, lambda: sock.recv(4096)),
                        timeout=1.0,
                    )
                    channel = data.decode("utf-8").strip()
                    if channel:
                        logger.debug(f"Trigger received for channel: {channel}")
                        await self.dispatch(channel)
                except asyncio.TimeoutError:
                    continue
                except OSError:
                    if stop_event and stop_event.is_set():
                        break
                    raise
        finally:
            sock.close()
            path.unlink(missing_ok=True)
            logger.info("Dispatcher stopped")


__all__ = ["SignalDispatcher"]

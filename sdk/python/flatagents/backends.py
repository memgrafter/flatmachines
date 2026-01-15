"""
Result backends for FlatMachine inter-machine communication.

Result backends handle the storage and retrieval of machine execution results,
enabling machines to read outputs from peer machines they launched.

URI Scheme: flatagents://{execution_id}/[checkpoint|result]
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


def make_uri(execution_id: str, path: str = "result") -> str:
    """Generate a FlatAgents URI for a given execution and path.

    Args:
        execution_id: Unique execution identifier
        path: URI path component (default: "result")

    Returns:
        URI string in format flatagents://{execution_id}/{path}
    """
    return f"flatagents://{execution_id}/{path}"


def parse_uri(uri: str) -> tuple[str, str]:
    """Parse a FlatAgents URI into execution_id and path.

    Args:
        uri: URI in format flatagents://{execution_id}/{path}

    Returns:
        Tuple of (execution_id, path)

    Raises:
        ValueError: If URI format is invalid
    """
    if not uri.startswith("flatagents://"):
        raise ValueError(f"Invalid FlatAgents URI: {uri}")

    rest = uri[len("flatagents://"):]
    parts = rest.split("/", 1)

    if len(parts) == 1:
        return parts[0], "result"
    return parts[0], parts[1]


@dataclass
class LaunchIntent:
    """
    Launch intent for outbox pattern.
    Recorded in checkpoint before launching to ensure exactly-once semantics.
    """
    execution_id: str
    machine: str
    input: Dict[str, Any]
    launched: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LaunchIntent":
        return cls(**data)


@runtime_checkable
class ResultBackend(Protocol):
    """
    Protocol for result backends.

    Result backends store and retrieve machine execution results,
    enabling inter-machine communication.
    """

    async def write(self, uri: str, data: Any) -> None:
        """Write data to a URI.

        Args:
            uri: FlatAgents URI (flatagents://{execution_id}/{path})
            data: Data to store (will be serialized)
        """
        ...

    async def read(self, uri: str, block: bool = True, timeout: Optional[float] = None) -> Any:
        """Read data from a URI.

        Args:
            uri: FlatAgents URI
            block: If True, wait for data to be available
            timeout: Maximum seconds to wait (None = forever, only used if block=True)

        Returns:
            The stored data, or None if not found and block=False

        Raises:
            TimeoutError: If timeout expires while waiting
        """
        ...

    async def exists(self, uri: str) -> bool:
        """Check if data exists at a URI.

        Args:
            uri: FlatAgents URI

        Returns:
            True if data exists, False otherwise
        """
        ...

    async def delete(self, uri: str) -> None:
        """Delete data at a URI.

        Args:
            uri: FlatAgents URI
        """
        ...


class InMemoryResultBackend:
    """
    In-memory result backend for local execution.

    Stores results in memory with asyncio Event-based blocking reads.
    Suitable for single-process execution where machines run in the same process.
    """

    def __init__(self):
        self._store: Dict[str, Any] = {}
        self._events: Dict[str, asyncio.Event] = {}
        self._lock = asyncio.Lock()

    def _get_key(self, uri: str) -> str:
        """Convert URI to storage key."""
        execution_id, path = parse_uri(uri)
        return f"{execution_id}/{path}"

    def _get_event(self, key: str) -> asyncio.Event:
        """Get or create an event for a key."""
        if key not in self._events:
            self._events[key] = asyncio.Event()
        return self._events[key]

    async def write(self, uri: str, data: Any) -> None:
        """Write data to a URI."""
        key = self._get_key(uri)
        async with self._lock:
            self._store[key] = data
            event = self._get_event(key)
            event.set()
        logger.debug(f"ResultBackend: wrote to {uri}")

    async def read(self, uri: str, block: bool = True, timeout: Optional[float] = None) -> Any:
        """Read data from a URI."""
        key = self._get_key(uri)

        if not block:
            return self._store.get(key)

        event = self._get_event(key)

        # Check if already available
        if key in self._store:
            return self._store[key]

        # Wait for data
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            raise TimeoutError(f"Timeout waiting for result at {uri}")

        return self._store.get(key)

    async def exists(self, uri: str) -> bool:
        """Check if data exists at a URI."""
        key = self._get_key(uri)
        return key in self._store

    async def delete(self, uri: str) -> None:
        """Delete data at a URI."""
        key = self._get_key(uri)
        async with self._lock:
            self._store.pop(key, None)
            if key in self._events:
                del self._events[key]


# Singleton for shared in-memory backend
_default_backend: Optional[InMemoryResultBackend] = None


def get_default_result_backend() -> InMemoryResultBackend:
    """Get the default shared in-memory result backend."""
    global _default_backend
    if _default_backend is None:
        _default_backend = InMemoryResultBackend()
    return _default_backend


def reset_default_result_backend() -> None:
    """Reset the default result backend (for testing)."""
    global _default_backend
    _default_backend = None


__all__ = [
    "ResultBackend",
    "InMemoryResultBackend",
    "LaunchIntent",
    "make_uri",
    "parse_uri",
    "get_default_result_backend",
    "reset_default_result_backend",
]

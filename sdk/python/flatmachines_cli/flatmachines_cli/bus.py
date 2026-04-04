"""
DataBus — UDP-like latest-value data serving layer.

Design principles (think UDP datagrams):
- Writers overwrite unconditionally. Latest value wins.
- Readers get the latest value. Missed updates are gone.
- No backpressure from readers to writers.
- No queue buildup. O(1) memory per slot.
- Version counter lets readers detect changes cheaply.

Writers (backend processors) write at their own pace.
Readers (frontend) read when they can, always get latest.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Generic, Optional, Tuple, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass
class SlotValue(Generic[T]):
    """Immutable snapshot of a slot's state at read time."""
    data: T
    version: int
    timestamp: float


class Slot(Generic[T]):
    """
    Single-slot buffer with UDP semantics.

    - write() overwrites unconditionally (latest wins)
    - read() returns latest value + monotonic version
    - try_read() returns None if no value written yet
    - wait() blocks until a new version is available (for event-driven frontends)
    - No backpressure. No blocking on write. No queue buildup.

    Thread-safety: designed for single-thread asyncio. All access is
    within the same event loop. If you need cross-thread, wrap with a lock.
    """

    __slots__ = ("_data", "_version", "_timestamp", "_event", "_name")

    def __init__(self, name: str = ""):
        self._data: Optional[T] = None
        self._version: int = 0
        self._timestamp: float = 0.0
        self._event: asyncio.Event = asyncio.Event()
        self._name: str = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def version(self) -> int:
        return self._version

    @property
    def has_value(self) -> bool:
        return self._version > 0

    def write(self, value: T) -> int:
        """
        Overwrite slot with new value. Returns new version.

        Non-blocking. Never raises. Fire-and-forget like a UDP send.
        """
        self._data = value
        self._version += 1
        self._timestamp = time.monotonic()
        # Wake all current waiters. The event stays set until explicitly
        # cleared by wait(), allowing multiple concurrent waiters to wake.
        self._event.set()
        return self._version

    def read(self) -> Optional[SlotValue[T]]:
        """
        Read latest value. Returns None if no value has been written.

        Non-blocking. Never raises. Like a UDP recv that returns latest datagram.
        """
        if self._version == 0:
            return None
        return SlotValue(
            data=self._data,
            version=self._version,
            timestamp=self._timestamp,
        )

    def read_data(self) -> Optional[T]:
        """Convenience: read just the data, or None if empty."""
        if self._version == 0:
            return None
        return self._data

    def read_if_changed(self, since_version: int) -> Optional[SlotValue[T]]:
        """
        Read only if version has changed since `since_version`.
        Returns None if no new data. Useful for poll-based frontends.
        """
        if self._version <= since_version:
            return None
        return SlotValue(
            data=self._data,
            version=self._version,
            timestamp=self._timestamp,
        )

    async def wait(self, timeout: Optional[float] = None) -> SlotValue[T]:
        """
        Wait for next write. For event-driven consumers.
        Raises TimeoutError if timeout expires with no value ever written.
        Returns current value on timeout if a value exists.
        """
        try:
            await asyncio.wait_for(self._event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            # Return current value on timeout (may be None if never written)
            if self._version == 0:
                raise
        # Clear event so the next wait() call blocks until the next write
        self._event.clear()
        return SlotValue(
            data=self._data,
            version=self._version,
            timestamp=self._timestamp,
        )

    def __repr__(self) -> str:
        return f"Slot(name={self._name!r}, version={self._version}, has_value={self.has_value})"


class DataBus:
    """
    Named collection of Slots. The shared data surface between backend and frontend.

    Backend processors write to slots by name.
    Frontend reads all slots (snapshot) or individual slots.

    Slot creation is lazy — first write or explicit get_slot() creates it.
    This keeps the bus zero-config: processors just write, frontend just reads.
    """

    def __init__(self):
        self._slots: Dict[str, Slot] = {}

    def slot(self, name: str) -> Slot:
        """Get or create a named slot.

        Args:
            name: Slot name. Must be a non-empty string.

        Raises:
            TypeError: If name is not a string.
            ValueError: If name is empty.
        """
        if not isinstance(name, str):
            raise TypeError(f"Slot name must be a string, got {type(name).__name__}")
        if not name:
            raise ValueError("Slot name must not be empty")
        if name not in self._slots:
            self._slots[name] = Slot(name=name)
        return self._slots[name]

    def write(self, name: str, value: Any) -> int:
        """Write to a named slot. Creates slot if needed. Returns version.

        Args:
            name: Slot name. Must be a non-empty string.
            value: Value to write (any type).

        Raises:
            TypeError: If name is not a string.
            ValueError: If name is empty.
        """
        return self.slot(name).write(value)

    def read(self, name: str) -> Optional[SlotValue]:
        """Read from a named slot. Returns None if slot doesn't exist or is empty."""
        s = self._slots.get(name)
        if s is None:
            return None
        return s.read()

    def read_data(self, name: str) -> Any:
        """Read just the data from a named slot. Returns None if empty."""
        s = self._slots.get(name)
        if s is None:
            return None
        return s.read_data()

    def snapshot(self) -> Dict[str, Any]:
        """
        Read all slots into a flat dict: {name: data}.
        Slots that haven't been written yet are omitted.

        This is the primary read interface for frontends.
        Call it at your render rate, always get latest.
        """
        result = {}
        for name, s in self._slots.items():
            if s.has_value:
                result[name] = s.read_data()
        return result

    def snapshot_versioned(self) -> Dict[str, SlotValue]:
        """Like snapshot() but returns SlotValue with version/timestamp metadata."""
        result = {}
        for name, s in self._slots.items():
            val = s.read()
            if val is not None:
                result[name] = val
        return result

    def versions(self) -> Dict[str, int]:
        """Return {name: version} for all slots. Cheap change-detection for frontends."""
        return {name: s.version for name, s in self._slots.items()}

    def slot_names(self) -> list:
        """List all registered slot names."""
        return list(self._slots.keys())

    def reset(self):
        """Clear all slots. Used for new machine execution."""
        self._slots.clear()

    def __repr__(self) -> str:
        slot_info = ", ".join(
            f"{n}(v{s.version})" for n, s in self._slots.items() if s.has_value
        )
        return f"DataBus([{slot_info}])"

    def __len__(self) -> int:
        """Number of slots (including empty ones)."""
        return len(self._slots)

    def __bool__(self) -> bool:
        """DataBus is always truthy, even when empty."""
        return True

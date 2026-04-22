"""Async call throttle — serialized gate with jitter.

Enforces a minimum delay between calls.  An asyncio.Lock serialises the
"when to launch" decision so concurrent callers are staggered, but the
actual work (subprocess, network call, …) runs concurrently once past
the gate.

    throttle = CallThrottle(delay=3.0, jitter=4.0)

    # 3 concurrent tasks:
    #   t≈0s   task-1 passes gate immediately (first call)
    #   t≈0s   task-2 acquires lock, sleeps ~7s, passes gate
    #   t≈7s   task-3 acquires lock, sleeps ~5s, passes gate
    #   all 3 subprocesses now running concurrently

Delay formula per call::

    wait = max(0, (last_call + delay + uniform(0, 2*jitter)) - now)

With ``delay=3, jitter=4`` the gap between consecutive calls is
uniformly distributed over **[3, 11] seconds**, with millisecond
granularity from float arithmetic.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time

logger = logging.getLogger(__name__)


class CallThrottle:
    """Async rate limiter: base delay + uniform jitter between calls.

    Args:
        delay: Minimum base seconds between calls.
        jitter: Half-width of the jitter window.  Actual jitter added is
            ``uniform(0, 2 * jitter)`` so the total gap is in
            ``[delay, delay + 2*jitter]``.  Set to 0 for fixed delay.
    """

    def __init__(self, delay: float = 0.0, jitter: float = 0.0) -> None:
        self._delay = max(0.0, delay)
        self._jitter = max(0.0, jitter)
        self._lock = asyncio.Lock()
        self._last_call: float = 0.0   # monotonic timestamp

    @property
    def enabled(self) -> bool:
        return self._delay > 0 or self._jitter > 0

    async def wait(self) -> float:
        """Block until the next call is allowed.

        Returns the number of seconds actually waited (0.0 on first call
        or when the throttle is disabled).
        """
        if not self.enabled:
            return 0.0

        async with self._lock:
            now = time.monotonic()

            if self._last_call == 0.0:
                # First call — no wait
                self._last_call = now
                return 0.0

            # Compute jitter with ms granularity
            jitter_ms = random.randint(0, int(2 * self._jitter * 1000))
            jitter_s = jitter_ms / 1000.0

            target = self._last_call + self._delay + jitter_s
            wait_s = max(0.0, target - now)

            if wait_s > 0:
                logger.debug(
                    "CallThrottle: sleeping %.3fs (delay=%.1f jitter=%.3f)",
                    wait_s, self._delay, jitter_s,
                )
                await asyncio.sleep(wait_s)

            self._last_call = time.monotonic()
            return wait_s

    def reset(self) -> None:
        """Reset the throttle so the next call passes immediately."""
        self._last_call = 0.0


# ---------------------------------------------------------------------------
# Factory from config dict
# ---------------------------------------------------------------------------

def throttle_from_config(config: dict) -> CallThrottle:
    """Create a CallThrottle from an adapter config dict.

    Recognised keys::

        rate_limit_delay:  3.0   # base seconds (default 0 = disabled)
        rate_limit_jitter: 4.0   # ±seconds (default 0)

    Returns a disabled throttle when neither key is set.
    """
    delay = float(config.get("rate_limit_delay", 0))
    jitter = float(config.get("rate_limit_jitter", 0))
    return CallThrottle(delay=delay, jitter=jitter)

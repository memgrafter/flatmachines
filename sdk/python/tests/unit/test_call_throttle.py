"""Unit tests for CallThrottle."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import patch

import pytest

from flatmachines.adapters.call_throttle import CallThrottle, throttle_from_config


# ---------------------------------------------------------------------------
# Basic behaviour
# ---------------------------------------------------------------------------

class TestCallThrottle:
    def test_disabled_by_default(self):
        t = CallThrottle()
        assert not t.enabled

    def test_enabled_with_delay(self):
        t = CallThrottle(delay=1.0)
        assert t.enabled

    def test_enabled_with_jitter_only(self):
        t = CallThrottle(jitter=1.0)
        assert t.enabled

    @pytest.mark.asyncio
    async def test_first_call_no_wait(self):
        t = CallThrottle(delay=100.0)  # huge delay — should still pass first
        waited = await t.wait()
        assert waited == 0.0

    @pytest.mark.asyncio
    async def test_disabled_always_zero(self):
        t = CallThrottle()
        w1 = await t.wait()
        w2 = await t.wait()
        w3 = await t.wait()
        assert w1 == 0.0
        assert w2 == 0.0
        assert w3 == 0.0

    @pytest.mark.asyncio
    async def test_second_call_waits(self):
        t = CallThrottle(delay=0.05, jitter=0.0)  # 50ms fixed
        await t.wait()  # first — instant
        start = time.monotonic()
        waited = await t.wait()  # second — should wait ~50ms
        elapsed = time.monotonic() - start
        assert waited > 0.0
        assert elapsed >= 0.04  # allow small scheduling slack

    @pytest.mark.asyncio
    async def test_jitter_adds_randomness(self):
        """Multiple calls should produce varying wait times."""
        t = CallThrottle(delay=0.01, jitter=0.01)
        waits = []
        await t.wait()  # first — instant
        for _ in range(10):
            t._last_call = time.monotonic()  # reset to force wait
            w = await t.wait()
            waits.append(w)
        # With jitter, not all waits should be identical
        unique = set(round(w, 4) for w in waits)
        assert len(unique) > 1, f"Expected variation, got {waits}"

    @pytest.mark.asyncio
    async def test_jitter_range(self):
        """Jitter should produce values in [0, 2*jitter] ms range."""
        jitter = 0.005  # 5ms
        t = CallThrottle(delay=0.0, jitter=jitter)
        await t.wait()  # first
        waits = []
        for _ in range(50):
            t._last_call = time.monotonic()
            w = await t.wait()
            waits.append(w)
        # All waits should be in [0, 2*jitter] ≈ [0, 0.010]
        for w in waits:
            assert w <= 0.015, f"Wait {w} exceeds max expected ~0.010"

    @pytest.mark.asyncio
    async def test_reset(self):
        t = CallThrottle(delay=100.0)
        await t.wait()  # first
        t.reset()
        start = time.monotonic()
        await t.wait()  # after reset — should be instant
        elapsed = time.monotonic() - start
        assert elapsed < 0.05

    @pytest.mark.asyncio
    async def test_negative_values_clamped(self):
        t = CallThrottle(delay=-5.0, jitter=-3.0)
        assert not t.enabled  # both clamped to 0


# ---------------------------------------------------------------------------
# Serialised gate behaviour
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestSerialisedGate:
    async def test_concurrent_calls_stagger(self):
        """Three concurrent wait() calls should be serialised."""
        t = CallThrottle(delay=0.05, jitter=0.0)  # 50ms fixed

        timestamps = []

        async def _call(idx):
            await t.wait()
            timestamps.append((idx, time.monotonic()))

        await asyncio.gather(_call(0), _call(1), _call(2))

        assert len(timestamps) == 3
        # Sort by time
        timestamps.sort(key=lambda x: x[1])
        # Gap between consecutive calls should be ~50ms (except first)
        gap_01 = timestamps[1][1] - timestamps[0][1]
        gap_12 = timestamps[2][1] - timestamps[1][1]
        assert gap_01 >= 0.03, f"Gap 0→1 too small: {gap_01:.4f}s"
        assert gap_12 >= 0.03, f"Gap 1→2 too small: {gap_12:.4f}s"


# ---------------------------------------------------------------------------
# throttle_from_config
# ---------------------------------------------------------------------------

class TestThrottleFromConfig:
    def test_empty_config(self):
        t = throttle_from_config({})
        assert not t.enabled

    def test_delay_only(self):
        t = throttle_from_config({"rate_limit_delay": 3.0})
        assert t.enabled
        assert t._delay == 3.0
        assert t._jitter == 0.0

    def test_both(self):
        t = throttle_from_config({"rate_limit_delay": 3.0, "rate_limit_jitter": 4.0})
        assert t.enabled
        assert t._delay == 3.0
        assert t._jitter == 4.0

    def test_string_values(self):
        t = throttle_from_config({"rate_limit_delay": "2.5", "rate_limit_jitter": "1.5"})
        assert t._delay == 2.5
        assert t._jitter == 1.5

    def test_zero_disabled(self):
        t = throttle_from_config({"rate_limit_delay": 0, "rate_limit_jitter": 0})
        assert not t.enabled

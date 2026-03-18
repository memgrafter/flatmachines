"""Unit tests for the Claude Code session holdback pattern."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from flatmachines.adapters.claude_code import ClaudeCodeExecutor
from flatmachines.adapters.claude_code_sessions import (
    ForkResult,
    SessionHoldback,
)
from flatmachines.agents import AgentResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_executor(config: Optional[Dict[str, Any]] = None) -> ClaudeCodeExecutor:
    return ClaudeCodeExecutor(
        config=config or {"permission_mode": "bypassPermissions"},
        config_dir="/tmp/test",
        settings={},
    )


def _make_result(
    session_id: str = "test-session",
    content: str = "ok",
    cache_read: int = 9000,
    cache_write: int = 20,
    cost: float = 0.01,
    error: Optional[Dict] = None,
    num_turns: int = 1,
) -> AgentResult:
    return AgentResult(
        output={"result": content, "session_id": session_id},
        content=content,
        usage={
            "input_tokens": 10,
            "output_tokens": 5,
            "cache_read_tokens": cache_read,
            "cache_write_tokens": cache_write,
        },
        cost=cost,
        finish_reason="stop",
        error=error,
        metadata={
            "session_id": session_id,
            "num_turns": num_turns,
            "stream_events": [],
        },
    )


# ---------------------------------------------------------------------------
# Seed tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestSeed:
    async def test_seed_creates_session(self):
        executor = _make_executor()
        holdback = SessionHoldback(executor=executor)

        seed_result = _make_result(session_id="seed-id", cache_read=0, cache_write=3000)
        warm_result = _make_result(session_id="warm-fork-id", cache_read=9000, cache_write=20)

        call_count = 0

        async def _fake_invoke(task, session_id, resume, context=None, fork_session=False):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Seed call
                assert not resume
                assert not fork_session
                return seed_result
            else:
                # Auto-warm call
                assert resume
                assert fork_session
                return warm_result

        executor._invoke_once = _fake_invoke

        result = await holdback.seed("set up context")

        assert holdback._seeded
        assert holdback.session_id is not None
        assert call_count == 2  # seed + auto-warm
        assert result.content == "ok"

    async def test_seed_auto_warm_false(self):
        executor = _make_executor()
        holdback = SessionHoldback(executor=executor)

        call_count = 0

        async def _fake_invoke(task, session_id, resume, context=None, fork_session=False):
            nonlocal call_count
            call_count += 1
            return _make_result(cache_read=0, cache_write=3000)

        executor._invoke_once = _fake_invoke

        await holdback.seed("context", auto_warm=False)
        assert call_count == 1  # No warm

    async def test_seed_error_skips_warm(self):
        executor = _make_executor()
        holdback = SessionHoldback(executor=executor)

        call_count = 0

        async def _fake_invoke(task, session_id, resume, context=None, fork_session=False):
            nonlocal call_count
            call_count += 1
            return _make_result(error={"code": "server_error", "message": "fail"})

        executor._invoke_once = _fake_invoke

        result = await holdback.seed("context")
        assert call_count == 1  # Error — no warm
        assert result.error is not None

    async def test_seed_with_provided_session_id(self):
        executor = _make_executor()
        holdback = SessionHoldback(executor=executor, session_id="my-custom-id")

        async def _fake_invoke(task, session_id, resume, context=None, fork_session=False):
            if not resume:
                assert session_id == "my-custom-id"
            return _make_result()

        executor._invoke_once = _fake_invoke

        await holdback.seed("context")
        assert holdback.session_id == "my-custom-id"


# ---------------------------------------------------------------------------
# Adopt tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestAdopt:
    async def test_adopt_sets_session(self):
        executor = _make_executor()
        holdback = SessionHoldback(executor=executor)

        async def _fake_invoke(task, session_id, resume, context=None, fork_session=False):
            assert resume
            assert fork_session
            assert session_id == "existing-session"
            return _make_result(cache_read=9000)

        executor._invoke_once = _fake_invoke

        result = await holdback.adopt("existing-session")

        assert holdback._seeded
        assert holdback.session_id == "existing-session"
        assert result is not None  # auto-warm result

    async def test_adopt_no_warm(self):
        executor = _make_executor()
        holdback = SessionHoldback(executor=executor)

        call_count = 0

        async def _fake_invoke(task, session_id, resume, context=None, fork_session=False):
            nonlocal call_count
            call_count += 1
            return _make_result()

        executor._invoke_once = _fake_invoke

        result = await holdback.adopt("existing-session", auto_warm=False)
        assert call_count == 0
        assert result is None
        assert holdback._seeded


# ---------------------------------------------------------------------------
# Fork tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestFork:
    async def test_fork_uses_fork_session(self):
        executor = _make_executor()
        holdback = SessionHoldback(executor=executor, session_id="parent-id")
        holdback._seeded = True

        async def _fake_invoke(task, session_id, resume, context=None, fork_session=False):
            assert resume
            assert fork_session
            assert session_id == "parent-id"
            assert task == "do work"
            return _make_result(session_id="child-id", cache_read=9500)

        executor._invoke_once = _fake_invoke

        fr = await holdback.fork("do work")
        assert fr.session_id == "child-id"
        assert fr.cache_read_tokens == 9500
        assert fr.task == "do work"
        assert holdback._fork_count == 1

    async def test_fork_not_seeded_raises(self):
        executor = _make_executor()
        holdback = SessionHoldback(executor=executor)

        with pytest.raises(RuntimeError, match="not seeded"):
            await holdback.fork("do work")

    async def test_fork_accumulates_cost(self):
        executor = _make_executor()
        holdback = SessionHoldback(executor=executor, session_id="p")
        holdback._seeded = True

        async def _fake_invoke(task, session_id, resume, context=None, fork_session=False):
            return _make_result(cost=0.05)

        executor._invoke_once = _fake_invoke

        await holdback.fork("task 1")
        await holdback.fork("task 2")
        assert abs(holdback._total_cost - 0.10) < 0.001
        assert holdback._fork_count == 2


# ---------------------------------------------------------------------------
# fork_n tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestForkN:
    async def test_fork_n_parallel(self):
        executor = _make_executor()
        holdback = SessionHoldback(executor=executor, session_id="p")
        holdback._seeded = True

        call_count = 0

        async def _fake_invoke(task, session_id, resume, context=None, fork_session=False):
            nonlocal call_count
            call_count += 1
            return _make_result(session_id=f"child-{call_count}", cache_read=9500)

        executor._invoke_once = _fake_invoke

        results = await holdback.fork_n(["task a", "task b", "task c"])
        assert len(results) == 3
        assert call_count == 3
        assert all(isinstance(r, ForkResult) for r in results)
        assert all(r.cache_read_tokens == 9500 for r in results)

    async def test_fork_n_with_concurrency_limit(self):
        executor = _make_executor()
        holdback = SessionHoldback(executor=executor, session_id="p")
        holdback._seeded = True

        max_concurrent_seen = 0
        current_concurrent = 0

        async def _fake_invoke(task, session_id, resume, context=None, fork_session=False):
            nonlocal max_concurrent_seen, current_concurrent
            current_concurrent += 1
            max_concurrent_seen = max(max_concurrent_seen, current_concurrent)
            await asyncio.sleep(0.01)
            current_concurrent -= 1
            return _make_result()

        executor._invoke_once = _fake_invoke

        results = await holdback.fork_n(
            ["a", "b", "c", "d", "e"],
            max_concurrent=2,
        )
        assert len(results) == 5
        assert max_concurrent_seen <= 2

    async def test_fork_n_handles_exceptions(self):
        executor = _make_executor()
        holdback = SessionHoldback(executor=executor, session_id="p")
        holdback._seeded = True

        call_count = 0

        async def _fake_invoke(task, session_id, resume, context=None, fork_session=False):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RuntimeError("API down")
            return _make_result()

        executor._invoke_once = _fake_invoke

        results = await holdback.fork_n(["ok", "fail", "ok"])
        assert len(results) == 3
        assert results[0].result.error is None
        assert results[1].result.error is not None
        assert "API down" in results[1].result.error["message"]
        assert results[2].result.error is None

    async def test_fork_n_not_seeded_raises(self):
        executor = _make_executor()
        holdback = SessionHoldback(executor=executor)

        with pytest.raises(RuntimeError, match="not seeded"):
            await holdback.fork_n(["task"])


# ---------------------------------------------------------------------------
# Warm tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestWarm:
    async def test_warm_uses_fork_session(self):
        executor = _make_executor()
        holdback = SessionHoldback(executor=executor, session_id="p")
        holdback._seeded = True

        async def _fake_invoke(task, session_id, resume, context=None, fork_session=False):
            assert task == "test"
            assert resume
            assert fork_session
            assert session_id == "p"
            return _make_result(cache_read=9500)

        executor._invoke_once = _fake_invoke

        result = await holdback.warm()
        assert result.usage["cache_read_tokens"] == 9500

    async def test_warm_not_seeded_raises(self):
        executor = _make_executor()
        holdback = SessionHoldback(executor=executor)

        with pytest.raises(RuntimeError, match="not seeded"):
            await holdback.warm()


# ---------------------------------------------------------------------------
# Stats tests
# ---------------------------------------------------------------------------

class TestStats:
    def test_initial_stats(self):
        executor = _make_executor()
        holdback = SessionHoldback(executor=executor)
        stats = holdback.stats
        assert stats["session_id"] is None
        assert stats["seeded"] is False
        assert stats["fork_count"] == 0
        assert stats["total_cost"] == 0.0


# ---------------------------------------------------------------------------
# build_args fork_session integration
# ---------------------------------------------------------------------------

class TestBuildArgsForkSession:
    def test_fork_session_flag(self):
        executor = _make_executor()
        args = executor._build_args("task", "sid", resume=True, fork_session=True)
        assert "--resume" in args
        assert "sid" in args
        assert "--fork-session" in args

    def test_no_fork_session_by_default(self):
        executor = _make_executor()
        args = executor._build_args("task", "sid", resume=True)
        assert "--fork-session" not in args

    def test_fork_session_ignored_without_resume(self):
        executor = _make_executor()
        args = executor._build_args("task", "sid", resume=False, fork_session=True)
        assert "--fork-session" not in args
        assert "--session-id" in args

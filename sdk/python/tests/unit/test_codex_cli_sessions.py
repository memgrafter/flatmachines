"""Unit tests for the Codex CLI session holdback pattern."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from flatmachines.adapters.codex_cli import CodexCliExecutor, CodexAppServerTransport
from flatmachines.adapters.codex_cli_sessions import (
    CodexSessionHoldback,
    ForkResult,
)
from flatmachines.agents import AgentResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_executor(config: Optional[Dict[str, Any]] = None) -> CodexCliExecutor:
    return CodexCliExecutor(
        config=config or {"use_app_server": True},
        config_dir="/tmp/test",
        settings={},
    )


def _make_result(
    content: str = "ok",
    input_tokens: int = 100,
    cached_input_tokens: int = 80,
    output_tokens: int = 10,
    error: Optional[Dict] = None,
) -> AgentResult:
    return AgentResult(
        output={"result": content, "thread_id": "tid"},
        content=content,
        usage={
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cached_input_tokens": cached_input_tokens,
        },
        finish_reason="stop" if not error else "error",
        error=error,
        metadata={"thread_id": "tid", "items": []},
    )


def _mock_transport() -> MagicMock:
    """Create a mock transport with async methods."""
    transport = MagicMock(spec=CodexAppServerTransport)
    transport.thread_start = AsyncMock(return_value={
        "thread": {"id": "parent-thread-id"},
        "model": "gpt-5.3-codex",
    })
    transport.thread_fork = AsyncMock(return_value={
        "thread": {"id": "child-thread-id", "turns": []},
        "model": "gpt-5.3-codex",
    })
    transport.thread_resume = AsyncMock(return_value={
        "thread": {"id": "parent-thread-id"},
    })
    transport.turn_start = AsyncMock(return_value={
        "turn": {"id": "turn-1", "status": "inProgress"},
    })
    transport.on_notification = MagicMock()
    return transport


# ---------------------------------------------------------------------------
# Seed tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestSeed:

    async def test_seed_creates_thread(self):
        executor = _make_executor()
        transport = _mock_transport()
        executor._transport = transport

        # Mock _ensure_transport to return our mock
        async def _ensure():
            return transport
        executor._ensure_transport = _ensure

        # Mock _run_turn_and_collect
        async def _run_turn(t, tid, text, timeout=0):
            return _make_result(cached_input_tokens=0)
        executor._run_turn_and_collect = _run_turn

        holdback = CodexSessionHoldback(executor=executor)
        result = await holdback.seed("set up context")

        assert holdback._seeded
        assert holdback.thread_id == "parent-thread-id"
        assert result.content == "ok"
        transport.thread_start.assert_called_once()

    async def test_seed_single_call(self):
        executor = _make_executor()
        transport = _mock_transport()
        executor._transport = transport

        call_count = 0

        async def _ensure():
            return transport
        executor._ensure_transport = _ensure

        async def _run_turn(t, tid, text, timeout=0):
            nonlocal call_count
            call_count += 1
            return _make_result()
        executor._run_turn_and_collect = _run_turn

        holdback = CodexSessionHoldback(executor=executor)
        await holdback.seed("context")
        assert call_count == 1

    async def test_seed_error_still_marks_seeded(self):
        executor = _make_executor()
        transport = _mock_transport()
        executor._transport = transport

        async def _ensure():
            return transport
        executor._ensure_transport = _ensure

        async def _run_turn(t, tid, text, timeout=0):
            return _make_result(error={"code": "server_error", "message": "fail"})
        executor._run_turn_and_collect = _run_turn

        holdback = CodexSessionHoldback(executor=executor)
        result = await holdback.seed("context")
        assert result.error is not None
        assert holdback._seeded

    async def test_seed_with_provided_thread_id(self):
        """When thread_id is pre-set, seed still starts a new thread (ignores it)."""
        executor = _make_executor()
        transport = _mock_transport()
        executor._transport = transport

        async def _ensure():
            return transport
        executor._ensure_transport = _ensure

        async def _run_turn(t, tid, text, timeout=0):
            return _make_result()
        executor._run_turn_and_collect = _run_turn

        holdback = CodexSessionHoldback(executor=executor, thread_id="will-be-replaced")
        await holdback.seed("context")
        # thread_id is replaced by the one from thread_start
        assert holdback.thread_id == "parent-thread-id"


# ---------------------------------------------------------------------------
# Adopt tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestAdopt:

    async def test_adopt_sets_thread(self):
        executor = _make_executor()
        holdback = CodexSessionHoldback(executor=executor)

        await holdback.adopt("existing-thread-id")

        assert holdback._seeded
        assert holdback.thread_id == "existing-thread-id"

    async def test_adopt_no_api_call(self):
        executor = _make_executor()
        transport = _mock_transport()
        executor._transport = transport

        holdback = CodexSessionHoldback(executor=executor)
        await holdback.adopt("existing-thread-id")

        transport.thread_start.assert_not_called()
        transport.thread_fork.assert_not_called()
        transport.turn_start.assert_not_called()


# ---------------------------------------------------------------------------
# Fork tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestFork:

    async def test_fork_uses_thread_fork(self):
        executor = _make_executor()
        transport = _mock_transport()
        executor._transport = transport

        fork_id_counter = [0]

        async def _ensure():
            return transport
        executor._ensure_transport = _ensure

        async def _mock_fork(tid, model=None, **kw):
            fork_id_counter[0] += 1
            return {"thread": {"id": f"child-{fork_id_counter[0]}", "turns": []}}
        transport.thread_fork = _mock_fork

        async def _run_turn(t, tid, text, timeout=0):
            return _make_result(cached_input_tokens=9500)
        executor._run_turn_and_collect = _run_turn

        holdback = CodexSessionHoldback(executor=executor, thread_id="parent")
        holdback._seeded = True

        fr = await holdback.fork("do work")
        assert fr.thread_id == "child-1"
        assert fr.cached_input_tokens == 9500
        assert fr.task == "do work"
        assert holdback._fork_count == 1

    async def test_fork_pins_model(self):
        executor = _make_executor()
        transport = _mock_transport()
        executor._transport = transport

        captured_model = [None]

        async def _ensure():
            return transport
        executor._ensure_transport = _ensure

        async def _mock_fork(tid, model=None, **kw):
            captured_model[0] = model
            return {"thread": {"id": "child", "turns": []}}
        transport.thread_fork = _mock_fork

        async def _run_turn(t, tid, text, timeout=0):
            return _make_result()
        executor._run_turn_and_collect = _run_turn

        holdback = CodexSessionHoldback(
            executor=executor, model="gpt-5.3-codex", thread_id="parent",
        )
        holdback._seeded = True

        await holdback.fork("task")
        assert captured_model[0] == "gpt-5.3-codex"

    async def test_fork_not_seeded_raises(self):
        executor = _make_executor()
        holdback = CodexSessionHoldback(executor=executor)

        with pytest.raises(RuntimeError, match="not seeded"):
            await holdback.fork("do work")

    async def test_fork_accumulates_usage(self):
        executor = _make_executor()
        transport = _mock_transport()
        executor._transport = transport

        fork_counter = [0]

        async def _ensure():
            return transport
        executor._ensure_transport = _ensure

        async def _mock_fork(tid, model=None, **kw):
            fork_counter[0] += 1
            return {"thread": {"id": f"c-{fork_counter[0]}", "turns": []}}
        transport.thread_fork = _mock_fork

        async def _run_turn(t, tid, text, timeout=0):
            return _make_result(input_tokens=100, cached_input_tokens=80)
        executor._run_turn_and_collect = _run_turn

        holdback = CodexSessionHoldback(executor=executor, thread_id="p")
        holdback._seeded = True

        await holdback.fork("task 1")
        await holdback.fork("task 2")
        assert holdback._total_input_tokens == 200
        assert holdback._total_cached_tokens == 160
        assert holdback._fork_count == 2


# ---------------------------------------------------------------------------
# fork_n tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestForkN:

    async def test_fork_n_parallel(self):
        executor = _make_executor()
        transport = _mock_transport()
        executor._transport = transport

        fork_counter = [0]

        async def _ensure():
            return transport
        executor._ensure_transport = _ensure

        async def _mock_fork(tid, model=None, **kw):
            fork_counter[0] += 1
            return {"thread": {"id": f"child-{fork_counter[0]}", "turns": []}}
        transport.thread_fork = _mock_fork

        async def _run_turn(t, tid, text, timeout=0):
            return _make_result(cached_input_tokens=9500)
        executor._run_turn_and_collect = _run_turn

        holdback = CodexSessionHoldback(executor=executor, thread_id="p")
        holdback._seeded = True

        results = await holdback.fork_n(["a", "b", "c"])
        assert len(results) == 3
        assert all(isinstance(r, ForkResult) for r in results)
        assert all(r.cached_input_tokens == 9500 for r in results)

    async def test_fork_n_with_concurrency_limit(self):
        executor = _make_executor()
        transport = _mock_transport()
        executor._transport = transport

        max_concurrent_seen = 0
        current_concurrent = 0
        fork_counter = [0]

        async def _ensure():
            return transport
        executor._ensure_transport = _ensure

        async def _mock_fork(tid, model=None, **kw):
            fork_counter[0] += 1
            return {"thread": {"id": f"c-{fork_counter[0]}", "turns": []}}
        transport.thread_fork = _mock_fork

        async def _run_turn(t, tid, text, timeout=0):
            nonlocal max_concurrent_seen, current_concurrent
            current_concurrent += 1
            max_concurrent_seen = max(max_concurrent_seen, current_concurrent)
            await asyncio.sleep(0.01)
            current_concurrent -= 1
            return _make_result()
        executor._run_turn_and_collect = _run_turn

        holdback = CodexSessionHoldback(executor=executor, thread_id="p")
        holdback._seeded = True

        results = await holdback.fork_n(
            ["a", "b", "c", "d", "e"],
            max_concurrent=2,
        )
        assert len(results) == 5
        assert max_concurrent_seen <= 2

    async def test_fork_n_handles_exceptions(self):
        executor = _make_executor()
        transport = _mock_transport()
        executor._transport = transport

        fork_counter = [0]

        async def _ensure():
            return transport
        executor._ensure_transport = _ensure

        async def _mock_fork(tid, model=None, **kw):
            fork_counter[0] += 1
            if fork_counter[0] == 2:
                raise RuntimeError("API down")
            return {"thread": {"id": f"c-{fork_counter[0]}", "turns": []}}
        transport.thread_fork = _mock_fork

        async def _run_turn(t, tid, text, timeout=0):
            return _make_result()
        executor._run_turn_and_collect = _run_turn

        holdback = CodexSessionHoldback(executor=executor, thread_id="p")
        holdback._seeded = True

        results = await holdback.fork_n(["ok", "fail", "ok"])
        assert len(results) == 3
        assert results[0].result.error is None
        assert results[1].result.error is not None
        assert "API down" in results[1].result.error["message"]
        assert results[2].result.error is None

    async def test_fork_n_not_seeded_raises(self):
        executor = _make_executor()
        holdback = CodexSessionHoldback(executor=executor)

        with pytest.raises(RuntimeError, match="not seeded"):
            await holdback.fork_n(["task"])


# ---------------------------------------------------------------------------
# Warm tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestWarm:

    async def test_warm_uses_fork(self):
        executor = _make_executor()
        transport = _mock_transport()
        executor._transport = transport

        async def _ensure():
            return transport
        executor._ensure_transport = _ensure

        async def _run_turn(t, tid, text, timeout=0):
            assert text == "health check"
            return _make_result(cached_input_tokens=9500)
        executor._run_turn_and_collect = _run_turn

        holdback = CodexSessionHoldback(executor=executor, thread_id="p")
        holdback._seeded = True

        result = await holdback.warm()
        assert result.usage["cached_input_tokens"] == 9500

    async def test_warm_not_seeded_raises(self):
        executor = _make_executor()
        holdback = CodexSessionHoldback(executor=executor)

        with pytest.raises(RuntimeError, match="not seeded"):
            await holdback.warm()


# ---------------------------------------------------------------------------
# Stats tests
# ---------------------------------------------------------------------------

class TestStats:

    def test_initial_stats(self):
        executor = _make_executor()
        holdback = CodexSessionHoldback(executor=executor)
        stats = holdback.stats
        assert stats["thread_id"] is None
        assert stats["seeded"] is False
        assert stats["fork_count"] == 0
        assert stats["total_input_tokens"] == 0
        assert stats["total_cached_tokens"] == 0

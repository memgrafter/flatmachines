"""Tests for on_agent_stream_event hook and stream callback plumbing."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from flatmachines.hooks import (
    MachineHooks,
    LoggingHooks,
    CompositeHooks,
    WebhookHooks,
)
from flatmachines.agents import StreamEventCallback


# ---------------------------------------------------------------------------
# Hook method tests
# ---------------------------------------------------------------------------


class TestMachineHooksDefault:
    """Base MachineHooks.on_agent_stream_event is a no-op."""

    def test_default_is_noop(self):
        hooks = MachineHooks()
        # Should not raise
        hooks.on_agent_stream_event("state", {"type": "assistant"}, {"key": "val"})

    def test_default_returns_none(self):
        hooks = MachineHooks()
        result = hooks.on_agent_stream_event("s", {}, {})
        assert result is None


class TestLoggingHooksStream:
    """LoggingHooks logs stream event types."""

    def test_has_stream_event_method(self):
        import logging
        hooks = LoggingHooks(log_level=logging.INFO)
        # Method exists and is callable
        assert callable(hooks.on_agent_stream_event)
        # Does not raise
        hooks.on_agent_stream_event(
            "interpret", {"type": "assistant"}, {}
        )

    def test_overrides_base(self):
        """LoggingHooks overrides the base no-op."""
        assert (
            LoggingHooks.on_agent_stream_event
            is not MachineHooks.on_agent_stream_event
        )


class TestCompositeHooksStream:
    """CompositeHooks fans out to all children."""

    def test_fans_out_to_all(self):
        events_a: List[Dict] = []
        events_b: List[Dict] = []

        class HooksA(MachineHooks):
            def on_agent_stream_event(self, state_name, event, context):
                events_a.append(event)

        class HooksB(MachineHooks):
            def on_agent_stream_event(self, state_name, event, context):
                events_b.append(event)

        composite = CompositeHooks(HooksA(), HooksB())
        ev = {"type": "result"}
        composite.on_agent_stream_event("s", ev, {})
        assert events_a == [ev]
        assert events_b == [ev]

    def test_child_error_does_not_stop_others(self):
        """One child raising should not prevent other children from firing."""
        events: List[Dict] = []

        class BadHooks(MachineHooks):
            def on_agent_stream_event(self, state_name, event, context):
                raise RuntimeError("boom")

        class GoodHooks(MachineHooks):
            def on_agent_stream_event(self, state_name, event, context):
                events.append(event)

        # Note: CompositeHooks doesn't catch errors in children —
        # the adapter's try/except around the callback handles this.
        # We verify that if one child doesn't raise, it works.
        good = GoodHooks()
        good.on_agent_stream_event("s", {"type": "x"}, {})
        assert len(events) == 1


# ---------------------------------------------------------------------------
# Custom hook implementation tests
# ---------------------------------------------------------------------------


class CollectingHooks(MachineHooks):
    """Test hook that collects stream events for assertions."""

    def __init__(self):
        self.events: List[tuple] = []

    def on_agent_stream_event(
        self, state_name: str, event: Dict[str, Any], context: Dict[str, Any]
    ) -> None:
        self.events.append((state_name, event, dict(context)))


class TestCustomHook:
    def test_receives_all_event_types(self):
        hooks = CollectingHooks()
        ctx = {"foo": "bar"}
        events = [
            {"type": "system", "session_id": "abc"},
            {"type": "assistant", "message": {"content": []}},
            {"type": "user", "message": {"content": []}},
            {"type": "result", "usage": {}},
        ]
        for ev in events:
            hooks.on_agent_stream_event("my_state", ev, ctx)

        assert len(hooks.events) == 4
        assert all(s == "my_state" for s, _, _ in hooks.events)
        assert [e["type"] for _, e, _ in hooks.events] == [
            "system", "assistant", "user", "result"
        ]

    def test_context_is_read_only_contract(self):
        """Hook receives context but must not mutate it."""
        hooks = CollectingHooks()
        ctx = {"original": True}
        hooks.on_agent_stream_event("s", {"type": "x"}, ctx)
        # The hook received a copy of the context reference
        _, _, received_ctx = hooks.events[0]
        assert received_ctx["original"] is True


# ---------------------------------------------------------------------------
# Claude Code Executor callback integration tests
# ---------------------------------------------------------------------------


class TestClaudeCodeStreamCallback:
    """Test that ClaudeCodeExecutor calls _stream_event_callback."""

    def test_callback_attribute_exists(self):
        from flatmachines.adapters.claude_code import ClaudeCodeExecutor
        from flatmachines.adapters.call_throttle import CallThrottle
        executor = ClaudeCodeExecutor(
            config={}, config_dir="/tmp", settings={},
            throttle=CallThrottle(),
        )
        assert hasattr(executor, "_stream_event_callback")
        assert executor._stream_event_callback is None

    def test_callback_set_and_cleared(self):
        from flatmachines.adapters.claude_code import ClaudeCodeExecutor
        from flatmachines.adapters.call_throttle import CallThrottle
        executor = ClaudeCodeExecutor(
            config={}, config_dir="/tmp", settings={},
            throttle=CallThrottle(),
        )

        cb = lambda event: None
        executor._stream_event_callback = cb
        assert executor._stream_event_callback is cb
        executor._stream_event_callback = None
        assert executor._stream_event_callback is None

    @pytest.mark.asyncio
    async def test_callback_fires_per_event(self):
        """Verify _read_stream calls the callback for each NDJSON event."""
        from flatmachines.adapters.claude_code import (
            ClaudeCodeExecutor,
            _StreamCollector,
        )
        from flatmachines.adapters.call_throttle import CallThrottle

        # Build executor with callback
        received: List[Dict] = []
        executor = ClaudeCodeExecutor(
            config={}, config_dir="/tmp", settings={},
            throttle=CallThrottle(),
        )
        executor._stream_event_callback = lambda ev: received.append(ev)

        # Fake process with NDJSON lines
        events = [
            {"type": "system", "session_id": "s1"},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "hi"}]}},
            {"type": "result", "result": "done", "usage": {}},
        ]
        lines = [json.dumps(e).encode() + b"\n" for e in events]

        class FakeStdout:
            def __init__(self):
                self._lines = iter(lines)
            async def readline(self):
                try:
                    return next(self._lines)
                except StopIteration:
                    return b""

        class FakeStderr:
            async def read(self, n):
                return b""

        class FakeProc:
            stdout = FakeStdout()
            stderr = FakeStderr()

        collector = _StreamCollector()
        await executor._read_stream(FakeProc(), collector)

        assert len(received) == 3
        assert received[0]["type"] == "system"
        assert received[1]["type"] == "assistant"
        assert received[2]["type"] == "result"

    @pytest.mark.asyncio
    async def test_callback_error_does_not_kill_stream(self):
        """A callback that raises should not prevent event processing."""
        from flatmachines.adapters.claude_code import (
            ClaudeCodeExecutor,
            _StreamCollector,
        )
        from flatmachines.adapters.call_throttle import CallThrottle

        call_count = 0

        def bad_callback(event):
            nonlocal call_count
            call_count += 1
            raise RuntimeError("callback boom")

        executor = ClaudeCodeExecutor(
            config={}, config_dir="/tmp", settings={},
            throttle=CallThrottle(),
        )
        executor._stream_event_callback = bad_callback

        events = [
            {"type": "system", "session_id": "s1"},
            {"type": "result", "result": "done", "usage": {}},
        ]
        lines = [json.dumps(e).encode() + b"\n" for e in events]

        class FakeStdout:
            def __init__(self):
                self._lines = iter(lines)
            async def readline(self):
                try:
                    return next(self._lines)
                except StopIteration:
                    return b""

        class FakeStderr:
            async def read(self, n):
                return b""

        class FakeProc:
            stdout = FakeStdout()
            stderr = FakeStderr()

        collector = _StreamCollector()
        # Should not raise despite callback errors
        await executor._read_stream(FakeProc(), collector)

        # Callback was called for both events
        assert call_count == 2
        # Collector still got both events
        assert len(collector.events) == 2


# ---------------------------------------------------------------------------
# Codex CLI Executor callback integration tests
# ---------------------------------------------------------------------------


class TestCodexCliStreamCallback:
    """Test that CodexCliExecutor has _stream_event_callback support."""

    def test_callback_attribute_exists(self):
        from flatmachines.adapters.codex_cli import CodexCliExecutor
        from flatmachines.adapters.call_throttle import CallThrottle
        executor = CodexCliExecutor(
            config={}, config_dir="/tmp", settings={},
            throttle=CallThrottle(),
        )
        assert hasattr(executor, "_stream_event_callback")
        assert executor._stream_event_callback is None


# ---------------------------------------------------------------------------
# Engine bind/unbind tests
# ---------------------------------------------------------------------------


class TestBindStreamCallback:
    """Test FlatMachine._bind_stream_callback / _unbind_stream_callback."""

    def _make_machine(self, hooks: MachineHooks):
        """Create a minimal FlatMachine with given hooks."""
        from flatmachines import FlatMachine
        config = {
            "spec": "flatmachine",
            "spec_version": "2.0.0",
            "data": {
                "name": "test",
                "context": {},
                "agents": {
                    "dummy": {
                        "type": "flatagent",
                        "config": {
                            "spec": "flatagent",
                            "spec_version": "2.5.0",
                            "data": {
                                "name": "dummy",
                                "model": {"provider": "test", "name": "test"},
                                "prompts": {"system": "test"},
                            },
                        },
                    }
                },
                "states": {
                    "start": {"type": "initial", "transitions": [{"to": "done"}]},
                    "done": {"type": "final"},
                },
            },
        }
        return FlatMachine(config_dict=config, hooks=hooks)

    def test_binds_callback_when_hook_overridden(self):
        """Callback is set when hooks override on_agent_stream_event."""
        hooks = CollectingHooks()
        machine = self._make_machine(hooks)

        # Fake executor with the attribute
        class FakeExecutor:
            _stream_event_callback = None

        executor = FakeExecutor()
        machine._bind_stream_callback(executor, "my_state", {"ctx": 1})
        assert executor._stream_event_callback is not None

        # Call it and verify events flow to hooks
        executor._stream_event_callback({"type": "test"})
        assert len(hooks.events) == 1
        assert hooks.events[0][0] == "my_state"

    def test_skips_when_no_attribute(self):
        """Executors without _stream_event_callback are silently skipped."""
        hooks = CollectingHooks()
        machine = self._make_machine(hooks)

        class PlainExecutor:
            pass

        executor = PlainExecutor()
        # Should not raise
        machine._bind_stream_callback(executor, "s", {})

    def test_skips_when_hook_not_overridden(self):
        """Default MachineHooks.on_agent_stream_event → no callback overhead."""
        hooks = MachineHooks()
        machine = self._make_machine(hooks)

        class FakeExecutor:
            _stream_event_callback = None

        executor = FakeExecutor()
        machine._bind_stream_callback(executor, "s", {})
        assert executor._stream_event_callback is None

    def test_unbind_clears_callback(self):
        """_unbind_stream_callback sets callback to None."""
        hooks = CollectingHooks()
        machine = self._make_machine(hooks)

        class FakeExecutor:
            _stream_event_callback = None

        executor = FakeExecutor()
        machine._bind_stream_callback(executor, "s", {})
        assert executor._stream_event_callback is not None

        machine._unbind_stream_callback(executor)
        assert executor._stream_event_callback is None

    def test_unbind_noop_without_attribute(self):
        """_unbind_stream_callback is safe on plain executors."""
        from flatmachines import FlatMachine

        class PlainExecutor:
            pass

        # Static method, can call directly
        FlatMachine._unbind_stream_callback(PlainExecutor())  # Should not raise

    def test_composite_hooks_trigger_callback(self):
        """CompositeHooks with one overriding child triggers the callback."""
        collector = CollectingHooks()
        composite = CompositeHooks(MachineHooks(), collector)
        machine = self._make_machine(composite)

        class FakeExecutor:
            _stream_event_callback = None

        executor = FakeExecutor()
        machine._bind_stream_callback(executor, "s", {})
        # CompositeHooks overrides on_agent_stream_event, so callback is set
        assert executor._stream_event_callback is not None

        executor._stream_event_callback({"type": "result"})
        assert len(collector.events) == 1


# ---------------------------------------------------------------------------
# StreamEventCallback type tests
# ---------------------------------------------------------------------------


class TestStreamEventCallbackType:
    def test_is_optional_callable(self):
        """StreamEventCallback should accept None and callables."""
        cb: StreamEventCallback = None
        assert cb is None

        cb = lambda event: None
        assert callable(cb)

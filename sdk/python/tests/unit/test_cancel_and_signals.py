"""Tests for FlatMachine.cancel() and execute_sync(handle_signals=...)."""

from __future__ import annotations

import asyncio
import signal
import sys
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from flatmachines import FlatMachine


# ---------------------------------------------------------------------------
# Minimal config for constructing FlatMachine instances
# ---------------------------------------------------------------------------

_MINIMAL_CONFIG = {
    "spec": "flatmachine",
    "spec_version": "2.5.0",
    "data": {
        "name": "cancel-test",
        "agents": {
            "dummy": {
                "spec": "flatagent",
                "spec_version": "2.5.0",
                "data": {
                    "name": "dummy",
                    "model": {"provider": "test", "name": "test"},
                    "prompts": {"system": "test"},
                },
            },
        },
        "states": {
            "start": {
                "type": "initial",
                "agent": "dummy",
                "transitions": [{"to": "done"}],
            },
            "done": {"type": "final"},
        },
    },
}


# ---------------------------------------------------------------------------
# Fake executor with cancel support
# ---------------------------------------------------------------------------

class FakeCancellableExecutor:
    """Executor that records cancel() calls."""

    def __init__(self):
        self.cancelled = False
        self.cancel_count = 0

    async def execute(self, input_data, context=None, session_id=None):
        await asyncio.sleep(100)  # simulate long-running work

    async def cancel(self) -> bool:
        self.cancelled = True
        self.cancel_count += 1
        return True

    @property
    def metadata(self):
        return {}


class FakeNonCancellableExecutor:
    """Executor without a cancel() method."""

    async def execute(self, input_data, context=None, session_id=None):
        return {}

    @property
    def metadata(self):
        return {}


# ---------------------------------------------------------------------------
# FlatMachine.cancel() tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestFlatMachineCancel:
    async def test_cancel_propagates_to_executors(self):
        """cancel() calls cancel() on all cached executors."""
        machine = FlatMachine(config_dict=_MINIMAL_CONFIG)

        executor1 = FakeCancellableExecutor()
        executor2 = FakeCancellableExecutor()
        machine._agents = {"agent1": executor1, "agent2": executor2}

        await machine.cancel()

        assert executor1.cancelled
        assert executor2.cancelled

    async def test_cancel_skips_executors_without_cancel(self):
        """cancel() skips executors that don't have a cancel() method."""
        machine = FlatMachine(config_dict=_MINIMAL_CONFIG)

        cancellable = FakeCancellableExecutor()
        non_cancellable = FakeNonCancellableExecutor()
        machine._agents = {"a": cancellable, "b": non_cancellable}

        await machine.cancel()

        assert cancellable.cancelled
        # No error raised for non-cancellable

    async def test_cancel_with_no_agents(self):
        """cancel() with empty agent cache is a no-op."""
        machine = FlatMachine(config_dict=_MINIMAL_CONFIG)
        assert machine._agents == {}
        await machine.cancel()  # should not raise

    async def test_cancel_handles_executor_errors(self):
        """cancel() swallows exceptions from individual executors."""
        machine = FlatMachine(config_dict=_MINIMAL_CONFIG)

        class FailingExecutor:
            async def cancel(self):
                raise RuntimeError("cancel failed")

            @property
            def metadata(self):
                return {}

        good = FakeCancellableExecutor()
        bad = FailingExecutor()
        machine._agents = {"good": good, "bad": bad}

        await machine.cancel()  # should not raise

        assert good.cancelled  # good executor was still cancelled

    async def test_cancel_idempotent(self):
        """cancel() can be called multiple times safely."""
        machine = FlatMachine(config_dict=_MINIMAL_CONFIG)

        executor = FakeCancellableExecutor()
        machine._agents = {"agent": executor}

        await machine.cancel()
        await machine.cancel()

        assert executor.cancel_count == 2


# ---------------------------------------------------------------------------
# execute_sync handle_signals tests
# ---------------------------------------------------------------------------

class TestExecuteSyncSignals:
    def test_handle_signals_default_true(self):
        """handle_signals defaults to True in the signature."""
        import inspect
        sig = inspect.signature(FlatMachine.execute_sync)
        p = sig.parameters["handle_signals"]
        assert p.default is True

    def test_handle_signals_installs_and_restores_handler(self):
        """SIGINT handler is installed during execution and restored after."""
        machine = FlatMachine(config_dict=_MINIMAL_CONFIG)

        original_handler = signal.getsignal(signal.SIGINT)

        installed_handler = None

        async def _fake_execute(**kwargs):
            nonlocal installed_handler
            installed_handler = signal.getsignal(signal.SIGINT)
            return {"result": "ok"}

        with patch.object(machine, "execute", side_effect=_fake_execute):
            result = machine.execute_sync(
                input={"statement": "test"}, handle_signals=True
            )

        assert result == {"result": "ok"}
        # During execution, a custom handler was installed
        assert installed_handler is not None
        assert installed_handler != original_handler
        # After execution, original handler is restored
        assert signal.getsignal(signal.SIGINT) == original_handler

    def test_handle_signals_false_no_handler(self):
        """handle_signals=False does not change the SIGINT handler."""
        machine = FlatMachine(config_dict=_MINIMAL_CONFIG)

        original_handler = signal.getsignal(signal.SIGINT)

        during_handler = None

        async def _fake_execute(**kwargs):
            nonlocal during_handler
            during_handler = signal.getsignal(signal.SIGINT)
            return {"result": "ok"}

        with patch.object(machine, "execute", side_effect=_fake_execute):
            result = machine.execute_sync(
                input={"statement": "test"}, handle_signals=False
            )

        assert result == {"result": "ok"}
        # Handler was NOT changed during execution
        assert during_handler == original_handler

    def test_cancelled_raises_keyboard_interrupt(self):
        """CancelledError from SIGINT handler raises KeyboardInterrupt."""
        machine = FlatMachine(config_dict=_MINIMAL_CONFIG)

        async def _fake_execute(**kwargs):
            raise asyncio.CancelledError()

        with patch.object(machine, "execute", side_effect=_fake_execute):
            with pytest.raises(KeyboardInterrupt):
                machine.execute_sync(input={}, handle_signals=True)


# ---------------------------------------------------------------------------
# Claude Code adapter termios tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestClaudeCodeTermios:
    async def test_termios_saved_and_restored(self):
        """_invoke_once saves/restores terminal state around subprocess."""
        from flatmachines.adapters.claude_code import ClaudeCodeExecutor
        from flatmachines.adapters.call_throttle import CallThrottle

        executor = ClaudeCodeExecutor(
            config={},
            config_dir="/tmp/test",
            settings={},
            throttle=CallThrottle(),
        )

        # Build a fake process
        result_event = {
            "type": "result",
            "is_error": False,
            "result": "done",
            "stop_reason": "end_turn",
            "session_id": "s1",
            "total_cost_usd": 0.01,
            "usage": {
                "input_tokens": 10,
                "output_tokens": 5,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
            },
            "num_turns": 1,
            "duration_ms": 100,
        }
        import json

        class FakeProc:
            pid = 12345
            returncode = 0

            class stdout:
                _lines = [json.dumps(result_event).encode() + b"\n"]
                _idx = 0

                @classmethod
                async def readline(cls):
                    if cls._idx < len(cls._lines):
                        line = cls._lines[cls._idx]
                        cls._idx += 1
                        return line
                    return b""

            class stderr:
                @staticmethod
                async def read(n=-1):
                    return b""

            @staticmethod
            async def wait():
                pass

        tcgetattr_calls = []
        tcsetattr_calls = []
        fake_termios_state = [1, 2, 3]  # fake saved state

        with patch("asyncio.create_subprocess_exec", return_value=FakeProc()), \
             patch("flatmachines.adapters.claude_code._termios") as mock_termios:
            mock_termios.tcgetattr.return_value = fake_termios_state
            mock_termios.error = OSError
            mock_termios.TCSADRAIN = 1

            def _track_get(fd):
                tcgetattr_calls.append(fd)
                return fake_termios_state

            def _track_set(fd, when, attrs):
                tcsetattr_calls.append((fd, when, attrs))

            mock_termios.tcgetattr.side_effect = _track_get
            mock_termios.tcsetattr.side_effect = _track_set

            result = await executor._invoke_once(
                task="test", session_id="s1", resume=False,
            )

        assert result.error is None
        # termios was saved before subprocess
        assert len(tcgetattr_calls) == 1
        # termios was restored after subprocess
        assert len(tcsetattr_calls) == 1
        assert tcsetattr_calls[0][2] == fake_termios_state

    async def test_termios_not_available(self):
        """When termios is None (Windows), no errors occur."""
        from flatmachines.adapters.claude_code import ClaudeCodeExecutor
        from flatmachines.adapters.call_throttle import CallThrottle

        executor = ClaudeCodeExecutor(
            config={},
            config_dir="/tmp/test",
            settings={},
            throttle=CallThrottle(),
        )

        result_event = {
            "type": "result",
            "is_error": False,
            "result": "done",
            "stop_reason": "end_turn",
            "session_id": "s1",
            "total_cost_usd": 0.01,
            "usage": {
                "input_tokens": 10,
                "output_tokens": 5,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
            },
            "num_turns": 1,
            "duration_ms": 100,
        }
        import json

        class FakeProc:
            pid = 12345
            returncode = 0

            class stdout:
                _lines = [json.dumps(result_event).encode() + b"\n"]
                _idx = 0

                @classmethod
                async def readline(cls):
                    if cls._idx < len(cls._lines):
                        line = cls._lines[cls._idx]
                        cls._idx += 1
                        return line
                    return b""

            class stderr:
                @staticmethod
                async def read(n=-1):
                    return b""

            @staticmethod
            async def wait():
                pass

        with patch("asyncio.create_subprocess_exec", return_value=FakeProc()), \
             patch("flatmachines.adapters.claude_code._termios", None):
            result = await executor._invoke_once(
                task="test", session_id="s1", resume=False,
            )

        assert result.error is None
        assert result.content == "done"

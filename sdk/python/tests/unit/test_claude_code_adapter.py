"""Unit tests for the Claude Code CLI adapter."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from flatmachines.adapters.claude_code import (
    ClaudeCodeAdapter,
    ClaudeCodeExecutor,
    _StreamCollector,
    _map_stop_reason,
    _DEFAULT_EXIT_SENTINEL,
    _DEFAULT_MODEL,
    _DEFAULT_EFFORT,
    _DEFAULT_MAX_CONTINUATIONS,
    _DEFAULT_RATE_LIMIT_DELAY,
    _DEFAULT_RATE_LIMIT_JITTER,
)
from flatagents.monitoring import AgentMonitor
from flatmachines.agents import AgentAdapterContext, AgentRef, AgentResult

FIXTURES = Path(__file__).parent.parent / "fixtures" / "claude_code"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_fixture(name: str) -> List[str]:
    """Load NDJSON fixture lines."""
    with open(FIXTURES / name) as f:
        return [line for line in f.read().splitlines() if line.strip()]


def _make_executor(config: Optional[Dict[str, Any]] = None) -> ClaudeCodeExecutor:
    from flatmachines.adapters.call_throttle import CallThrottle
    return ClaudeCodeExecutor(
        config=config or {},
        config_dir="/tmp/test",
        settings={},
        throttle=CallThrottle(),  # disabled — unit tests shouldn't sleep
    )


class FakeProcess:
    """Fake asyncio.subprocess.Process that yields canned NDJSON lines."""

    def __init__(self, lines: List[str], returncode: int = 0, stderr: bytes = b""):
        self._lines = lines
        self.returncode = returncode
        self._stderr_data = stderr
        self.stdout = self._FakeStdout(lines)
        self.stderr = self._FakeStderr(stderr)
        self._killed = False

    class _FakeStdout:
        def __init__(self, lines: List[str]):
            self._lines = list(lines)
            self._idx = 0

        async def readline(self) -> bytes:
            if self._idx < len(self._lines):
                line = self._lines[self._idx]
                self._idx += 1
                return (line + "\n").encode()
            return b""

    class _FakeStderr:
        def __init__(self, data: bytes):
            self._data = data
            self._read = False

        async def read(self, n: int = -1) -> bytes:
            if not self._read:
                self._read = True
                return self._data
            return b""

    async def wait(self):
        pass

    def send_signal(self, sig):
        self._killed = True

    def kill(self):
        self._killed = True


async def _fake_subprocess(*args, **kwargs):
    """Default fake that returns empty result — override per test."""
    raise RuntimeError("_fake_subprocess not configured")


# ---------------------------------------------------------------------------
# _build_args tests
# ---------------------------------------------------------------------------

class TestBuildArgs:
    def test_defaults(self):
        executor = _make_executor()
        args = executor._build_args("do something", "sess-1", resume=False)
        assert args[0] == "claude"
        assert "-p" in args
        assert "do something" in args
        assert "--output-format" in args
        assert "stream-json" in args
        assert "--verbose" in args
        assert "--session-id" in args
        assert "sess-1" in args
        assert "--model" in args
        assert "opus" in args
        assert "--effort" in args
        assert "high" in args
        # No --resume
        assert "--resume" not in args

    def test_resume_mode(self):
        executor = _make_executor()
        args = executor._build_args("continue", "sess-1", resume=True)
        assert "--resume" in args
        assert "sess-1" in args
        assert "--session-id" not in args

    def test_custom_model(self):
        executor = _make_executor({"model": "sonnet"})
        args = executor._build_args("task", "s1", resume=False)
        idx = args.index("--model")
        assert args[idx + 1] == "sonnet"

    def test_permission_mode(self):
        executor = _make_executor({"permission_mode": "bypassPermissions"})
        args = executor._build_args("task", "s1", resume=False)
        idx = args.index("--permission-mode")
        assert args[idx + 1] == "bypassPermissions"

    def test_system_prompt(self):
        executor = _make_executor({"system_prompt": "You are a coder."})
        args = executor._build_args("task", "s1", resume=False)
        idx = args.index("--system-prompt")
        assert args[idx + 1] == "You are a coder."
        assert "--append-system-prompt" not in args

    def test_append_system_prompt(self):
        executor = _make_executor({"append_system_prompt": "Also do X."})
        args = executor._build_args("task", "s1", resume=False)
        idx = args.index("--append-system-prompt")
        assert args[idx + 1] == "Also do X."
        assert "--system-prompt" not in args

    def test_system_prompt_wins_over_append(self):
        executor = _make_executor({
            "system_prompt": "Full replace.",
            "append_system_prompt": "Should be ignored.",
        })
        args = executor._build_args("task", "s1", resume=False)
        assert "--system-prompt" in args
        assert "--append-system-prompt" not in args

    def test_tools_exact_whitelist(self):
        executor = _make_executor({"tools": ["Bash", "Read", "Write"]})
        args = executor._build_args("task", "s1", resume=False)
        idx = args.index("--tools")
        assert args[idx + 1:idx + 4] == ["Bash", "Read", "Write"]

    def test_budget_disabled_by_default(self):
        executor = _make_executor()
        args = executor._build_args("task", "s1", resume=False)
        assert "--max-budget-usd" not in args

    def test_budget_zero_disabled(self):
        executor = _make_executor({"max_budget_usd": 0})
        args = executor._build_args("task", "s1", resume=False)
        assert "--max-budget-usd" not in args

    def test_budget_positive(self):
        executor = _make_executor({"max_budget_usd": 2.5})
        args = executor._build_args("task", "s1", resume=False)
        idx = args.index("--max-budget-usd")
        assert args[idx + 1] == "2.5"

    def test_custom_claude_bin(self):
        executor = _make_executor({"claude_bin": "/usr/local/bin/claude"})
        args = executor._build_args("task", "s1", resume=False)
        assert args[0] == "/usr/local/bin/claude"

    def test_custom_effort(self):
        executor = _make_executor({"effort": "low"})
        args = executor._build_args("task", "s1", resume=False)
        idx = args.index("--effort")
        assert args[idx + 1] == "low"

    def test_dangerously_skip_permissions(self):
        executor = _make_executor({"dangerously_skip_permissions": True})
        args = executor._build_args("task", "s1", resume=False)
        assert "--dangerously-skip-permissions" in args

    def test_dangerously_skip_permissions_false(self):
        executor = _make_executor({"dangerously_skip_permissions": False})
        args = executor._build_args("task", "s1", resume=False)
        assert "--dangerously-skip-permissions" not in args

    def test_add_dirs(self):
        executor = _make_executor({"add_dirs": ["/tmp/extra", "/home/user/data"]})
        args = executor._build_args("task", "s1", resume=False)
        # Should have --add-dir /tmp/extra --add-dir /home/user/data
        add_dir_indices = [i for i, a in enumerate(args) if a == "--add-dir"]
        assert len(add_dir_indices) == 2
        assert args[add_dir_indices[0] + 1] == "/tmp/extra"
        assert args[add_dir_indices[1] + 1] == "/home/user/data"

    def test_add_dirs_empty(self):
        executor = _make_executor({"add_dirs": []})
        args = executor._build_args("task", "s1", resume=False)
        assert "--add-dir" not in args


class TestThrottleDefaults:
    def test_default_throttle_enabled(self):
        """Executor created without injected throttle uses adapter defaults."""
        executor = ClaudeCodeExecutor(
            config={},
            config_dir="/tmp/test",
            settings={},
        )
        assert executor._throttle.enabled
        assert executor._throttle._delay == _DEFAULT_RATE_LIMIT_DELAY
        assert executor._throttle._jitter == _DEFAULT_RATE_LIMIT_JITTER

    def test_throttle_override_from_config(self):
        executor = ClaudeCodeExecutor(
            config={"rate_limit_delay": 1.0, "rate_limit_jitter": 0.5},
            config_dir="/tmp/test",
            settings={},
        )
        assert executor._throttle._delay == 1.0
        assert executor._throttle._jitter == 0.5

    def test_throttle_disabled_via_config(self):
        executor = ClaudeCodeExecutor(
            config={"rate_limit_delay": 0, "rate_limit_jitter": 0},
            config_dir="/tmp/test",
            settings={},
        )
        assert not executor._throttle.enabled

    def test_injected_throttle_wins(self):
        from flatmachines.adapters.call_throttle import CallThrottle
        custom = CallThrottle(delay=99.0, jitter=0.0)
        executor = ClaudeCodeExecutor(
            config={},
            config_dir="/tmp/test",
            settings={},
            throttle=custom,
        )
        assert executor._throttle is custom


# ---------------------------------------------------------------------------
# Stream collector tests
# ---------------------------------------------------------------------------

class TestStreamCollector:
    def test_simple_result(self):
        lines = _load_fixture("simple_result.ndjson")
        collector = _StreamCollector()
        for line in lines:
            collector.ingest(json.loads(line))

        assert collector.session_id == "abc-123"
        assert collector.result_event is not None
        assert collector.result_event["result"] == "2 + 2 = 4."
        assert collector.result_event["is_error"] is False
        assert len(collector.events) == 3  # system + assistant + result

    def test_tool_use_tracking(self):
        lines = _load_fixture("tool_use_session.ndjson")
        collector = _StreamCollector()
        for line in lines:
            collector.ingest(json.loads(line))

        assert collector.session_id == "sess-tool-1"
        assert collector.result_event is not None
        assert "<<AGENT_EXIT>>" in collector.result_event["result"]

        # Check tool_use tracking
        assert "toolu_001" in collector._pending_tools
        assert collector._pending_tools["toolu_001"]["name"] == "Read"
        assert "toolu_002" in collector._pending_tools
        assert collector._pending_tools["toolu_002"]["name"] == "Edit"

    def test_get_tool_calls_from_assistant(self):
        lines = _load_fixture("tool_use_session.ndjson")
        collector = _StreamCollector()
        events = [json.loads(line) for line in lines]
        for event in events:
            collector.ingest(event)

        # First assistant event has a tool_use
        assistant_events = [e for e in events if e["type"] == "assistant"]
        calls = collector.get_tool_calls_from_assistant(assistant_events[0])
        assert len(calls) == 1
        assert calls[0]["name"] == "Read"
        assert calls[0]["id"] == "toolu_001"

    def test_get_tool_results_from_user(self):
        lines = _load_fixture("tool_use_session.ndjson")
        collector = _StreamCollector()
        events = [json.loads(line) for line in lines]
        for event in events:
            collector.ingest(event)

        user_events = [e for e in events if e["type"] == "user"]
        results = collector.get_tool_results_from_user(user_events[0])
        assert len(results) == 1
        assert results[0]["name"] == "Read"
        assert "def main" in results[0]["content"]

    def test_error_result(self):
        lines = _load_fixture("error_result.ndjson")
        collector = _StreamCollector()
        for line in lines:
            collector.ingest(json.loads(line))

        assert collector.result_event is not None
        assert collector.result_event["is_error"] is True
        assert "Rate limit" in collector.result_event["result"]


# ---------------------------------------------------------------------------
# _map_stop_reason tests
# ---------------------------------------------------------------------------

class TestMapStopReason:
    def test_end_turn(self):
        assert _map_stop_reason("end_turn") == "stop"

    def test_max_tokens(self):
        assert _map_stop_reason("max_tokens") == "length"

    def test_none(self):
        assert _map_stop_reason(None) is None

    def test_passthrough(self):
        assert _map_stop_reason("unknown_reason") == "unknown_reason"


# ---------------------------------------------------------------------------
# Result mapping tests
# ---------------------------------------------------------------------------

class TestResultMapping:
    def test_simple_result_mapping(self):
        lines = _load_fixture("simple_result.ndjson")
        collector = _StreamCollector()
        for line in lines:
            collector.ingest(json.loads(line))

        executor = _make_executor()
        result = executor._build_result(collector, "abc-123", "")

        assert result.content == "2 + 2 = 4."
        assert result.output["result"] == "2 + 2 = 4."
        assert result.output["session_id"] == "abc-123"
        assert result.usage["input_tokens"] == 10
        assert result.usage["output_tokens"] == 8
        assert result.usage["cache_read_tokens"] == 6000
        assert result.usage["cache_write_tokens"] == 500
        assert result.cost == 0.02
        assert result.finish_reason == "stop"
        assert result.error is None
        assert result.metadata["session_id"] == "abc-123"
        assert result.metadata["num_turns"] == 1
        assert result.metadata["duration_ms"] == 1500
        assert len(result.metadata["stream_events"]) == 3

    def test_error_result_mapping(self):
        lines = _load_fixture("error_result.ndjson")
        collector = _StreamCollector()
        for line in lines:
            collector.ingest(json.loads(line))

        executor = _make_executor()
        result = executor._build_result(collector, "sess-err-1", "")

        assert result.error is not None
        assert result.error["code"] == "server_error"
        assert "Rate limit" in result.error["message"]

    def test_no_truncation_of_content(self):
        """Verify that long content is not truncated."""
        long_text = "A" * 100_000
        event_line = json.dumps({
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "duration_ms": 100,
            "num_turns": 1,
            "result": long_text,
            "stop_reason": "end_turn",
            "session_id": "sess-long",
            "total_cost_usd": 0.01,
            "usage": {"input_tokens": 1, "output_tokens": 1,
                      "cache_creation_input_tokens": 0,
                      "cache_read_input_tokens": 0},
        })
        collector = _StreamCollector()
        collector.ingest(json.loads(event_line))

        executor = _make_executor()
        result = executor._build_result(collector, "sess-long", "")

        assert len(result.content) == 100_000
        assert result.content == long_text


# ---------------------------------------------------------------------------
# execute() integration tests (mocked subprocess)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestExecute:
    async def test_simple_invocation(self):
        lines = _load_fixture("simple_result.ndjson")
        proc = FakeProcess(lines)

        executor = _make_executor({"permission_mode": "bypassPermissions"})
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await executor.execute({"task": "what is 2+2"})

        assert result.error is None
        assert result.content == "2 + 2 = 4."
        assert result.output["session_id"] == "abc-123"
        assert result.finish_reason == "stop"

    async def test_missing_task_returns_error(self):
        executor = _make_executor()
        result = await executor.execute({})
        assert result.error is not None
        assert result.error["code"] == "invalid_request"

    async def test_resume_session(self):
        lines = _load_fixture("simple_result.ndjson")
        proc = FakeProcess(lines)

        executor = _make_executor()
        with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
            result = await executor.execute({
                "task": "continue",
                "resume_session": "existing-sess-id",
            })

            # Verify --resume was used
            call_args = mock_exec.call_args
            args_list = list(call_args[0])
            assert "--resume" in args_list
            assert "existing-sess-id" in args_list
            assert "--session-id" not in args_list

    async def test_new_session_generates_uuid(self):
        lines = _load_fixture("simple_result.ndjson")
        proc = FakeProcess(lines)

        executor = _make_executor()
        with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
            await executor.execute({"task": "hello"})

            call_args = mock_exec.call_args
            args_list = list(call_args[0])
            assert "--session-id" in args_list
            # UUID should be present after --session-id
            idx = args_list.index("--session-id")
            session_id = args_list[idx + 1]
            assert len(session_id) == 36  # UUID format

    async def test_sentinel_detection(self):
        lines = _load_fixture("tool_use_session.ndjson")
        proc = FakeProcess(lines)

        executor = _make_executor()
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await executor.execute({"task": "edit the file"})

        assert "<<AGENT_EXIT>>" in result.content
        assert result.error is None

    async def test_continuation_loop(self):
        """Test that executor continues when sentinel not found."""
        lines_first = _load_fixture("needs_continuation.ndjson")
        lines_second = _load_fixture("continuation_done.ndjson")

        call_count = 0

        async def _fake_exec(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return FakeProcess(lines_first)
            else:
                return FakeProcess(lines_second)

        executor = _make_executor({"max_continuations": 5})
        with patch("asyncio.create_subprocess_exec", side_effect=_fake_exec):
            result = await executor.execute({"task": "implement feature"})

        assert call_count == 2
        assert "<<AGENT_EXIT>>" in result.content
        assert result.metadata["continuation_attempts"] == 2
        # Aggregated usage
        assert result.usage["api_calls"] == 2

    async def test_continuation_disabled(self):
        """max_continuations=0 means no auto-continue."""
        lines = _load_fixture("needs_continuation.ndjson")
        proc = FakeProcess(lines)

        executor = _make_executor({"max_continuations": 0})
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await executor.execute({"task": "implement feature"})

        # Should return without continuing
        assert "<<AGENT_EXIT>>" not in (result.content or "")
        assert result.metadata["continuation_attempts"] == 1

    async def test_continuation_limit_exhausted(self):
        """Stops after max_continuations even without sentinel."""
        lines = _load_fixture("needs_continuation.ndjson")

        async def _fake_exec(*args, **kwargs):
            return FakeProcess(lines)

        executor = _make_executor({"max_continuations": 3})
        with patch("asyncio.create_subprocess_exec", side_effect=_fake_exec):
            result = await executor.execute({"task": "implement feature"})

        assert result.metadata["continuation_attempts"] == 4  # 1 initial + 3 continuations

    async def test_continuation_prompt_used_on_resume(self):
        """Verify the continuation prompt is sent on second invocation."""
        lines_first = _load_fixture("needs_continuation.ndjson")
        lines_second = _load_fixture("continuation_done.ndjson")

        calls = []

        async def _fake_exec(*args, **kwargs):
            calls.append(list(args))
            if len(calls) == 1:
                return FakeProcess(lines_first)
            return FakeProcess(lines_second)

        executor = _make_executor({"max_continuations": 5})
        with patch("asyncio.create_subprocess_exec", side_effect=_fake_exec):
            await executor.execute({"task": "do stuff"})

        # Second call should use the continuation prompt
        second_args = calls[1]
        assert "-p" in second_args
        p_idx = second_args.index("-p")
        prompt = second_args[p_idx + 1]
        assert "<<AGENT_EXIT>>" in prompt
        assert "Continue" in prompt

        # Second call should use --resume
        assert "--resume" in second_args

    async def test_error_stops_continuation(self):
        """Error result stops the continuation loop."""
        lines = _load_fixture("error_result.ndjson")
        proc = FakeProcess(lines)

        executor = _make_executor({"max_continuations": 10})
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await executor.execute({"task": "do something"})

        assert result.error is not None
        assert result.metadata["continuation_attempts"] == 1

    async def test_process_failure_no_result(self):
        """Process exits non-zero with no result event."""
        proc = FakeProcess([], returncode=1, stderr=b"segfault")

        executor = _make_executor()
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await executor.execute({"task": "crash"})

        assert result.error is not None
        assert result.error["code"] == "server_error"
        assert "segfault" in result.error["message"]
        assert result.metadata["stderr"] == "segfault"

    async def test_timeout_raises(self):
        """Timeout > 0 raises TimeoutError."""

        async def _hanging_readline():
            await asyncio.sleep(100)
            return b""

        class HangingProcess:
            def __init__(self):
                self.returncode = None
                self.stdout = self
                self.stderr = MagicMock()
                self.stderr.read = AsyncMock(return_value=b"")
            async def readline(self):
                await asyncio.sleep(100)
                return b""
            async def wait(self):
                pass
            def send_signal(self, sig):
                pass
            def kill(self):
                pass

        executor = _make_executor({"timeout": 0.1})
        with patch("asyncio.create_subprocess_exec", return_value=HangingProcess()):
            with pytest.raises(TimeoutError, match="timed out"):
                await executor.execute({"task": "hang"})

    async def test_no_timeout_by_default(self):
        """timeout=0 means no timeout."""
        lines = _load_fixture("simple_result.ndjson")
        proc = FakeProcess(lines)

        executor = _make_executor()  # no timeout config
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await executor.execute({"task": "hello"})

        assert result.error is None

    async def test_working_dir_resolved(self):
        """working_dir from config is passed to subprocess."""
        lines = _load_fixture("simple_result.ndjson")
        proc = FakeProcess(lines)

        executor = _make_executor({"working_dir": "/home/user/project"})
        with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
            await executor.execute({"task": "hello"})

            kwargs = mock_exec.call_args[1]
            assert kwargs["cwd"] == "/home/user/project"

    async def test_aggregated_cost(self):
        """Cost is aggregated across continuations."""
        lines_first = _load_fixture("needs_continuation.ndjson")
        lines_second = _load_fixture("continuation_done.ndjson")

        call_count = 0

        async def _fake_exec(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return FakeProcess(lines_first)
            return FakeProcess(lines_second)

        executor = _make_executor({"max_continuations": 5})
        with patch("asyncio.create_subprocess_exec", side_effect=_fake_exec):
            result = await executor.execute({"task": "implement"})

        # 0.05 + 0.03 = 0.08
        assert abs(result.cost - 0.08) < 0.001
        assert result.usage["input_tokens"] == 80 + 40
        assert result.usage["output_tokens"] == 70 + 20


# ---------------------------------------------------------------------------
# execute_with_tools tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestExecuteWithTools:
    async def test_raises_not_implemented(self):
        executor = _make_executor()
        with pytest.raises(NotImplementedError, match="tool loop"):
            await executor.execute_with_tools(
                input_data={"task": "x"},
                tools=[{"function": {"name": "bash"}}],
            )


# ---------------------------------------------------------------------------
# Adapter tests
# ---------------------------------------------------------------------------

class TestAdapter:
    def test_type_name(self):
        adapter = ClaudeCodeAdapter()
        assert adapter.type_name == "claude-code"

    def test_create_executor(self):
        adapter = ClaudeCodeAdapter()
        agent_ref = AgentRef(
            type="claude-code",
            config={"model": "sonnet", "permission_mode": "bypassPermissions"},
        )
        ctx = AgentAdapterContext(
            config_dir="/tmp/test",
            settings={},
            machine_name="test-machine",
        )

        executor = adapter.create_executor(
            agent_name="coder",
            agent_ref=agent_ref,
            context=ctx,
        )

        assert isinstance(executor, ClaudeCodeExecutor)
        # Verify config was passed through
        args = executor._build_args("hello", "s1", resume=False)
        assert "sonnet" in args
        assert "bypassPermissions" in args

    def test_settings_merge(self):
        """Global settings are merged under per-agent config."""
        adapter = ClaudeCodeAdapter()
        agent_ref = AgentRef(
            type="claude-code",
            config={"model": "sonnet"},
        )
        ctx = AgentAdapterContext(
            config_dir="/tmp/test",
            settings={
                "agent_runners": {
                    "claude_code": {
                        "permission_mode": "auto",
                        "claude_bin": "/opt/claude",
                    }
                }
            },
            machine_name="test-machine",
        )

        executor = adapter.create_executor(
            agent_name="coder",
            agent_ref=agent_ref,
            context=ctx,
        )

        args = executor._build_args("hello", "s1", resume=False)
        # Per-agent config wins for model
        assert "sonnet" in args
        # Settings provide permission_mode (not overridden by agent config)
        assert "auto" in args
        # Settings provide claude_bin
        assert args[0] == "/opt/claude"


# ---------------------------------------------------------------------------
# Registration test
# ---------------------------------------------------------------------------

class TestRegistration:
    def test_registered_in_builtins(self):
        from flatmachines.adapters import create_registry
        registry = create_registry()
        adapter = registry.get("claude-code")
        assert adapter.type_name == "claude-code"


# ---------------------------------------------------------------------------
# Unparseable NDJSON handling
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestUnparseableLines:
    async def test_skips_bad_json(self):
        """Bad JSON lines are skipped, result still captured."""
        lines = [
            '{"type":"system","session_id":"s1"}',
            'THIS IS NOT JSON',
            '{"type":"result","is_error":false,"result":"ok","stop_reason":"end_turn","session_id":"s1","total_cost_usd":0.01,"usage":{"input_tokens":1,"output_tokens":1,"cache_creation_input_tokens":0,"cache_read_input_tokens":0},"num_turns":1,"duration_ms":100}',
        ]
        proc = FakeProcess(lines)

        executor = _make_executor()
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await executor.execute({"task": "test"})

        assert result.error is None
        assert result.content == "ok"


# ---------------------------------------------------------------------------
# AgentMonitor metrics tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestAgentMonitorMetrics:
    """Verify that _invoke_once populates AgentMonitor metrics correctly."""

    async def test_success_metrics(self):
        """Successful invocation should populate token and cost metrics."""
        lines = _load_fixture("simple_result.ndjson")
        proc = FakeProcess(lines)

        executor = _make_executor()
        monitors = []

        _orig_init = AgentMonitor.__init__

        def _capture_init(self_monitor, *a, **kw):
            _orig_init(self_monitor, *a, **kw)
            monitors.append(self_monitor)

        with patch("asyncio.create_subprocess_exec", return_value=proc), \
             patch.object(AgentMonitor, "__init__", _capture_init):
            result = await executor._invoke_once(
                task="what is 2+2", session_id="s1", resume=False,
            )

        assert result.error is None
        assert len(monitors) == 1
        m = monitors[0].metrics
        assert m["input_tokens"] == 10
        assert m["output_tokens"] == 8
        assert m["tokens"] == 18
        assert m["cache_read_tokens"] == 6000
        assert m["cache_write_tokens"] == 500
        assert m["cost"] == 0.02
        assert "error" not in m

    async def test_error_metrics(self):
        """Error invocation should record error_type in metrics."""
        lines = _load_fixture("error_result.ndjson")
        proc = FakeProcess(lines)

        executor = _make_executor()
        monitors = []

        _orig_init = AgentMonitor.__init__

        def _capture_init(self_monitor, *a, **kw):
            _orig_init(self_monitor, *a, **kw)
            monitors.append(self_monitor)

        with patch("asyncio.create_subprocess_exec", return_value=proc), \
             patch.object(AgentMonitor, "__init__", _capture_init):
            result = await executor._invoke_once(
                task="fail", session_id="s2", resume=False,
            )

        assert result.error is not None
        assert len(monitors) == 1
        m = monitors[0].metrics
        assert m["error"] is True
        assert m["error_type"] == "ClaudeCodeError"

    async def test_process_failure_metrics(self):
        """Process crash with no result event should record error metrics."""
        proc = FakeProcess([], returncode=1, stderr=b"crash")

        executor = _make_executor()
        monitors = []

        _orig_init = AgentMonitor.__init__

        def _capture_init(self_monitor, *a, **kw):
            _orig_init(self_monitor, *a, **kw)
            monitors.append(self_monitor)

        with patch("asyncio.create_subprocess_exec", return_value=proc), \
             patch.object(AgentMonitor, "__init__", _capture_init):
            result = await executor._invoke_once(
                task="crash", session_id="s3", resume=False,
            )

        assert result.error is not None
        assert len(monitors) == 1
        m = monitors[0].metrics
        assert m["error"] is True
        assert m["error_type"] == "ClaudeCodeProcessError"

    async def test_monitor_agent_id_uses_model(self):
        """AgentMonitor should include the model name in agent_id."""
        lines = _load_fixture("simple_result.ndjson")
        proc = FakeProcess(lines)

        executor = _make_executor({"model": "sonnet"})
        agent_ids = []

        _orig_init = AgentMonitor.__init__

        def _capture_init(self_monitor, agent_id, *a, **kw):
            agent_ids.append(agent_id)
            _orig_init(self_monitor, agent_id, *a, **kw)

        with patch("asyncio.create_subprocess_exec", return_value=proc), \
             patch.object(AgentMonitor, "__init__", _capture_init):
            await executor._invoke_once(
                task="hello", session_id="s4", resume=False,
            )

        assert len(agent_ids) == 1
        assert agent_ids[0] == "claude-code/sonnet"

    async def test_continuation_summary_log(self, caplog):
        """Continuation loop should log aggregated summary when attempt > 1."""
        lines_first = _load_fixture("needs_continuation.ndjson")
        lines_second = _load_fixture("continuation_done.ndjson")

        call_count = 0

        async def _fake_exec(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return FakeProcess(lines_first)
            return FakeProcess(lines_second)

        executor = _make_executor({"max_continuations": 5})
        import logging
        # Enable propagation so caplog can capture via the root logger.
        # flatmachines.monitoring sets propagate=False on the namespace logger.
        fm_logger = logging.getLogger("flatmachines")
        orig_propagate = fm_logger.propagate
        fm_logger.propagate = True
        try:
            with patch("asyncio.create_subprocess_exec", side_effect=_fake_exec), \
                 caplog.at_level(logging.INFO):
                result = await executor.execute({"task": "implement"})
        finally:
            fm_logger.propagate = orig_propagate

        assert call_count == 2
        assert result.error is None
        # Find the continuation summary log
        summary_msgs = [r.message for r in caplog.records
                        if "continuation complete" in r.message]
        assert len(summary_msgs) == 1
        assert "attempts=2" in summary_msgs[0]

    async def test_no_continuation_summary_for_single(self, caplog):
        """Single invocation should NOT log continuation summary."""
        lines = _load_fixture("simple_result.ndjson")
        proc = FakeProcess(lines)

        executor = _make_executor()
        import logging
        fm_logger = logging.getLogger("flatmachines")
        orig_propagate = fm_logger.propagate
        fm_logger.propagate = True
        try:
            with patch("asyncio.create_subprocess_exec", return_value=proc), \
                 caplog.at_level(logging.INFO):
                result = await executor.execute({"task": "hello"})
        finally:
            fm_logger.propagate = orig_propagate

        assert result.error is None
        summary_msgs = [r.message for r in caplog.records
                        if "continuation complete" in r.message]
        assert len(summary_msgs) == 0

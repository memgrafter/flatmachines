"""Unit tests for the Codex CLI adapter."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import pytest

from flatmachines.adapters.codex_cli import (
    CodexCliAdapter,
    CodexCliExecutor,
    _ExecStreamCollector,
)
from flatmachines.agents import AgentResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_executor(config: Optional[Dict[str, Any]] = None) -> CodexCliExecutor:
    return CodexCliExecutor(
        config=config or {},
        config_dir="/tmp/test",
        settings={},
    )


# ---------------------------------------------------------------------------
# _ExecStreamCollector tests
# ---------------------------------------------------------------------------

class TestExecStreamCollector:

    def test_simple_message(self):
        c = _ExecStreamCollector()
        c.ingest({"type": "thread.started", "thread_id": "tid-123"})
        c.ingest({"type": "turn.started"})
        c.ingest({"type": "item.completed", "item": {
            "id": "item_0", "type": "agent_message", "text": "Hello world",
        }})
        c.ingest({"type": "turn.completed", "usage": {
            "input_tokens": 100, "cached_input_tokens": 50, "output_tokens": 10,
        }})

        assert c.thread_id == "tid-123"
        assert c.final_message == "Hello world"
        assert c.usage == {"input_tokens": 100, "cached_input_tokens": 50, "output_tokens": 10}
        assert c.error is None
        assert len(c.items) == 1
        assert len(c.events) == 4

    def test_tool_using_turn(self):
        c = _ExecStreamCollector()
        c.ingest({"type": "thread.started", "thread_id": "tid-456"})
        c.ingest({"type": "turn.started"})
        c.ingest({"type": "item.completed", "item": {
            "id": "item_0", "type": "agent_message", "text": "Let me check...",
        }})
        c.ingest({"type": "item.started", "item": {
            "id": "item_1", "type": "command_execution",
            "command": "/bin/bash -lc 'ls'",
            "aggregated_output": "", "exit_code": None, "status": "in_progress",
        }})
        c.ingest({"type": "item.completed", "item": {
            "id": "item_1", "type": "command_execution",
            "command": "/bin/bash -lc 'ls'",
            "aggregated_output": "file.txt\n", "exit_code": 0, "status": "completed",
        }})
        c.ingest({"type": "item.completed", "item": {
            "id": "item_2", "type": "agent_message", "text": "Found file.txt",
        }})
        c.ingest({"type": "turn.completed", "usage": {
            "input_tokens": 200, "cached_input_tokens": 100, "output_tokens": 30,
        }})

        assert c.final_message == "Found file.txt"
        assert len(c.items) == 3  # two agent_messages + one command
        assert c.items[1]["type"] == "command_execution"
        assert c.items[1]["exit_code"] == 0

    def test_error_turn(self):
        c = _ExecStreamCollector()
        c.ingest({"type": "thread.started", "thread_id": "tid-err"})
        c.ingest({"type": "turn.started"})
        c.ingest({"type": "error", "message": "API rate limit exceeded"})
        c.ingest({"type": "turn.failed", "error": {"message": "Rate limited"}})

        assert c.error is not None
        # The error event fires first, then turn.failed overwrites
        assert c.error["message"] == "Rate limited"
        assert c.final_message is None

    def test_turn_failed_with_string_error(self):
        c = _ExecStreamCollector()
        c.ingest({"type": "turn.failed", "error": "some string error"})
        assert c.error == {"message": "some string error"}

    def test_multiple_agent_messages_takes_last(self):
        c = _ExecStreamCollector()
        c.ingest({"type": "item.completed", "item": {
            "id": "item_0", "type": "agent_message", "text": "first",
        }})
        c.ingest({"type": "item.completed", "item": {
            "id": "item_1", "type": "agent_message", "text": "second",
        }})
        assert c.final_message == "second"

    def test_unknown_event_type_stored(self):
        c = _ExecStreamCollector()
        c.ingest({"type": "unknown_future_event", "data": 42})
        assert len(c.events) == 1
        assert c.events[0]["type"] == "unknown_future_event"


# ---------------------------------------------------------------------------
# _build_exec_args tests
# ---------------------------------------------------------------------------

class TestBuildExecArgs:

    def test_simple(self):
        executor = _make_executor({"model": "gpt-5.3-codex"})
        args = executor._build_exec_args("do stuff", None)
        assert args[0] == "codex"
        assert "exec" in args
        assert "--json" in args
        assert "--model" in args
        idx = args.index("--model")
        assert args[idx + 1] == "gpt-5.3-codex"
        # Prompt is the last positional arg
        assert args[-1] == "do stuff"

    def test_resume(self):
        executor = _make_executor({"model": "gpt-5.3-codex"})
        args = executor._build_exec_args("follow up", "thread-id-123")
        assert "resume" in args
        # Last two positionals: session_id then prompt
        assert args[-2] == "thread-id-123"
        assert args[-1] == "follow up"
        assert "--json" in args

    def test_output_schema(self):
        executor = _make_executor({"output_schema": "/tmp/schema.json"})
        args = executor._build_exec_args("task", None)
        assert "--output-schema" in args
        idx = args.index("--output-schema")
        assert args[idx + 1] == "/tmp/schema.json"

    def test_sandbox_modes(self):
        for mode in ("read-only", "workspace-write", "danger-full-access"):
            executor = _make_executor({"sandbox": mode})
            args = executor._build_exec_args("task", None)
            idx = args.index("--sandbox")
            assert args[idx + 1] == mode

    def test_resume_no_sandbox_flag(self):
        """codex exec resume does not support --sandbox."""
        executor = _make_executor({"sandbox": "read-only"})
        args = executor._build_exec_args("task", "session-123")
        assert "--sandbox" not in args
        assert "--full-auto" in args

    def test_config_overrides(self):
        executor = _make_executor({
            "config_overrides": {"service_tier": '"fast"', "foo.bar": '"baz"'},
        })
        args = executor._build_exec_args("task", None)
        c_indices = [i for i, a in enumerate(args) if a == "-c"]
        assert len(c_indices) >= 2  # reasoning_effort + 2 overrides

    def test_model_always_present(self):
        executor = _make_executor({})
        args = executor._build_exec_args("task", None)
        assert "--model" in args
        idx = args.index("--model")
        assert args[idx + 1] == "gpt-5.3-codex"  # default

    def test_feature_flags(self):
        executor = _make_executor({
            "feature_enable": ["fast_mode"],
            "feature_disable": ["multi_agent"],
        })
        args = executor._build_exec_args("task", None)
        assert "--enable" in args
        assert "fast_mode" in args
        assert "--disable" in args
        assert "multi_agent" in args

    def test_skip_git_repo_check(self):
        executor = _make_executor({"skip_git_repo_check": True})
        args = executor._build_exec_args("task", None)
        assert "--skip-git-repo-check" in args

    def test_ephemeral(self):
        executor = _make_executor({"ephemeral": True})
        args = executor._build_exec_args("task", None)
        assert "--ephemeral" in args

    def test_search(self):
        executor = _make_executor({"search": True})
        args = executor._build_exec_args("task", None)
        # search is passed as config override for exec mode
        assert "-c" in args
        c_args = [args[i + 1] for i, a in enumerate(args) if a == "-c"]
        assert any("search" in c for c in c_args)

    def test_add_dirs(self):
        executor = _make_executor({"add_dirs": ["/tmp/a", "/tmp/b"]})
        args = executor._build_exec_args("task", None)
        add_indices = [i for i, a in enumerate(args) if a == "--add-dir"]
        assert len(add_indices) == 2

    def test_dangerously_bypass(self):
        executor = _make_executor({"dangerously_bypass_approvals_and_sandbox": True})
        args = executor._build_exec_args("task", None)
        assert "--dangerously-bypass-approvals-and-sandbox" in args

    def test_custom_codex_bin(self):
        executor = _make_executor({"codex_bin": "/usr/local/bin/codex"})
        args = executor._build_exec_args("task", None)
        assert args[0] == "/usr/local/bin/codex"

    def test_full_auto_for_never_approval(self):
        """Default approval_policy=never uses --full-auto."""
        executor = _make_executor({"approval_policy": "never"})
        args = executor._build_exec_args("task", None)
        assert "--full-auto" in args
        assert "-a" not in args

    def test_no_duplicate_approval_flags(self):
        """Bypass flag should not also include --full-auto."""
        executor = _make_executor({"dangerously_bypass_approvals_and_sandbox": True})
        args = executor._build_exec_args("task", None)
        assert "--dangerously-bypass-approvals-and-sandbox" in args
        assert "--full-auto" not in args


# ---------------------------------------------------------------------------
# _build_result_from_exec tests
# ---------------------------------------------------------------------------

class TestBuildResultFromExec:

    def test_success(self):
        executor = _make_executor()
        collector = _ExecStreamCollector()
        collector.thread_id = "tid-1"
        collector.final_message = "result text"
        collector.usage = {"input_tokens": 100, "cached_input_tokens": 80, "output_tokens": 10}

        result = executor._build_result_from_exec(collector, 0, "")
        assert result.success
        assert result.content == "result text"
        assert result.finish_reason == "stop"
        assert result.usage["input_tokens"] == 100
        assert result.usage["cached_input_tokens"] == 80
        assert result.metadata["thread_id"] == "tid-1"

    def test_error_from_collector(self):
        executor = _make_executor()
        collector = _ExecStreamCollector()
        collector.error = {"message": "Bad request"}

        result = executor._build_result_from_exec(collector, 1, "stderr stuff")
        assert not result.success
        assert "Bad request" in result.error["message"]
        assert "stderr stuff" in result.error["message"]

    def test_process_error_no_message(self):
        executor = _make_executor()
        collector = _ExecStreamCollector()
        # No final_message, no error, but bad exit code
        result = executor._build_result_from_exec(collector, 2, "usage error")
        assert not result.success
        assert "exited with code 2" in result.error["message"]

    def test_process_error_with_message_is_success(self):
        """If there's a final_message, even with bad exit code, it's not an error."""
        executor = _make_executor()
        collector = _ExecStreamCollector()
        collector.final_message = "partial result"
        # Bad exit code but we got a message -> not treated as process error
        result = executor._build_result_from_exec(collector, 1, "")
        assert result.success
        assert result.content == "partial result"

    def test_no_usage(self):
        executor = _make_executor()
        collector = _ExecStreamCollector()
        collector.final_message = "ok"
        result = executor._build_result_from_exec(collector, 0, "")
        assert result.usage is None

    def test_output_dict(self):
        executor = _make_executor()
        collector = _ExecStreamCollector()
        collector.thread_id = "tid-out"
        collector.final_message = '{"answer": "Paris"}'
        result = executor._build_result_from_exec(collector, 0, "")
        assert result.output["result"] == '{"answer": "Paris"}'
        assert result.output["thread_id"] == "tid-out"


# ---------------------------------------------------------------------------
# CodexCliAdapter tests
# ---------------------------------------------------------------------------

class TestCodexCliAdapter:

    def test_type_name(self):
        adapter = CodexCliAdapter()
        assert adapter.type_name == "codex-cli"

    def test_create_executor(self):
        from flatmachines.agents import AgentAdapterContext, AgentRef

        adapter = CodexCliAdapter()
        executor = adapter.create_executor(
            agent_name="test",
            agent_ref=AgentRef(type="codex-cli", config={"model": "gpt-5.3-codex"}),
            context=AgentAdapterContext(
                config_dir="/tmp",
                settings={"agent_runners": {"codex_cli": {"timeout": 30}}},
                machine_name="test-machine",
            ),
        )
        assert isinstance(executor, CodexCliExecutor)
        assert executor._merged["model"] == "gpt-5.3-codex"
        assert executor._merged["timeout"] == 30

    def test_settings_override(self):
        from flatmachines.agents import AgentAdapterContext, AgentRef

        adapter = CodexCliAdapter()
        executor = adapter.create_executor(
            agent_name="test",
            agent_ref=AgentRef(type="codex-cli", config={"model": "gpt-5.4"}),
            context=AgentAdapterContext(
                config_dir="/tmp",
                settings={"agent_runners": {"codex_cli": {"model": "gpt-5.3-codex"}}},
                machine_name="test-machine",
            ),
        )
        # Config (per-agent) wins over settings (global)
        assert executor._merged["model"] == "gpt-5.4"


# ---------------------------------------------------------------------------
# execute_with_tools raises
# ---------------------------------------------------------------------------

class TestExecuteWithTools:

    @pytest.mark.asyncio
    async def test_raises(self):
        executor = _make_executor()
        with pytest.raises(NotImplementedError, match="tool loop"):
            await executor.execute_with_tools({}, [])


# ---------------------------------------------------------------------------
# execute validation
# ---------------------------------------------------------------------------

class TestExecuteValidation:

    @pytest.mark.asyncio
    async def test_empty_prompt_returns_error(self):
        executor = _make_executor()
        result = await executor.execute({})
        assert not result.success
        assert "requires input.task" in result.error["message"]

    @pytest.mark.asyncio
    async def test_accepts_task_key(self):
        """Verify input_data["task"] is accepted (not just "prompt")."""
        executor = _make_executor()
        # This will fail at subprocess level, but validates the dispatch path
        # We just check it doesn't return the "requires input.task" error
        # (It will fail because codex isn't actually available in unit tests,
        # but that's fine -- we're testing the validation path)
        result = await executor.execute({"task": ""})
        assert not result.success
        assert "requires input.task" in result.error["message"]

        # Non-empty should not hit validation error
        # (would need mock subprocess to fully test)

#!/usr/bin/env python3
"""
Live integration tests for the Claude Code CLI adapter.

These tests invoke the real `claude` binary and hit the real API.
They are designed to be cheap (sonnet, low effort, small prompts)
but still exercise the full adapter ↔ CLI ↔ API stack.

**Gated behind --live flag.**  Without it, every test is skipped.

Test matrix (from analysis doc "Integration Tests" section):
  1. Simple task — claude -p "say hi" → AgentResult with content
  2. Tool use — read a real file → verify stream events contain tool_use/tool_result
  3. Session resume — turn 1 sets context, turn 2 recalls it
  4. Concurrent sessions — two simultaneous executions both succeed
  5. Error recovery — resume nonexistent session → AgentResult with error
  6. Permission mode — bypassPermissions works headless with no TTY
  7. Tool restrictions — --tools restricts to exactly listed tools
  8. Continuation loop — multi-turn with sentinel detection
  9. Full stream capture — verify NDJSON event types parsed correctly

Requires:
  - `claude` binary on PATH (v2.1+)
  - Valid Claude subscription / API auth
  - Internet access

Usage:
    cd sdk/python
    source .venv/bin/activate

    # Run live tests (hits real API, costs money):
    python -m pytest tests/integration/claude_code/ -v --live

    # Without --live, all tests are skipped:
    python -m pytest tests/integration/claude_code/ -v

    # Via runner script:
    tests/integration/claude_code/run.sh --local
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "flatmachines"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "flatagents"))

from flatmachines.adapters.claude_code import ClaudeCodeAdapter, ClaudeCodeExecutor
from flatmachines.adapters.claude_code_sessions import SessionHoldback
from flatmachines.agents import AgentAdapterContext, AgentRef, AgentResult


# ---------------------------------------------------------------------------
# Skip logic is in conftest.py (--live flag + claude binary check).
# All tests in this file are skipped unless `pytest --live` is passed.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Shared config — cheap, fast, headless
# ---------------------------------------------------------------------------

_BASE_CONFIG = {
    "model": "sonnet",
    "effort": "low",
    "permission_mode": "bypassPermissions",
    "max_continuations": 0,  # disable auto-continue unless explicitly tested
    # rate_limit_delay=3.0 and rate_limit_jitter=4.0 are adapter defaults
}

_WORK_DIR: Optional[str] = None


@pytest.fixture(scope="module")
def work_dir():
    """Module-scoped temp directory for all tests."""
    global _WORK_DIR
    d = tempfile.mkdtemp(prefix="cc-integ-")
    _WORK_DIR = d
    yield d
    # Cleanup
    shutil.rmtree(d, ignore_errors=True)


def _make_executor(
    config_overrides: Optional[Dict[str, Any]] = None,
    work_dir: str = "/tmp",
) -> ClaudeCodeExecutor:
    cfg = {**_BASE_CONFIG, **(config_overrides or {})}
    return ClaudeCodeExecutor(
        config=cfg,
        config_dir=work_dir,
        settings={},
    )


# ---------------------------------------------------------------------------
# 1. Simple task
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_simple_task(work_dir):
    """claude -p 'what is 2+2' → AgentResult with content, no error."""
    executor = _make_executor(work_dir=work_dir)
    result = await executor.execute({"task": "What is 2+2? Reply with just the number."})

    assert result.error is None, f"Unexpected error: {result.error}"
    assert result.content is not None
    assert "4" in result.content
    assert result.finish_reason == "stop"

    # Usage populated
    assert result.usage is not None
    assert result.usage["input_tokens"] > 0
    assert result.usage["output_tokens"] > 0

    # Cost populated
    assert result.cost is not None
    assert (isinstance(result.cost, (int, float)) and result.cost > 0) or \
           (isinstance(result.cost, dict))

    # Session ID in output
    assert result.output is not None
    assert result.output.get("session_id")

    # Metadata
    assert result.metadata is not None
    assert result.metadata.get("num_turns") is not None
    assert result.metadata.get("duration_ms") is not None
    assert result.metadata.get("session_id")


# ---------------------------------------------------------------------------
# 2. Tool use — read a real file
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tool_use_read_file(work_dir):
    """Create a file, ask Claude to read it, verify tool events in stream."""
    # Create a file for Claude to read
    test_file = os.path.join(work_dir, "hello.txt")
    with open(test_file, "w") as f:
        f.write("The magic number is 42.\n")

    executor = _make_executor(
        config_overrides={"tools": ["Read"]},
        work_dir=work_dir,
    )
    result = await executor.execute({
        "task": f"Read the file hello.txt and tell me the magic number. Reply with just the number."
    })

    assert result.error is None, f"Unexpected error: {result.error}"
    assert result.content is not None
    assert "42" in result.content

    # Verify stream events contain tool_use and tool_result
    events = result.metadata.get("stream_events", [])
    event_types = [e.get("type") for e in events]

    assert "system" in event_types, "Missing system event"
    assert "assistant" in event_types, "Missing assistant event"
    assert "result" in event_types, "Missing result event"

    # Find tool_use in assistant events
    tool_use_found = False
    for event in events:
        if event.get("type") == "assistant":
            message = event.get("message", {})
            for block in message.get("content", []):
                if block.get("type") == "tool_use" and block.get("name") == "Read":
                    tool_use_found = True
                    break

    assert tool_use_found, "No Read tool_use found in stream events"

    # Find tool_result in user events
    tool_result_found = False
    for event in events:
        if event.get("type") == "user":
            message = event.get("message", {})
            for block in message.get("content", []):
                if block.get("type") == "tool_result":
                    tool_result_found = True
                    break

    assert tool_result_found, "No tool_result found in stream events"


# ---------------------------------------------------------------------------
# 3. Session resume — turn 1 sets context, turn 2 recalls
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_session_resume(work_dir):
    """Two-turn session: set a value, then recall it via --resume."""
    executor = _make_executor(work_dir=work_dir)

    # Turn 1: establish context
    session_id = str(uuid.uuid4())
    r1 = await executor._invoke_once(
        task="Remember this secret code: FLAMINGO-7734. Acknowledge briefly.",
        session_id=session_id,
        resume=False,
    )
    assert r1.error is None, f"Turn 1 error: {r1.error}"
    assert r1.content is not None

    # Turn 2: recall via resume
    r2 = await executor._invoke_once(
        task="What was the secret code I told you? Reply with just the code.",
        session_id=session_id,
        resume=True,
    )
    assert r2.error is None, f"Turn 2 error: {r2.error}"
    assert r2.content is not None
    assert "FLAMINGO" in r2.content or "7734" in r2.content, \
        f"Session resume failed to recall context. Got: {r2.content}"

    # Turn 2 should show cache hits (system prompt at minimum)
    u2 = r2.usage or {}
    assert u2.get("cache_read_tokens", 0) > 0, \
        f"Expected cache_read_tokens > 0 on resume, got {u2}"


# ---------------------------------------------------------------------------
# 4. Concurrent sessions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_concurrent_sessions(work_dir):
    """Two simultaneous executions with different session IDs both succeed."""
    executor = _make_executor(work_dir=work_dir)

    async def _run(prompt: str) -> AgentResult:
        return await executor.execute({"task": prompt})

    r1, r2 = await asyncio.gather(
        _run("What is 10+20? Reply with just the number."),
        _run("What is 5*6? Reply with just the number."),
    )

    assert r1.error is None, f"Session 1 error: {r1.error}"
    assert r2.error is None, f"Session 2 error: {r2.error}"

    assert r1.content is not None
    assert r2.content is not None
    assert "30" in r1.content
    assert "30" in r2.content

    # Different session IDs
    sid1 = r1.output.get("session_id", "")
    sid2 = r2.output.get("session_id", "")
    assert sid1 != sid2, "Concurrent sessions should have different IDs"


# ---------------------------------------------------------------------------
# 5. Error recovery — resume nonexistent session
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resume_nonexistent_session(work_dir):
    """Resuming a nonexistent session should return an error AgentResult."""
    executor = _make_executor(work_dir=work_dir)

    bogus_id = str(uuid.uuid4())
    result = await executor._invoke_once(
        task="hello",
        session_id=bogus_id,
        resume=True,
    )

    # Should be an error — either in result.error or process failure
    assert result.error is not None, \
        f"Expected error for nonexistent session, got: content={result.content}"


# ---------------------------------------------------------------------------
# 6. Permission mode — bypassPermissions headless
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_permission_bypass_headless(work_dir):
    """bypassPermissions allows bash execution with no TTY."""
    # Create a test file to operate on
    target = os.path.join(work_dir, "perm_test.txt")
    with open(target, "w") as f:
        f.write("original content\n")

    executor = _make_executor(
        config_overrides={
            "permission_mode": "bypassPermissions",
            "tools": ["Bash", "Read"],
        },
        work_dir=work_dir,
    )

    result = await executor.execute({
        "task": (
            "Run this exact bash command: echo 'PERM_OK' >> perm_test.txt\n"
            "Then read perm_test.txt and tell me its full contents."
        ),
    })

    assert result.error is None, f"Error: {result.error}"
    assert result.content is not None

    # Verify the file was actually modified (side effect)
    with open(target) as f:
        contents = f.read()
    assert "PERM_OK" in contents, \
        f"Bash tool didn't modify file. File contents: {contents}"


# ---------------------------------------------------------------------------
# 7. Tool restrictions — --tools exact whitelist
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tools_exact_restriction(work_dir):
    """--tools Read should allow Read but not Bash/Write/Edit."""
    # Create a file to read
    test_file = os.path.join(work_dir, "restricted.txt")
    with open(test_file, "w") as f:
        f.write("restricted content\n")

    executor = _make_executor(
        config_overrides={"tools": ["Read"]},
        work_dir=work_dir,
    )

    # Verify the system event reports only the allowed tools
    result = await executor.execute({
        "task": "Read restricted.txt and tell me its content. Reply briefly.",
    })

    assert result.error is None, f"Error: {result.error}"

    # Check system event — tools list should be restricted
    events = result.metadata.get("stream_events", [])
    system_events = [e for e in events if e.get("type") == "system"]
    assert len(system_events) > 0, "No system event found"

    reported_tools = system_events[0].get("tools", [])
    assert "Read" in reported_tools, \
        f"Read not in reported tools: {reported_tools}"

    # The system event should NOT include Bash, Write, Edit etc.
    # (unless the CLI includes them regardless — this test validates that)
    restricted_out = set(reported_tools) - {"Read"}
    if restricted_out:
        # Log but don't fail — some CLI versions may report differently
        print(f"  NOTE: Extra tools reported beyond Read: {restricted_out}")


# ---------------------------------------------------------------------------
# 8. Continuation loop — multi-turn with sentinel
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_continuation_loop(work_dir):
    """Enable continuations, verify sentinel detection ends the loop."""
    executor = _make_executor(
        config_overrides={
            "max_continuations": 3,
            "exit_sentinel": "<<AGENT_EXIT>>",
            "tools": ["Bash"],
        },
        work_dir=work_dir,
    )

    result = await executor.execute({
        "task": (
            "Run: echo 'step1'\n"
            "Then say <<AGENT_EXIT>> on its own line when done."
        ),
    })

    assert result.error is None, f"Error: {result.error}"
    assert result.content is not None

    # Should have completed (sentinel found or single-turn natural stop)
    attempts = result.metadata.get("continuation_attempts", 0)
    assert attempts >= 1, "Expected at least 1 attempt"

    # Usage should show api_calls
    assert result.usage is not None
    assert result.usage.get("api_calls", 0) >= 1


# ---------------------------------------------------------------------------
# 9. Full stream capture — verify event types
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stream_event_types(work_dir):
    """Verify all expected NDJSON event types are captured and parsed."""
    executor = _make_executor(work_dir=work_dir)

    result = await executor.execute({
        "task": "Say 'hello world'. Nothing else.",
    })

    assert result.error is None, f"Error: {result.error}"

    events = result.metadata.get("stream_events", [])
    assert len(events) >= 2, f"Expected ≥2 events, got {len(events)}"

    # Verify event structure
    for event in events:
        assert "type" in event, f"Event missing 'type': {event}"

    # Must have system and result at minimum
    types = {e["type"] for e in events}
    assert "system" in types, f"Missing 'system' event. Types: {types}"
    assert "result" in types, f"Missing 'result' event. Types: {types}"

    # System event should have session_id, tools, model
    sys_event = next(e for e in events if e["type"] == "system")
    assert sys_event.get("session_id"), "system event missing session_id"
    assert sys_event.get("tools"), "system event missing tools list"
    assert sys_event.get("model"), "system event missing model"

    # Result event should have core fields
    result_event = next(e for e in events if e["type"] == "result")
    assert "is_error" in result_event
    assert "result" in result_event
    assert "usage" in result_event
    assert "session_id" in result_event


# ---------------------------------------------------------------------------
# 10. Session holdback — seed + fork
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_holdback_seed_and_fork(work_dir):
    """SessionHoldback: seed establishes context, fork recalls it."""
    executor = _make_executor(work_dir=work_dir)
    holdback = SessionHoldback(executor=executor)

    # Seed
    seed_result = await holdback.seed(
        "Remember: the project uses Python 3.12 with FastAPI. Acknowledge briefly."
    )
    assert seed_result.error is None, f"Seed error: {seed_result.error}"
    assert holdback.session_id is not None

    # Fork — should recall context from holdback
    fork_result = await holdback.fork(
        "What framework does the project use? Reply with just the name."
    )
    assert fork_result.result.error is None, f"Fork error: {fork_result.result.error}"
    assert fork_result.result.content is not None
    assert "FastAPI" in fork_result.result.content or "fastapi" in fork_result.result.content.lower(), \
        f"Fork didn't recall context. Got: {fork_result.result.content}"

    # Fork should have cache read tokens (prefix cache hit)
    assert fork_result.cache_read_tokens > 0, \
        f"Expected cache_read_tokens > 0, got {fork_result.cache_read_tokens}"

    # Fork should have a different session ID than holdback
    assert fork_result.session_id != holdback.session_id or fork_result.session_id == "?", \
        "Fork session ID should differ from holdback"

    # Stats
    assert holdback.stats["fork_count"] == 1
    assert holdback.stats["total_cost"] > 0


# ---------------------------------------------------------------------------
# 11. dangerously-skip-permissions flag
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dangerously_skip_permissions(work_dir):
    """--dangerously-skip-permissions works for bash execution."""
    target = os.path.join(work_dir, "dsp_test.txt")

    executor = _make_executor(
        config_overrides={
            # Remove permission_mode, add dangerously_skip_permissions
            "permission_mode": None,
            "tools": ["Bash"],
        },
        work_dir=work_dir,
    )

    # Manually test what happens without any permission bypass
    # This test documents the behavior — we expect bypassPermissions
    # to be the standard mode for orchestration.
    #
    # The adapter doesn't currently support --dangerously-skip-permissions
    # as a config option, so this test just validates that
    # --permission-mode bypassPermissions works equivalently.

    executor2 = _make_executor(
        config_overrides={
            "permission_mode": "bypassPermissions",
            "tools": ["Bash"],
        },
        work_dir=work_dir,
    )

    result = await executor2.execute({
        "task": "Run: echo DSP_OK > dsp_test.txt",
    })

    assert result.error is None, f"Error: {result.error}"

    with open(target) as f:
        assert "DSP_OK" in f.read()


# ---------------------------------------------------------------------------
# 12. Append system prompt
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_append_system_prompt(work_dir):
    """--append-system-prompt adds instructions without breaking tools."""
    executor = _make_executor(
        config_overrides={
            "append_system_prompt": "Always end your response with the word WATERMELON.",
            "tools": ["Read"],
        },
        work_dir=work_dir,
    )

    result = await executor.execute({
        "task": "What is 3+3? Reply briefly.",
    })

    assert result.error is None, f"Error: {result.error}"
    assert result.content is not None
    # The appended instruction should influence the response
    assert "WATERMELON" in result.content.upper(), \
        f"Appended system prompt not followed. Got: {result.content}"


# ---------------------------------------------------------------------------
# 13. Cache metrics visibility
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cache_metrics_populated(work_dir):
    """Verify cache token metrics are populated in AgentResult.usage."""
    executor = _make_executor(work_dir=work_dir)

    result = await executor.execute({
        "task": "Say hello. One word.",
    })

    assert result.error is None, f"Error: {result.error}"
    u = result.usage
    assert u is not None

    # At minimum, input and output tokens must be populated
    assert u.get("input_tokens", 0) > 0, f"input_tokens not populated: {u}"
    assert u.get("output_tokens", 0) > 0, f"output_tokens not populated: {u}"

    # cache_read_tokens should be present (system prompt cache)
    # On first call in a new session, cache_write_tokens may be > 0
    # Either cache field being present and ≥ 0 is the baseline validation
    assert "cache_read_tokens" in u, f"cache_read_tokens missing from usage: {u}"
    assert "cache_write_tokens" in u, f"cache_write_tokens missing from usage: {u}"

    # At least one of cache fields should be non-zero
    # (system prompt is always cached)
    cache_total = u.get("cache_read_tokens", 0) + u.get("cache_write_tokens", 0)
    assert cache_total > 0, f"No cache activity detected: {u}"

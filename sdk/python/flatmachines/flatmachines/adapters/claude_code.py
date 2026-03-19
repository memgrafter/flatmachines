"""Claude Code CLI adapter for FlatMachines.

Drives the Claude Code CLI (`claude -p`) as a subprocess, streaming NDJSON
events and mapping the result to AgentResult.  Claude Code owns its own
tool loop — this adapter does NOT implement execute_with_tools().

Design rules:
  - No data truncation anywhere.  Stream events, result text, tool outputs,
    stderr — all captured in full.
  - No --json-schema.  Use a downstream FlatAgent extractor if needed.
  - --tools (exact whitelist), never --allowed-tools.

Config keys (agent config or global settings.agent_runners.claude_code):
  model               Model alias or name (default: opus)
  effort              low | medium | high | max (default: high)
  permission_mode     default | acceptEdits | bypassPermissions | dontAsk | plan | auto
  dangerously_skip_permissions  bool — bypass all checks (sandboxed envs only)
  system_prompt       Replace default system prompt entirely
  append_system_prompt  Append to default system prompt (preferred)
  tools               List of exact tool names (e.g. ["Bash", "Read", "Edit"])
  max_budget_usd      Cost cap for the session (0 = disabled)
  add_dirs            List of additional directories for tool access
  claude_bin          Path to claude binary (default: "claude")
  working_dir         Working directory for subprocess (supports Jinja2)
  timeout             Subprocess timeout in seconds (0 = no timeout)
  max_continuations   Max continuation attempts (default: 100, 0 = disabled)
  exit_sentinel       Sentinel text to detect completion (default: <<AGENT_EXIT>>)
  continuation_prompt  Prompt for continuation turns
  mcp_config          Path to MCP server configuration JSON file
  rate_limit_delay   Base seconds between CLI calls (default 0 = disabled)
  rate_limit_jitter  ±seconds jitter added to delay (default 0)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import uuid
from typing import Any, Dict, List, Optional

from flatagents.monitoring import AgentMonitor

from ..agents import (
    AgentAdapter,
    AgentAdapterContext,
    AgentExecutor,
    AgentRef,
    AgentResult,
)
from .call_throttle import CallThrottle, throttle_from_config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

_DEFAULT_MODEL = "opus"
_DEFAULT_EFFORT = "high"
_DEFAULT_EXIT_SENTINEL = "<<AGENT_EXIT>>"
_DEFAULT_CONTINUATION_PROMPT = (
    "Continue working. When fully done, emit <<AGENT_EXIT>> on its own line."
)
_DEFAULT_MAX_CONTINUATIONS = 100
_DEFAULT_RATE_LIMIT_DELAY = 3.0   # seconds between CLI calls
_DEFAULT_RATE_LIMIT_JITTER = 4.0  # ±4s → uniform(0, 8) added → [3, 11]s total
_SIGTERM_GRACE_SECONDS = 5


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _map_stop_reason(stop_reason: Optional[str]) -> Optional[str]:
    """Map Claude Code stop_reason to AgentResult finish_reason."""
    if stop_reason is None:
        return None
    mapping = {
        "end_turn": "stop",
        "max_tokens": "length",
        "stop_sequence": "stop",
    }
    return mapping.get(stop_reason, stop_reason)


def _build_error(event: Dict[str, Any], stderr: str = "") -> Dict[str, Any]:
    """Build an AgentError dict from a CLI result event."""
    message = event.get("result", "Unknown error")
    if stderr:
        message = f"{message}\nstderr: {stderr}"
    return {
        "code": "server_error",
        "type": "ClaudeCodeError",
        "message": message,
        "retryable": False,
    }


# ---------------------------------------------------------------------------
# Rate limit mapping
# ---------------------------------------------------------------------------

def _build_rate_limit_from_events(
    rl_events: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Build a normalised RateLimitState from Claude Code rate_limit_event info.

    Returns None if no rate limit events were observed.
    """
    if not rl_events:
        return None

    # Use the last (most recent) event
    info = rl_events[-1]

    windows: List[Dict[str, Any]] = []

    # Map known fields to RateLimitWindow dicts
    for resource in ("requests", "tokens"):
        remaining = info.get(f"{resource}_remaining")
        limit = info.get(f"{resource}_limit")
        if remaining is not None or limit is not None:
            window: Dict[str, Any] = {
                "name": resource,
                "resource": resource,
            }
            if remaining is not None:
                window["remaining"] = remaining
            if limit is not None:
                window["limit"] = limit
            windows.append(window)

    limited = any(w.get("remaining") == 0 for w in windows)
    retry_after = info.get("retry_after_seconds")

    state: Dict[str, Any] = {"limited": limited}
    if retry_after is not None:
        state["retry_after"] = retry_after
    if windows:
        state["windows"] = windows

    return state


# ---------------------------------------------------------------------------
# Stream event collector
# ---------------------------------------------------------------------------

class _StreamCollector:
    """Collects NDJSON stream events and tracks tool_use blocks for
    matching against subsequent tool_result blocks.

    Also detects StructuredOutput tool_use blocks and rate_limit_event
    data for surfacing to AgentResult.
    """

    def __init__(self) -> None:
        self.events: List[Dict[str, Any]] = []
        self.result_event: Optional[Dict[str, Any]] = None
        self.session_id: Optional[str] = None
        self.system_meta: Optional[Dict[str, Any]] = None
        # Map tool_use_id -> {name, input} for matching results
        self._pending_tools: Dict[str, Dict[str, Any]] = {}
        # Ordered tool call / result lists for hook integration
        self.ordered_tool_calls: List[Dict[str, Any]] = []
        self.ordered_tool_results: List[Dict[str, Any]] = []
        # StructuredOutput detection
        self.structured_output: Optional[Dict[str, Any]] = None
        # Rate limit info from rate_limit_event(s)
        self.rate_limit_events: List[Dict[str, Any]] = []

    def ingest(self, event: Dict[str, Any]) -> None:
        """Ingest a single parsed NDJSON event."""
        etype = event.get("type")

        if etype == "system":
            self.session_id = event.get("session_id")
            self.system_meta = event
            self.events.append(event)

        elif etype == "assistant":
            # Track session_id from assistant events too
            if event.get("session_id"):
                self.session_id = event["session_id"]

            # Index tool_use blocks for later matching
            message = event.get("message", {})
            for block in message.get("content", []):
                if block.get("type") == "tool_use":
                    tool_id = block.get("id", "")
                    tool_name = block.get("name", "")
                    tool_input = block.get("input", {})
                    self._pending_tools[tool_id] = {
                        "name": tool_name,
                        "input": tool_input,
                    }
                    self.ordered_tool_calls.append({
                        "id": tool_id,
                        "name": tool_name,
                        "arguments": tool_input,
                    })
                    # Detect StructuredOutput tool_use
                    if tool_name == "StructuredOutput":
                        self.structured_output = tool_input
            self.events.append(event)

        elif etype == "user":
            # Extract tool results and add to ordered list
            message = event.get("message", {})
            for block in message.get("content", []):
                if block.get("type") == "tool_result":
                    tool_id = block.get("tool_use_id", "")
                    pending = self._pending_tools.get(tool_id, {})
                    self.ordered_tool_results.append({
                        "tool_call_id": tool_id,
                        "name": pending.get("name", ""),
                        "arguments": pending.get("input", {}),
                        "content": block.get("content", ""),
                        "is_error": block.get("is_error", False),
                    })
            self.events.append(event)

        elif etype == "result":
            self.result_event = event
            # Also capture session_id from result
            if event.get("session_id"):
                self.session_id = event["session_id"]
            self.events.append(event)

        elif etype == "rate_limit_event":
            rl_info = event.get("rate_limit_info", {})
            logger.info("Claude Code rate limit event: %s", rl_info)
            self.rate_limit_events.append(rl_info)
            self.events.append(event)

        else:
            # Unknown event type — keep it, never discard
            self.events.append(event)

    def get_tool_calls_from_assistant(self, event: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract tool_calls list from an assistant event."""
        calls = []
        message = event.get("message", {})
        for block in message.get("content", []):
            if block.get("type") == "tool_use":
                calls.append({
                    "id": block.get("id", ""),
                    "name": block.get("name", ""),
                    "arguments": block.get("input", {}),
                })
        return calls

    def get_tool_results_from_user(self, event: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract tool results from a user event, matched to pending tool_use."""
        results = []
        message = event.get("message", {})
        for block in message.get("content", []):
            if block.get("type") == "tool_result":
                tool_id = block.get("tool_use_id", "")
                pending = self._pending_tools.get(tool_id, {})
                results.append({
                    "tool_call_id": tool_id,
                    "name": pending.get("name", ""),
                    "arguments": pending.get("input", {}),
                    "content": block.get("content", ""),
                    "is_error": block.get("is_error", False),
                })
        return results


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------

class ClaudeCodeExecutor(AgentExecutor):
    """Executor that drives Claude Code CLI as a subprocess."""

    def __init__(
        self,
        config: Dict[str, Any],
        config_dir: str,
        settings: Dict[str, Any],
        throttle: Optional[CallThrottle] = None,
    ) -> None:
        self._config = config
        self._config_dir = config_dir
        self._settings = settings

        # Merge settings (global) under config (per-agent), config wins
        self._merged: Dict[str, Any] = {**settings, **config}

        # Rate limiter — injected or built from config (defaults on)
        if throttle is not None:
            self._throttle = throttle
        else:
            self._throttle = CallThrottle(
                delay=float(self._merged.get(
                    "rate_limit_delay", _DEFAULT_RATE_LIMIT_DELAY)),
                jitter=float(self._merged.get(
                    "rate_limit_jitter", _DEFAULT_RATE_LIMIT_JITTER)),
            )

        # Running subprocess reference for cancellation
        self._process: Optional[asyncio.subprocess.Process] = None

    @property
    def metadata(self) -> Dict[str, Any]:
        return {}

    # -- Public interface ---------------------------------------------------

    async def execute(
        self,
        input_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> AgentResult:
        """Execute a Claude Code CLI invocation with optional continue loop."""
        task = input_data.get("task") or input_data.get("prompt", "")
        if not task:
            return AgentResult(
                error={
                    "code": "invalid_request",
                    "type": "ValueError",
                    "message": "claude-code adapter requires input.task or input.prompt",
                    "retryable": False,
                },
                finish_reason="error",
            )

        # Session mode
        resume_session = input_data.get("resume_session")
        if resume_session:
            session_id = resume_session
            resume = True
        else:
            session_id = str(uuid.uuid4())
            resume = False

        # Continue-until-done config
        cfg = self._merged
        max_continuations = cfg.get("max_continuations", _DEFAULT_MAX_CONTINUATIONS)
        exit_sentinel = cfg.get("exit_sentinel", _DEFAULT_EXIT_SENTINEL)
        continuation_prompt = cfg.get("continuation_prompt", _DEFAULT_CONTINUATION_PROMPT)

        # Aggregators across continuations
        all_events: List[Dict[str, Any]] = []
        total_cost = 0.0
        total_input_tokens = 0
        total_output_tokens = 0
        total_cache_read = 0
        total_cache_write = 0
        last_result: Optional[AgentResult] = None

        attempt = 0
        while True:
            result = await self._invoke_once(
                task=task,
                session_id=session_id,
                resume=resume,
                context=context,
            )
            attempt += 1

            # Aggregate metrics
            if result.usage:
                total_input_tokens += result.usage.get("input_tokens", 0)
                total_output_tokens += result.usage.get("output_tokens", 0)
                total_cache_read += result.usage.get("cache_read_tokens", 0)
                total_cache_write += result.usage.get("cache_write_tokens", 0)
            if result.cost is not None:
                if isinstance(result.cost, (int, float)):
                    total_cost += float(result.cost)
                elif isinstance(result.cost, dict):
                    total_cost += float(result.cost.get("total", 0))

            # Collect stream events
            if result.metadata and result.metadata.get("stream_events"):
                all_events.extend(result.metadata["stream_events"])

            last_result = result

            # Error — stop immediately
            if result.error:
                break

            result_text = result.content or ""

            # Sentinel found — done
            if exit_sentinel in result_text:
                break

            # Natural completion: stop with single turn, no tool use
            if (
                result.finish_reason == "stop"
                and result.metadata
                and result.metadata.get("num_turns", 0) <= 1
            ):
                break

            # Check continuation limits
            if max_continuations == 0:
                break
            if max_continuations > 0 and attempt > max_continuations:
                break

            # Continue — resume the session
            task = continuation_prompt
            resume = True

        # Build final aggregated result
        if last_result is None:
            return AgentResult(
                error={
                    "code": "server_error",
                    "type": "ClaudeCodeError",
                    "message": "No result from Claude Code",
                    "retryable": False,
                },
                finish_reason="error",
            )

        # Replace metrics with aggregated totals
        final = AgentResult(
            output=last_result.output,
            content=last_result.content,
            raw=last_result.raw,
            usage={
                "input_tokens": total_input_tokens,
                "output_tokens": total_output_tokens,
                "cache_read_tokens": total_cache_read,
                "cache_write_tokens": total_cache_write,
                "api_calls": attempt,
            },
            cost=total_cost if total_cost > 0 else last_result.cost,
            finish_reason=last_result.finish_reason,
            error=last_result.error,
            metadata={
                **(last_result.metadata or {}),
                "stream_events": all_events,
                "continuation_attempts": attempt,
            },
            provider_data=last_result.provider_data,
        )

        # Log aggregated summary when continuations were used
        if attempt > 1:
            logger.info(
                "Claude Code continuation complete: attempts=%d input=%d output=%d "
                "cache_read=%d cache_write=%d cost=%.4f",
                attempt, total_input_tokens, total_output_tokens,
                total_cache_read, total_cache_write, total_cost,
            )

        return final

    async def execute_with_tools(
        self,
        input_data: Dict[str, Any],
        tools: List[Dict[str, Any]],
        messages: Optional[List[Dict[str, Any]]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> AgentResult:
        """Not supported — Claude Code owns its tool loop."""
        raise NotImplementedError(
            "Claude Code CLI adapter does not support machine-driven tool loops. "
            "Remove tool_loop from the state config."
        )

    # -- Cancellation -------------------------------------------------------

    async def cancel(self) -> bool:
        """Cancel the running subprocess with SIGTERM → grace → SIGKILL.

        Returns True if a process was signalled, False if nothing was running.
        """
        proc = self._process
        if proc is None:
            return False

        logger.info("Claude Code cancel: sending SIGTERM to pid %s", proc.pid)
        try:
            proc.send_signal(signal.SIGTERM)
        except ProcessLookupError:
            return False

        try:
            await asyncio.wait_for(proc.wait(), timeout=_SIGTERM_GRACE_SECONDS)
        except asyncio.TimeoutError:
            logger.warning(
                "Claude Code cancel: SIGTERM grace expired, sending SIGKILL to pid %s",
                proc.pid,
            )
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            await proc.wait()

        return True

    # -- Metrics helper -----------------------------------------------------

    @staticmethod
    def _populate_monitor(monitor: AgentMonitor, result: AgentResult) -> None:
        """Populate an AgentMonitor's metrics dict from an AgentResult."""
        if result.usage:
            inp = result.usage.get("input_tokens", 0)
            out = result.usage.get("output_tokens", 0)
            monitor.metrics["input_tokens"] = inp
            monitor.metrics["output_tokens"] = out
            monitor.metrics["tokens"] = inp + out
            cr = result.usage.get("cache_read_tokens", 0)
            cw = result.usage.get("cache_write_tokens", 0)
            if cr:
                monitor.metrics["cache_read_tokens"] = cr
            if cw:
                monitor.metrics["cache_write_tokens"] = cw
        if result.cost is not None:
            cost_val = (
                float(result.cost)
                if isinstance(result.cost, (int, float))
                else float(result.cost.get("total", 0))
                if isinstance(result.cost, dict)
                else 0
            )
            if cost_val:
                monitor.metrics["cost"] = cost_val
        if result.error:
            monitor.metrics["error"] = True
            monitor.metrics["error_type"] = result.error.get("type", "unknown")

    # -- Single invocation --------------------------------------------------

    async def _invoke_once(
        self,
        task: str,
        session_id: str,
        resume: bool,
        context: Optional[Dict[str, Any]] = None,
        fork_session: bool = False,
    ) -> AgentResult:
        """Run a single claude -p invocation and return AgentResult.

        Args:
            task: Prompt text
            session_id: Session UUID (new or existing)
            resume: Use --resume instead of --session-id
            context: Optional context for working_dir resolution
            fork_session: Add --fork-session (new ID, preserves history)
        """
        # Rate-limit gate (serialised — concurrent callers stagger)
        waited = await self._throttle.wait()
        if waited > 0:
            logger.info("Claude Code throttle: waited %.3fs before call", waited)

        cfg = self._merged
        model = cfg.get("model", _DEFAULT_MODEL)
        agent_id = f"claude-code/{model}"
        args = self._build_args(task, session_id, resume, fork_session=fork_session)

        # Resolve working directory
        working_dir = cfg.get("working_dir")
        if working_dir and context:
            # Render Jinja2 template if present
            if "{{" in str(working_dir):
                try:
                    from jinja2 import Template
                    working_dir = Template(str(working_dir)).render(context=context)
                except Exception:
                    pass
        if working_dir:
            working_dir = os.path.abspath(working_dir)
        else:
            working_dir = self._config_dir

        timeout = cfg.get("timeout", 0)

        logger.info(
            "Claude Code invoke: session=%s resume=%s timeout=%s cwd=%s",
            session_id, resume, timeout, working_dir,
        )
        logger.debug("Claude Code args: %s", args)

        with AgentMonitor(agent_id, extra_attributes={
            "adapter": "claude-code",
            "session_id": session_id,
            "resume": str(resume),
        }) as monitor:
            # Spawn subprocess
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=working_dir,
                env=os.environ.copy(),
            )
            self._process = proc

            collector = _StreamCollector()
            stderr_data = b""

            try:
                if timeout and timeout > 0:
                    stderr_data = await asyncio.wait_for(
                        self._read_stream(proc, collector),
                        timeout=timeout,
                    )
                else:
                    stderr_data = await self._read_stream(proc, collector)
            except asyncio.TimeoutError:
                # SIGTERM -> grace period -> SIGKILL
                try:
                    proc.send_signal(signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.wait_for(proc.wait(), timeout=_SIGTERM_GRACE_SECONDS)
                except asyncio.TimeoutError:
                    try:
                        proc.kill()
                    except ProcessLookupError:
                        pass
                    await proc.wait()
                raise TimeoutError(
                    f"Claude Code subprocess timed out after {timeout}s "
                    f"(session={session_id})"
                )

            # Wait for process exit
            await proc.wait()
            self._process = None

            stderr_text = stderr_data.decode("utf-8", errors="replace")

            # Check for process-level failure with no result event
            if proc.returncode != 0 and collector.result_event is None:
                result = AgentResult(
                    error={
                        "code": "server_error",
                        "type": "ClaudeCodeProcessError",
                        "message": f"claude exited with code {proc.returncode}\nstderr: {stderr_text}",
                        "retryable": proc.returncode in (429, 500, 502, 503, 504),
                    },
                    finish_reason="error",
                    metadata={
                        "session_id": collector.session_id or session_id,
                        "stream_events": collector.events,
                        "stderr": stderr_text,
                    },
                )
                self._populate_monitor(monitor, result)
                return result

            # No result event but process exited 0
            if collector.result_event is None:
                result = AgentResult(
                    error={
                        "code": "server_error",
                        "type": "ClaudeCodeError",
                        "message": f"No result event received from Claude Code\nstderr: {stderr_text}",
                        "retryable": False,
                    },
                    finish_reason="error",
                    metadata={
                        "session_id": collector.session_id or session_id,
                        "stream_events": collector.events,
                        "stderr": stderr_text,
                    },
                )
                self._populate_monitor(monitor, result)
                return result

            result = self._build_result(collector, session_id, stderr_text)
            self._populate_monitor(monitor, result)
            return result

    async def _read_stream(
        self,
        proc: asyncio.subprocess.Process,
        collector: _StreamCollector,
    ) -> bytes:
        """Read NDJSON from stdout, collect stderr.  Returns stderr bytes."""
        assert proc.stdout is not None
        assert proc.stderr is not None

        stderr_chunks: List[bytes] = []

        async def _drain_stderr():
            assert proc.stderr is not None
            while True:
                chunk = await proc.stderr.read(65536)
                if not chunk:
                    break
                stderr_chunks.append(chunk)

        stderr_task = asyncio.create_task(_drain_stderr())

        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            line_str = line.decode("utf-8", errors="replace").rstrip("\n\r")
            if not line_str:
                continue
            try:
                event = json.loads(line_str)
                collector.ingest(event)
            except json.JSONDecodeError:
                logger.warning("Claude Code: unparseable NDJSON line: %s", line_str)

        await stderr_task
        return b"".join(stderr_chunks)

    # -- Arg builder --------------------------------------------------------

    def _build_args(
        self,
        task: str,
        session_id: str,
        resume: bool,
        fork_session: bool = False,
    ) -> List[str]:
        """Build CLI argument list.

        Args:
            task: Prompt text
            session_id: Session UUID
            resume: Use --resume instead of --session-id
            fork_session: Add --fork-session (requires resume=True)
        """
        cfg = self._merged
        claude_bin = cfg.get("claude_bin", "claude")

        args = [claude_bin, "-p", task, "--output-format", "stream-json", "--verbose"]

        if resume:
            args += ["--resume", session_id]
            if fork_session:
                args += ["--fork-session"]
        else:
            args += ["--session-id", session_id]

        # Model defaults to opus
        model = cfg.get("model", _DEFAULT_MODEL)
        args += ["--model", model]

        permission_mode = cfg.get("permission_mode")
        if permission_mode:
            args += ["--permission-mode", permission_mode]

        # Dangerously skip permissions (sandboxed environments only)
        if cfg.get("dangerously_skip_permissions"):
            args += ["--dangerously-skip-permissions"]

        # Additional directories for tool access
        add_dirs = cfg.get("add_dirs")
        if add_dirs:
            for d in add_dirs:
                args += ["--add-dir", d]

        # Prompt control (mutually exclusive)
        system_prompt = cfg.get("system_prompt")
        append_system_prompt = cfg.get("append_system_prompt")
        if system_prompt:
            args += ["--system-prompt", system_prompt]
        elif append_system_prompt:
            args += ["--append-system-prompt", append_system_prompt]

        # Tool control (exact whitelist)
        tools = cfg.get("tools")
        if tools:
            args += ["--tools"] + list(tools)

        # MCP server configuration
        mcp_config = cfg.get("mcp_config")
        if mcp_config:
            args += ["--mcp-config", str(mcp_config)]

        # Budget (0 = disabled)
        max_budget = cfg.get("max_budget_usd", 0)
        if max_budget and float(max_budget) > 0:
            args += ["--max-budget-usd", str(max_budget)]

        # Effort defaults to high
        effort = cfg.get("effort", _DEFAULT_EFFORT)
        args += ["--effort", effort]

        return args

    # -- Result builder -----------------------------------------------------

    def _build_result(
        self,
        collector: _StreamCollector,
        session_id: str,
        stderr_text: str,
    ) -> AgentResult:
        """Build AgentResult from collected stream events."""
        event = collector.result_event
        assert event is not None

        resolved_session = collector.session_id or event.get("session_id") or session_id

        # Usage
        usage_raw = event.get("usage", {})
        usage = {
            "input_tokens": usage_raw.get("input_tokens", 0),
            "output_tokens": usage_raw.get("output_tokens", 0),
            "cache_read_tokens": usage_raw.get("cache_read_input_tokens", 0),
            "cache_write_tokens": usage_raw.get("cache_creation_input_tokens", 0),
        }

        # Error check
        error = None
        if event.get("is_error"):
            error = _build_error(event, stderr_text)

        # Output: prefer StructuredOutput if detected, otherwise text result
        if collector.structured_output is not None:
            output = {
                **collector.structured_output,
                "session_id": resolved_session,
                "_raw_result": event.get("result"),
            }
        else:
            output = {
                "result": event.get("result"),
                "session_id": resolved_session,
            }

        # Rate limit state from rate_limit_event(s)
        rate_limit = _build_rate_limit_from_events(collector.rate_limit_events)

        return AgentResult(
            output=output,
            content=event.get("result"),
            raw=event,
            usage=usage,
            cost=event.get("total_cost_usd"),
            finish_reason=_map_stop_reason(event.get("stop_reason")),
            error=error,
            rate_limit=rate_limit,
            tool_calls=collector.ordered_tool_calls or None,
            metadata={
                "num_turns": event.get("num_turns"),
                "duration_ms": event.get("duration_ms"),
                "duration_api_ms": event.get("duration_api_ms"),
                "session_id": resolved_session,
                "stream_events": collector.events,
                "stderr": stderr_text,
                "tool_results": collector.ordered_tool_results or None,
            },
            provider_data=event.get("modelUsage"),
        )


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

class ClaudeCodeAdapter(AgentAdapter):
    """Adapter that creates ClaudeCodeExecutor instances."""

    type_name = "claude-code"

    def create_executor(
        self,
        *,
        agent_name: str,
        agent_ref: AgentRef,
        context: AgentAdapterContext,
    ) -> AgentExecutor:
        config = agent_ref.config or {}

        # Fallback: if ref is still present (direct adapter usage, not
        # through FlatMachine which resolves refs at load time), load it.
        if not config and agent_ref.ref:
            loaded = self._load_ref(agent_ref.ref, context.config_dir)
            if loaded is not None:
                config = loaded

        settings = context.settings.get("agent_runners", {}).get("claude_code", {})

        return ClaudeCodeExecutor(
            config=config,
            config_dir=context.config_dir,
            settings=settings,
        )

    @staticmethod
    def _load_ref(ref: str, config_dir: str) -> Optional[dict]:
        """Load a ref file, resolving relative to config_dir."""
        import json as _json

        if os.path.isabs(ref):
            path = ref
        else:
            path = os.path.join(config_dir, ref)

        if not os.path.isfile(path):
            return None

        with open(path, 'r') as f:
            if path.endswith('.json'):
                return _json.load(f)
            else:
                try:
                    import yaml as _yaml
                    return _yaml.safe_load(f)
                except ImportError:
                    raise ImportError(
                        f"pyyaml is required to load YAML agent config: {path}"
                    )

"""Codex CLI adapter for FlatMachines.

Drives the OpenAI Codex CLI as a subprocess (``codex exec --json``) or via
the app-server JSON-RPC protocol (``codex app-server --listen stdio://``).
Codex owns its own tool loop -- this adapter does NOT implement
execute_with_tools().

Two transports:
  - **Exec transport** (default): one subprocess per call.  Supports resume
    via ``codex exec resume``.  No fork.
  - **App-server transport** (``use_app_server: true``): long-lived JSON-RPC
    subprocess.  Supports ``thread/start``, ``thread/fork``, ``turn/start``.
    Required for SessionHoldback fork-with-cache.

Design rules:
  - No data truncation.  Stream events, result text, tool outputs, stderr
    -- all captured in full.
  - Model is ALWAYS pinned explicitly (config.toml migrations silently
    upgrade without it).
  - Token usage in app-server arrives via ``thread/tokenUsage/updated``,
    NOT inside ``turn/completed``.

Config keys (agent config or global settings.agent_runners.codex_cli):
  model               Model slug (default: gpt-5.3-codex)
  reasoning_effort    none|minimal|low|medium|high|xhigh (default: high)
  sandbox             read-only|workspace-write|danger-full-access (default: workspace-write)
  approval_policy     untrusted|on-request|never (default: never)
  output_schema       Path to JSON Schema file for structured output
  add_dirs            List of additional writable directories
  codex_bin           Path to codex binary (default: "codex")
  working_dir         Working directory for subprocess (supports Jinja2)
  timeout             Subprocess timeout in seconds (0 = no timeout)
  skip_git_repo_check bool -- allow running outside git repos
  ephemeral           bool -- don't persist session to disk
  search              bool -- enable web search tool
  config_overrides    Dict of -c key=value pairs
  feature_enable      List of features to enable
  feature_disable     List of features to disable
  rate_limit_delay    Base seconds between CLI calls (default: 0)
  rate_limit_jitter   +/-seconds jitter (default: 0)
  use_app_server      bool -- use app-server transport (required for fork)
  session_source      App-server session source tag (default: "exec")
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
from typing import Any, Callable, Dict, List, Optional

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

_DEFAULT_MODEL = "gpt-5.3-codex"
_DEFAULT_REASONING_EFFORT = "high"
_DEFAULT_SANDBOX = "workspace-write"
_DEFAULT_APPROVAL = "never"
_SIGTERM_GRACE_SECONDS = 5
_FLATMACHINES_VERSION = "0.1.0"


# ---------------------------------------------------------------------------
# Exec stream collector
# ---------------------------------------------------------------------------

class _ExecStreamCollector:
    """Collects JSONL events from ``codex exec --json``.

    Event types: thread.started, turn.started, item.started,
    item.completed, turn.completed, turn.failed, error.
    """

    def __init__(self) -> None:
        self.events: List[Dict[str, Any]] = []
        self.thread_id: Optional[str] = None
        self.items: List[Dict[str, Any]] = []
        self.usage: Optional[Dict[str, Any]] = None
        self.error: Optional[Dict[str, Any]] = None
        self.final_message: Optional[str] = None

    def ingest(self, event: Dict[str, Any]) -> None:
        """Ingest a single parsed JSONL event."""
        etype = event.get("type")
        self.events.append(event)

        if etype == "thread.started":
            self.thread_id = event.get("thread_id")

        elif etype == "item.completed":
            item = event.get("item", {})
            self.items.append(item)
            if item.get("type") == "agent_message":
                self.final_message = item.get("text")

        elif etype == "item.started":
            # Tracked for observability; not used in result building
            pass

        elif etype == "turn.completed":
            self.usage = event.get("usage")

        elif etype == "turn.failed":
            err = event.get("error", {})
            self.error = err if isinstance(err, dict) else {"message": str(err)}

        elif etype == "error":
            self.error = {"message": event.get("message", "Unknown error")}


# ---------------------------------------------------------------------------
# App-server JSON-RPC transport
# ---------------------------------------------------------------------------

class CodexAppServerTransport:
    """Manages a ``codex app-server --listen stdio://`` subprocess.

    Multiplexes JSON-RPC requests/responses and server notifications
    over stdin/stdout.  Notifications are dispatched to a registered
    callback; responses are correlated by request ID.
    """

    def __init__(
        self,
        codex_bin: str = "codex",
        cwd: Optional[str] = None,
        session_source: str = "exec",
    ) -> None:
        self._codex_bin = codex_bin
        self._cwd = cwd
        self._session_source = session_source
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._next_id = 0
        self._pending: Dict[int, asyncio.Future] = {}
        self._notification_cbs: List[Callable[[dict], None]] = []
        self._reader_task: Optional[asyncio.Task] = None
        self._started = False

    # -- Lifecycle ----------------------------------------------------------

    async def start(self) -> None:
        """Spawn the app-server subprocess and initialize the protocol."""
        self._proc = await asyncio.create_subprocess_exec(
            self._codex_bin, "app-server",
            "--listen", "stdio://",
            "--session-source", self._session_source,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self._cwd,
            env=os.environ.copy(),
        )
        self._reader_task = asyncio.create_task(self._read_loop())

        resp = await self._request("initialize", {
            "clientInfo": {
                "name": "flatmachines",
                "version": _FLATMACHINES_VERSION,
            },
        })
        self._started = True
        logger.info("Codex app-server initialized: %s", resp.get("serverVersion", "?"))

    async def stop(self) -> None:
        """Terminate the app-server subprocess."""
        self._started = False
        if self._reader_task:
            self._reader_task.cancel()
            self._reader_task = None
        if self._proc and self._proc.returncode is None:
            try:
                self._proc.terminate()
            except ProcessLookupError:
                pass
            await self._proc.wait()
        self._proc = None
        # Fail any pending requests
        for future in self._pending.values():
            if not future.done():
                future.set_exception(RuntimeError("Transport stopped"))
        self._pending.clear()

    @property
    def is_running(self) -> bool:
        return self._started and self._proc is not None and self._proc.returncode is None

    # -- JSON-RPC core ------------------------------------------------------

    async def _request(self, method: str, params: dict) -> dict:
        """Send a JSON-RPC request and await the response."""
        self._next_id += 1
        req_id = self._next_id
        msg = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}

        loop = asyncio.get_event_loop()
        future: asyncio.Future = loop.create_future()
        self._pending[req_id] = future

        assert self._proc and self._proc.stdin
        line = json.dumps(msg) + "\n"
        self._proc.stdin.write(line.encode())
        await self._proc.stdin.drain()

        return await future

    async def _read_loop(self) -> None:
        """Read JSON-RPC messages from stdout, dispatch responses and notifications."""
        assert self._proc and self._proc.stdout
        try:
            while True:
                line = await self._proc.stdout.readline()
                if not line:
                    break
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue

                msg_id = msg.get("id")
                if msg_id is not None and msg_id in self._pending:
                    future = self._pending.pop(msg_id)
                    if "error" in msg:
                        future.set_exception(
                            RuntimeError(f"RPC error on {msg_id}: {msg['error']}")
                        )
                    else:
                        future.set_result(msg.get("result", {}))
                elif "method" in msg:
                    for cb in self._notification_cbs:
                        try:
                            cb(msg)
                        except Exception:
                            logger.exception("Notification callback error")
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("App-server read loop error")

    def add_notification_listener(self, cb: Callable[[dict], None]) -> None:
        """Add a notification listener.  Multiple listeners are supported."""
        self._notification_cbs.append(cb)

    def remove_notification_listener(self, cb: Callable[[dict], None]) -> None:
        """Remove a previously added notification listener."""
        try:
            self._notification_cbs.remove(cb)
        except ValueError:
            pass

    # Keep for backwards compat / simple use
    def on_notification(self, cb: Optional[Callable[[dict], None]]) -> None:
        """Set or clear the sole notification callback (legacy).

        For concurrent use, prefer add/remove_notification_listener().
        """
        # Remove all existing callbacks and optionally add the new one
        self._notification_cbs.clear()
        if cb is not None:
            self._notification_cbs.append(cb)

    # -- Thread operations --------------------------------------------------

    async def thread_start(
        self,
        cwd: str,
        model: str = _DEFAULT_MODEL,
        sandbox: str = _DEFAULT_SANDBOX,
        approval_policy: str = _DEFAULT_APPROVAL,
        ephemeral: bool = False,
    ) -> dict:
        """Start a new thread. Returns full response with thread object."""
        return await self._request("thread/start", {
            "cwd": cwd,
            "model": model,
            "sandbox": sandbox,
            "approvalPolicy": approval_policy,
            "ephemeral": ephemeral,
        })

    async def thread_fork(
        self,
        thread_id: str,
        model: Optional[str] = None,
        **overrides: Any,
    ) -> dict:
        """Fork a thread.  Returns new Thread with full parent history.

        IMPORTANT: Always pass *model* explicitly.  Without it, codex
        auto-upgrades to the latest model (e.g. gpt-5.4) due to model
        migration notices in config.toml.
        """
        params: Dict[str, Any] = {"threadId": thread_id, **overrides}
        if model:
            params["model"] = model
        return await self._request("thread/fork", params)

    async def thread_resume(self, thread_id: str, **overrides: Any) -> dict:
        """Resume an existing thread."""
        params: Dict[str, Any] = {"threadId": thread_id, **overrides}
        return await self._request("thread/resume", params)

    async def thread_read(self, thread_id: str, include_turns: bool = True) -> dict:
        """Read thread state and history."""
        return await self._request("thread/read", {
            "threadId": thread_id,
            "includeTurns": include_turns,
        })

    # -- Turn operations ----------------------------------------------------

    async def turn_start(
        self,
        thread_id: str,
        text: str,
        output_schema: Optional[dict] = None,
    ) -> dict:
        """Send a user message and start a new turn."""
        params: Dict[str, Any] = {
            "threadId": thread_id,
            "input": [{"type": "text", "text": text}],
        }
        if output_schema:
            params["outputSchema"] = output_schema
        return await self._request("turn/start", params)

    async def turn_interrupt(self, thread_id: str) -> dict:
        """Interrupt a running turn."""
        return await self._request("turn/interrupt", {"threadId": thread_id})


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------

class CodexCliExecutor(AgentExecutor):
    """Executor that drives Codex CLI via exec subprocess or app-server."""

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
        self._merged: Dict[str, Any] = {**settings, **config}

        if throttle is not None:
            self._throttle = throttle
        else:
            self._throttle = throttle_from_config(self._merged)

        self._process: Optional[asyncio.subprocess.Process] = None
        self._transport: Optional[CodexAppServerTransport] = None

    @property
    def metadata(self) -> Dict[str, Any]:
        return {}

    # -- Public interface ---------------------------------------------------

    async def execute(
        self,
        input_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
    ) -> AgentResult:
        """Execute a Codex CLI invocation.

        `session_id` is accepted for AgentExecutor protocol compatibility.
        The Codex CLI adapter uses explicit `input.resume_session` to resume
        existing Codex threads; `session_id` is intentionally ignored.
        """
        task = input_data.get("task") or input_data.get("prompt", "")
        if not task:
            return AgentResult(
                error={
                    "code": "invalid_request",
                    "type": "ValueError",
                    "message": "codex-cli adapter requires input.task or input.prompt",
                    "retryable": False,
                },
                finish_reason="error",
            )

        resume_session = input_data.get("resume_session")

        if self._merged.get("use_app_server"):
            return await self._execute_app_server(task, resume_session, context)
        else:
            return await self._execute_exec(task, resume_session, context)

    async def execute_with_tools(
        self,
        input_data: Dict[str, Any],
        tools: List[Dict[str, Any]],
        messages: Optional[List[Dict[str, Any]]] = None,
        context: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
    ) -> AgentResult:
        """Not supported -- Codex CLI owns its tool loop.

        `session_id` is accepted for AgentExecutor protocol compatibility.
        """
        raise NotImplementedError(
            "Codex CLI adapter does not support machine-driven tool loops. "
            "Remove tool_loop from the state config."
        )

    # -- Cancellation -------------------------------------------------------

    async def cancel(self) -> bool:
        """Cancel the running subprocess with SIGTERM -> grace -> SIGKILL."""
        proc = self._process
        if proc is None:
            return False

        logger.info("Codex CLI cancel: sending SIGTERM to pid %s", proc.pid)
        try:
            proc.send_signal(signal.SIGTERM)
        except ProcessLookupError:
            return False

        try:
            await asyncio.wait_for(proc.wait(), timeout=_SIGTERM_GRACE_SECONDS)
        except asyncio.TimeoutError:
            logger.warning(
                "Codex CLI cancel: SIGTERM grace expired, sending SIGKILL to pid %s",
                proc.pid,
            )
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            await proc.wait()

        return True

    # -- Transport management -----------------------------------------------

    async def _ensure_transport(self) -> CodexAppServerTransport:
        """Lazy-initialize the app-server transport."""
        if self._transport is not None and self._transport.is_running:
            return self._transport

        cfg = self._merged
        working_dir = self._resolve_working_dir(cfg, None)

        self._transport = CodexAppServerTransport(
            codex_bin=cfg.get("codex_bin", "codex"),
            cwd=working_dir,
            session_source=cfg.get("session_source", "exec"),
        )
        await self._transport.start()
        return self._transport

    async def close_transport(self) -> None:
        """Shut down the app-server transport if running."""
        if self._transport:
            await self._transport.stop()
            self._transport = None

    # -- Exec transport -----------------------------------------------------

    async def _execute_exec(
        self,
        task: str,
        resume_session: Optional[str],
        context: Optional[Dict[str, Any]],
    ) -> AgentResult:
        """Run via ``codex exec --json`` subprocess."""
        waited = await self._throttle.wait()
        if waited > 0:
            logger.info("Codex CLI throttle: waited %.3fs before call", waited)

        cfg = self._merged
        model = cfg.get("model", _DEFAULT_MODEL)
        agent_id = f"codex-cli/{model}"
        args = self._build_exec_args(task, resume_session)
        working_dir = self._resolve_working_dir(cfg, context)
        timeout = cfg.get("timeout", 0)

        logger.info(
            "Codex CLI exec: resume=%s timeout=%s cwd=%s",
            resume_session, timeout, working_dir,
        )

        with AgentMonitor(agent_id, extra_attributes={
            "adapter": "codex-cli",
            "transport": "exec",
            "resume": str(bool(resume_session)),
        }) as monitor:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=working_dir,
                env=os.environ.copy(),
            )
            self._process = proc

            collector = _ExecStreamCollector()
            stderr_data = b""

            try:
                if timeout and timeout > 0:
                    stderr_data = await asyncio.wait_for(
                        self._read_exec_stream(proc, collector),
                        timeout=timeout,
                    )
                else:
                    stderr_data = await self._read_exec_stream(proc, collector)
            except asyncio.TimeoutError:
                await self._kill_process(proc)
                return AgentResult(
                    error={
                        "code": "timeout",
                        "type": "TimeoutError",
                        "message": f"Codex CLI timed out after {timeout}s",
                        "retryable": True,
                    },
                    finish_reason="error",
                )

            await proc.wait()
            self._process = None

            stderr_text = stderr_data.decode("utf-8", errors="replace")
            result = self._build_result_from_exec(collector, proc.returncode, stderr_text)
            self._populate_monitor(monitor, result)
            return result

    async def _read_exec_stream(
        self,
        proc: asyncio.subprocess.Process,
        collector: _ExecStreamCollector,
    ) -> bytes:
        """Read JSONL from stdout, collect stderr.  Returns stderr bytes."""
        assert proc.stdout is not None
        assert proc.stderr is not None

        stderr_chunks: List[bytes] = []

        async def _drain_stderr() -> None:
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
                logger.warning("Codex CLI: unparseable JSONL: %s", line_str[:200])

        await stderr_task
        return b"".join(stderr_chunks)

    def _build_exec_args(
        self,
        task: str,
        resume_session: Optional[str],
    ) -> List[str]:
        """Build CLI argument list for codex exec.

        Note: ``codex exec`` does NOT support ``-a`` (approval policy).
        Use ``--full-auto`` (implies ``-a on-request --sandbox workspace-write``)
        or ``--dangerously-bypass-approvals-and-sandbox``.
        Sandbox is set via ``--sandbox``.  For ``-a never`` behaviour,
        use ``--dangerously-bypass-approvals-and-sandbox`` or ``--full-auto``.
        """
        cfg = self._merged
        codex_bin = cfg.get("codex_bin", "codex")
        model = cfg.get("model", _DEFAULT_MODEL)
        sandbox = cfg.get("sandbox", _DEFAULT_SANDBOX)

        # Build base command -- prompt must be last positional arg
        is_resume = resume_session is not None
        if is_resume:
            # codex exec resume [OPTIONS] <SESSION_ID> [PROMPT]
            args = [codex_bin, "exec", "resume", "--json", "--model", model]
        else:
            # codex exec [OPTIONS] [PROMPT]
            args = [codex_bin, "exec", "--json", "--model", model]

        # Sandbox policy -- codex exec resume does NOT support --sandbox,
        # only --full-auto and --dangerously-bypass-approvals-and-sandbox.
        # codex exec (non-resume) supports --sandbox directly.
        approval = cfg.get("approval_policy", _DEFAULT_APPROVAL)
        if cfg.get("dangerously_bypass_approvals_and_sandbox"):
            args += ["--dangerously-bypass-approvals-and-sandbox"]
        elif is_resume:
            # Resume only has --full-auto
            args += ["--full-auto"]
        else:
            # Non-resume: can use --sandbox + --full-auto
            args += ["--sandbox", sandbox]
            if approval in ("never", "on-request", "untrusted"):
                args += ["--full-auto"]

        # Reasoning effort
        effort = cfg.get("reasoning_effort", _DEFAULT_REASONING_EFFORT)
        if effort:
            args += ["-c", f'reasoning_effort="{effort}"']

        # Output schema
        output_schema = cfg.get("output_schema")
        if output_schema:
            args += ["--output-schema", str(output_schema)]

        # Additional directories
        add_dirs = cfg.get("add_dirs")
        if add_dirs:
            for d in add_dirs:
                args += ["--add-dir", d]

        # Skip git repo check
        if cfg.get("skip_git_repo_check"):
            args += ["--skip-git-repo-check"]

        # Ephemeral
        if cfg.get("ephemeral"):
            args += ["--ephemeral"]

        # Web search (exec doesn't have --search, use config override)
        if cfg.get("search"):
            args += ["-c", 'search=true']

        # Config overrides
        overrides = cfg.get("config_overrides", {})
        for key, val in overrides.items():
            args += ["-c", f'{key}={val}']

        # Feature flags
        for feat in cfg.get("feature_enable", []):
            args += ["--enable", feat]
        for feat in cfg.get("feature_disable", []):
            args += ["--disable", feat]

        # Positional args last: session_id (for resume) and prompt
        if resume_session:
            args += [resume_session, task]
        else:
            args += [task]

        return args

    def _build_result_from_exec(
        self,
        collector: _ExecStreamCollector,
        returncode: Optional[int],
        stderr_text: str,
    ) -> AgentResult:
        """Map _ExecStreamCollector state to AgentResult."""
        # Error cases
        if collector.error:
            msg = collector.error.get("message", "Unknown error")
            if stderr_text:
                msg = f"{msg}\nstderr: {stderr_text}"
            return AgentResult(
                error={
                    "code": "server_error",
                    "type": "CodexCliError",
                    "message": msg,
                    "retryable": False,
                },
                finish_reason="error",
                content=collector.final_message,
                metadata={
                    "thread_id": collector.thread_id,
                    "stream_events": collector.events,
                    "items": collector.items,
                    "stderr": stderr_text,
                },
            )

        if returncode and returncode != 0 and collector.final_message is None:
            return AgentResult(
                error={
                    "code": "server_error",
                    "type": "CodexCliProcessError",
                    "message": f"codex exited with code {returncode}\nstderr: {stderr_text}",
                    "retryable": returncode in (137, 143),
                },
                finish_reason="error",
                metadata={
                    "thread_id": collector.thread_id,
                    "stream_events": collector.events,
                    "stderr": stderr_text,
                },
            )

        # Success
        usage = None
        if collector.usage:
            usage = {
                "input_tokens": collector.usage.get("input_tokens", 0),
                "output_tokens": collector.usage.get("output_tokens", 0),
                "cached_input_tokens": collector.usage.get("cached_input_tokens", 0),
            }

        output = {
            "result": collector.final_message,
            "thread_id": collector.thread_id,
        }

        return AgentResult(
            output=output,
            content=collector.final_message,
            usage=usage,
            finish_reason="stop",
            metadata={
                "thread_id": collector.thread_id,
                "stream_events": collector.events,
                "items": collector.items,
                "stderr": stderr_text,
            },
        )

    # -- App-server transport -----------------------------------------------

    async def _execute_app_server(
        self,
        task: str,
        resume_session: Optional[str],
        context: Optional[Dict[str, Any]],
    ) -> AgentResult:
        """Run via app-server JSON-RPC transport."""
        waited = await self._throttle.wait()
        if waited > 0:
            logger.info("Codex CLI throttle: waited %.3fs before call", waited)

        cfg = self._merged
        model = cfg.get("model", _DEFAULT_MODEL)
        agent_id = f"codex-cli/{model}"
        transport = await self._ensure_transport()

        with AgentMonitor(agent_id, extra_attributes={
            "adapter": "codex-cli",
            "transport": "app-server",
            "resume": str(bool(resume_session)),
        }) as monitor:
            try:
                if resume_session:
                    await transport.thread_resume(resume_session, model=model)
                    thread_id = resume_session
                else:
                    resp = await transport.thread_start(
                        cwd=self._resolve_working_dir(cfg, context) or os.getcwd(),
                        model=model,
                        sandbox=cfg.get("sandbox", _DEFAULT_SANDBOX),
                        approval_policy=cfg.get("approval_policy", _DEFAULT_APPROVAL),
                        ephemeral=cfg.get("ephemeral", False),
                    )
                    thread_id = resp["thread"]["id"]

                result = await self._run_turn_and_collect(
                    transport, thread_id, task, cfg.get("timeout", 0),
                )
                self._populate_monitor(monitor, result)
                return result

            except Exception as exc:
                logger.exception("Codex app-server execute failed")
                return AgentResult(
                    error={
                        "code": "server_error",
                        "type": type(exc).__name__,
                        "message": str(exc),
                        "retryable": False,
                    },
                    finish_reason="error",
                )

    async def _run_turn_and_collect(
        self,
        transport: CodexAppServerTransport,
        thread_id: str,
        text: str,
        timeout: int = 0,
    ) -> AgentResult:
        """Start a turn on the app-server and collect notifications until done.

        Notification methods (codex-cli 0.116.0):
          item/completed             -> item data
          thread/tokenUsage/updated  -> token usage (separate from turn/completed)
          turn/completed             -> turn status only
          turn/failed                -> error
        """
        collected_items: List[Dict[str, Any]] = []
        turn_done = asyncio.Event()
        turn_state: Dict[str, Any] = {}

        def _on_notification(msg: dict) -> None:
            method = msg.get("method", "")
            params = msg.get("params", {})
            if params.get("threadId") != thread_id:
                return

            if "item/completed" in method:
                collected_items.append(params.get("item", {}))

            elif "tokenUsage/updated" in method:
                usage_total = params.get("tokenUsage", {}).get("total", {})
                turn_state["usage"] = {
                    "input_tokens": usage_total.get("inputTokens", 0),
                    "output_tokens": usage_total.get("outputTokens", 0),
                    "cached_input_tokens": usage_total.get("cachedInputTokens", 0),
                    "reasoning_tokens": usage_total.get("reasoningOutputTokens", 0),
                    "context_window": params.get("tokenUsage", {}).get(
                        "modelContextWindow", 0),
                }

            elif "turn/completed" in method:
                turn_state["status"] = "completed"
                turn_done.set()

            elif "turn/failed" in method:
                turn_state["status"] = "failed"
                turn_obj = params.get("turn", {})
                turn_state["error"] = turn_obj.get("error")
                turn_done.set()

        transport.add_notification_listener(_on_notification)

        try:
            # Load output schema if configured
            output_schema = None
            schema_path = self._merged.get("output_schema")
            if schema_path and os.path.isfile(str(schema_path)):
                with open(str(schema_path)) as f:
                    output_schema = json.load(f)

            await transport.turn_start(thread_id, text, output_schema)

            if timeout and timeout > 0:
                await asyncio.wait_for(turn_done.wait(), timeout=timeout)
            else:
                await turn_done.wait()
        finally:
            transport.remove_notification_listener(_on_notification)

        return self._build_result_from_turn(
            collected_items, turn_state, thread_id,
        )

    def _build_result_from_turn(
        self,
        items: List[Dict[str, Any]],
        turn_state: Dict[str, Any],
        thread_id: str,
    ) -> AgentResult:
        """Map app-server turn notifications to AgentResult."""
        # Extract final agent message
        final_message = None
        for item in reversed(items):
            if item.get("type") == "agentMessage":
                final_message = item.get("text")
                break

        # Error case
        if turn_state.get("status") == "failed":
            err = turn_state.get("error", {})
            return AgentResult(
                error={
                    "code": "server_error",
                    "type": "CodexCliTurnError",
                    "message": err.get("message", "Turn failed") if isinstance(err, dict) else str(err),
                    "retryable": False,
                },
                finish_reason="error",
                content=final_message,
                metadata={
                    "thread_id": thread_id,
                    "items": items,
                },
            )

        output = {
            "result": final_message,
            "thread_id": thread_id,
        }

        return AgentResult(
            output=output,
            content=final_message,
            usage=turn_state.get("usage"),
            finish_reason="stop",
            metadata={
                "thread_id": thread_id,
                "items": items,
            },
        )

    # -- Helpers ------------------------------------------------------------

    def _resolve_working_dir(
        self,
        cfg: Dict[str, Any],
        context: Optional[Dict[str, Any]],
    ) -> Optional[str]:
        """Resolve working directory from config, with Jinja2 support."""
        working_dir = cfg.get("working_dir")
        if working_dir and context:
            if "{{" in str(working_dir):
                try:
                    from jinja2 import Template
                    working_dir = Template(str(working_dir)).render(context=context)
                except Exception:
                    pass
        if working_dir:
            return os.path.abspath(working_dir)
        return self._config_dir or None

    @staticmethod
    async def _kill_process(proc: asyncio.subprocess.Process) -> None:
        """SIGTERM -> grace -> SIGKILL a subprocess."""
        try:
            proc.send_signal(signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(proc.wait(), timeout=_SIGTERM_GRACE_SECONDS)
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            await proc.wait()

    @staticmethod
    def _populate_monitor(monitor: AgentMonitor, result: AgentResult) -> None:
        """Populate an AgentMonitor's metrics dict from an AgentResult."""
        if result.usage:
            inp = result.usage.get("input_tokens", 0)
            out = result.usage.get("output_tokens", 0)
            monitor.metrics["input_tokens"] = inp
            monitor.metrics["output_tokens"] = out
            monitor.metrics["tokens"] = inp + out
            cached = result.usage.get("cached_input_tokens", 0)
            if cached:
                monitor.metrics["cached_input_tokens"] = cached
        if result.error:
            monitor.metrics["error"] = True
            monitor.metrics["error_type"] = result.error.get("type", "unknown")


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

class CodexCliAdapter(AgentAdapter):
    """Adapter that creates CodexCliExecutor instances."""

    type_name = "codex-cli"

    def create_executor(
        self,
        *,
        agent_name: str,
        agent_ref: AgentRef,
        context: AgentAdapterContext,
    ) -> AgentExecutor:
        config = agent_ref.config or {}

        if not config and agent_ref.ref:
            loaded = self._load_ref(agent_ref.ref, context.config_dir)
            if loaded is not None:
                config = loaded

        settings = context.settings.get("agent_runners", {}).get("codex_cli", {})

        return CodexCliExecutor(
            config=config,
            config_dir=context.config_dir,
            settings=settings,
        )

    @staticmethod
    def _load_ref(ref: str, config_dir: str) -> Optional[dict]:
        """Load a ref file, resolving relative to config_dir."""
        if os.path.isabs(ref):
            path = ref
        else:
            path = os.path.join(config_dir, ref)

        if not os.path.isfile(path):
            return None

        with open(path, "r") as f:
            if path.endswith(".json"):
                return json.load(f)
            else:
                try:
                    import yaml as _yaml
                    return _yaml.safe_load(f)
                except ImportError:
                    raise ImportError(
                        f"pyyaml is required to load YAML agent config: {path}"
                    )

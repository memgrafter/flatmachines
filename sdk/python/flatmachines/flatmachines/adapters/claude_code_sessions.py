"""Session holdback pattern for Claude Code CLI adapter.

Maintains a frozen "holdback" session that forks produce cache-warm
children from.  The holdback is never advanced — only forks diverge.

Cache mechanics:
  - Claude Code stores conversation history locally, sends to API on resume
  - API prompt cache is prefix-based with 1-hour TTL (Claude Max plan)
  - Fork sends the same prefix as the holdback → API cache hit
  - Periodic warm() keeps the prefix in API cache without advancing holdback

Usage:
    holdback = SessionHoldback(executor)
    await holdback.seed("Read the codebase and understand the architecture.")

    # Fan out — each gets full context, hits cache
    results = await holdback.fork_n([
        "Implement the auth module",
        "Implement the database layer",
        "Write the test suite",
    ])

    # Keep cache warm while idle (optional, within 1hr TTL)
    await holdback.warm()
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .claude_code import ClaudeCodeExecutor
from ..agents import AgentResult

logger = logging.getLogger(__name__)


@dataclass
class ForkResult:
    """Result from a forked session."""
    session_id: str
    task: str
    result: AgentResult
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


@dataclass
class SessionHoldback:
    """Manages a frozen session for cache-warm fan-out.

    The holdback session is seeded once, then only forked from.
    Plain --resume is never used on the holdback — every operation
    after seed uses --fork-session to get a new session ID while
    preserving the shared prefix for API cache hits.

    Args:
        executor: ClaudeCodeExecutor instance (already configured)
        session_id: Optional pre-existing session ID to adopt as holdback
    """

    executor: ClaudeCodeExecutor
    session_id: Optional[str] = None
    _seeded: bool = field(default=False, init=False)
    _fork_count: int = field(default=0, init=False)
    _total_cost: float = field(default=0.0, init=False)

    async def seed(
        self,
        task: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> AgentResult:
        """Create the holdback session with initial content.

        This is the only call that uses --session-id (new session).
        All subsequent operations use --fork-session.

        Args:
            task: Initial prompt to seed the session with
            context: Optional context for working_dir resolution

        Returns:
            AgentResult from the seed invocation
        """
        if self.session_id is None:
            self.session_id = str(uuid.uuid4())

        result = await self.executor._invoke_once(
            task=task,
            session_id=self.session_id,
            resume=False,
            context=context,
        )

        self._seeded = True
        self._accumulate_cost(result)

        logger.info(
            "Holdback seeded: session=%s cache_write=%s",
            self.session_id,
            (result.usage or {}).get("cache_write_tokens", 0),
        )
        return result

    async def adopt(self, session_id: str) -> None:
        """Adopt an existing session as the holdback.

        Use this when you have a session from a prior machine execution
        and want to fork from it without re-seeding.

        Args:
            session_id: Existing Claude Code session ID
        """
        self.session_id = session_id
        self._seeded = True
        logger.info("Holdback adopted: session=%s", session_id)

    async def fork(
        self,
        task: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> ForkResult:
        """Fork a new session from the holdback and execute a task.

        The fork gets a new session ID but sees the full holdback
        conversation.  The holdback is not advanced.

        Args:
            task: Prompt for the forked session
            context: Optional context for working_dir resolution

        Returns:
            ForkResult with the new session ID and result
        """
        if not self._seeded:
            raise RuntimeError("Holdback not seeded — call seed() or adopt() first")

        result = await self._fork_once(task, context)
        self._fork_count += 1
        self._accumulate_cost(result)

        usage = result.usage or {}
        fork_session = (result.metadata or {}).get("session_id", "?")

        fr = ForkResult(
            session_id=fork_session,
            task=task,
            result=result,
            cache_read_tokens=usage.get("cache_read_tokens", 0),
            cache_write_tokens=usage.get("cache_write_tokens", 0),
        )

        logger.info(
            "Holdback fork: parent=%s child=%s cache_read=%s cache_write=%s",
            self.session_id, fork_session,
            fr.cache_read_tokens, fr.cache_write_tokens,
        )
        return fr

    async def fork_n(
        self,
        tasks: List[str],
        context: Optional[Dict[str, Any]] = None,
        max_concurrent: Optional[int] = None,
    ) -> List[ForkResult]:
        """Fork N sessions in parallel, each with a different task.

        All forks share the holdback prefix and hit API cache.

        Args:
            tasks: List of prompts, one per fork
            context: Optional context for working_dir resolution
            max_concurrent: Max concurrent forks (None = all at once)

        Returns:
            List of ForkResult in same order as tasks
        """
        if not self._seeded:
            raise RuntimeError("Holdback not seeded — call seed() or adopt() first")

        if max_concurrent is None or max_concurrent <= 0:
            max_concurrent = len(tasks)

        semaphore = asyncio.Semaphore(max_concurrent)

        async def _limited_fork(task: str) -> ForkResult:
            async with semaphore:
                return await self.fork(task, context)

        results = await asyncio.gather(
            *[_limited_fork(t) for t in tasks],
            return_exceptions=True,
        )

        # Convert exceptions to ForkResult with error
        final: List[ForkResult] = []
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                final.append(ForkResult(
                    session_id="",
                    task=tasks[i],
                    result=AgentResult(
                        error={
                            "code": "server_error",
                            "type": type(r).__name__,
                            "message": str(r),
                            "retryable": False,
                        },
                        finish_reason="error",
                    ),
                ))
            else:
                final.append(r)

        return final

    async def warm(
        self,
        context: Optional[Dict[str, Any]] = None,
    ) -> AgentResult:
        """Send a minimal request to keep the API prefix cache warm.

        Uses --fork-session so the holdback is not advanced.
        The fork is discarded — its only purpose is to touch the API
        with the holdback's prefix so the 1-hour cache TTL resets.

        Args:
            context: Optional context for working_dir resolution

        Returns:
            AgentResult from the warm invocation
        """
        if not self._seeded:
            raise RuntimeError("Holdback not seeded — call seed() or adopt() first")

        result = await self._fork_once("test", context)
        self._accumulate_cost(result)

        usage = result.usage or {}
        logger.info(
            "Holdback warm: session=%s cache_read=%s cost=%s",
            self.session_id,
            usage.get("cache_read_tokens", 0),
            result.cost,
        )
        return result

    @property
    def stats(self) -> Dict[str, Any]:
        """Current holdback statistics."""
        return {
            "session_id": self.session_id,
            "seeded": self._seeded,
            "fork_count": self._fork_count,
            "total_cost": self._total_cost,
        }

    # -- Internal -----------------------------------------------------------

    async def _fork_once(
        self,
        task: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> AgentResult:
        """Execute a single fork from the holdback.

        Builds args manually to inject --fork-session, which the
        standard _invoke_once doesn't support.
        """
        import asyncio as _asyncio
        import json
        import os
        import signal as _signal

        cfg = self.executor._merged
        claude_bin = cfg.get("claude_bin", "claude")
        timeout = cfg.get("timeout", 0)

        # Build args — like _build_args but with --resume + --fork-session
        args = [claude_bin, "-p", task, "--output-format", "stream-json", "--verbose"]
        args += ["--resume", self.session_id, "--fork-session"]

        model = cfg.get("model", "opus")
        args += ["--model", model]

        permission_mode = cfg.get("permission_mode")
        if permission_mode:
            args += ["--permission-mode", permission_mode]

        system_prompt = cfg.get("system_prompt")
        append_system_prompt = cfg.get("append_system_prompt")
        if system_prompt:
            args += ["--system-prompt", system_prompt]
        elif append_system_prompt:
            args += ["--append-system-prompt", append_system_prompt]

        tools = cfg.get("tools")
        if tools:
            args += ["--tools"] + list(tools)

        max_budget = cfg.get("max_budget_usd", 0)
        if max_budget and float(max_budget) > 0:
            args += ["--max-budget-usd", str(max_budget)]

        effort = cfg.get("effort", "high")
        args += ["--effort", effort]

        # Resolve working directory
        working_dir = cfg.get("working_dir")
        if working_dir and context:
            if "{{" in str(working_dir):
                try:
                    from jinja2 import Template
                    working_dir = Template(str(working_dir)).render(context=context)
                except Exception:
                    pass
        if working_dir:
            working_dir = os.path.abspath(working_dir)
        else:
            working_dir = self.executor._config_dir

        logger.debug("Holdback fork args: %s", args)

        proc = await _asyncio.create_subprocess_exec(
            *args,
            stdout=_asyncio.subprocess.PIPE,
            stderr=_asyncio.subprocess.PIPE,
            cwd=working_dir,
            env=os.environ.copy(),
        )

        from .claude_code import _StreamCollector, _SIGTERM_GRACE_SECONDS

        collector = _StreamCollector()
        try:
            if timeout and timeout > 0:
                stderr_data = await _asyncio.wait_for(
                    self.executor._read_stream(proc, collector),
                    timeout=timeout,
                )
            else:
                stderr_data = await self.executor._read_stream(proc, collector)
        except _asyncio.TimeoutError:
            try:
                proc.send_signal(_signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                await _asyncio.wait_for(proc.wait(), timeout=_SIGTERM_GRACE_SECONDS)
            except _asyncio.TimeoutError:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
                await proc.wait()
            raise TimeoutError(
                f"Claude Code fork timed out after {timeout}s "
                f"(holdback={self.session_id})"
            )

        await proc.wait()
        stderr_text = stderr_data.decode("utf-8", errors="replace")

        if collector.result_event is None:
            return AgentResult(
                error={
                    "code": "server_error",
                    "type": "ClaudeCodeError",
                    "message": f"No result event from fork\nstderr: {stderr_text}",
                    "retryable": False,
                },
                finish_reason="error",
                metadata={
                    "session_id": collector.session_id or "",
                    "stream_events": collector.events,
                    "stderr": stderr_text,
                },
            )

        return self.executor._build_result(collector, self.session_id, stderr_text)

    def _accumulate_cost(self, result: AgentResult) -> None:
        if result.cost is not None:
            if isinstance(result.cost, (int, float)):
                self._total_cost += float(result.cost)
            elif isinstance(result.cost, dict):
                self._total_cost += float(result.cost.get("total", 0))

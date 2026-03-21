"""Session holdback pattern for Codex CLI adapter.

Maintains a frozen "holdback" thread that forks produce cache-warm
children from.  The holdback is never advanced -- only forks diverge.

Cache mechanics (Responses API):
  - Codex stores conversation history in local rollout files
  - On resume/fork the full history is sent to the API
  - Responses API prefix cache is automatic -- no TTL management needed
  - Fork sends the same prefix as the holdback -> API cache hit

Usage:
    holdback = CodexSessionHoldback(executor)
    await holdback.seed("Read the codebase and understand the architecture.")

    # Fan out -- each gets full context, hits cache
    results = await holdback.fork_n([
        "Implement the auth module",
        "Implement the database layer",
        "Write the test suite",
    ])

    # Warm is a no-op for Codex (cache is automatic)
    await holdback.warm()
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .codex_cli import CodexCliExecutor, CodexAppServerTransport
from ..agents import AgentResult

logger = logging.getLogger(__name__)


@dataclass
class ForkResult:
    """Result from a forked session."""
    thread_id: str
    task: str
    result: AgentResult
    cached_input_tokens: int = 0


@dataclass
class CodexSessionHoldback:
    """Manages a frozen thread for cache-warm fan-out via app-server.

    Equivalent to ``claude_code_sessions.SessionHoldback`` but uses
    the app-server's ``thread/fork`` instead of CLI ``--fork-session``.

    Args:
        executor: CodexCliExecutor instance (must have use_app_server=True
            or the caller must have started the transport)
        model: Model slug to pin on all forks (default: gpt-5.3-codex)
        thread_id: Optional pre-existing thread ID to adopt as holdback
    """

    executor: CodexCliExecutor
    model: str = "gpt-5.3-codex"
    thread_id: Optional[str] = None
    _seeded: bool = field(default=False, init=False)
    _fork_count: int = field(default=0, init=False)
    _total_input_tokens: int = field(default=0, init=False)
    _total_cached_tokens: int = field(default=0, init=False)

    async def seed(
        self,
        task: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> AgentResult:
        """Create the holdback thread and run the seed prompt.

        Uses the app-server transport to start a new thread and execute
        the seed task.  The API prefix cache is primed immediately.

        Args:
            task: Initial prompt to seed the session with
            context: Optional context for working_dir resolution

        Returns:
            AgentResult from the seed invocation
        """
        transport = await self.executor._ensure_transport()
        cfg = self.executor._merged

        resp = await transport.thread_start(
            cwd=self.executor._resolve_working_dir(cfg, context) or ".",
            model=self.model,
            sandbox=cfg.get("sandbox", "workspace-write"),
            approval_policy=cfg.get("approval_policy", "never"),
            ephemeral=cfg.get("ephemeral", False),
        )
        self.thread_id = resp["thread"]["id"]

        result = await self.executor._run_turn_and_collect(
            transport, self.thread_id, task,
            timeout=cfg.get("timeout", 0),
        )

        self._seeded = True
        self._accumulate_usage(result)

        logger.info(
            "Codex holdback seeded: thread=%s cached=%s",
            self.thread_id,
            (result.usage or {}).get("cached_input_tokens", 0),
        )

        return result

    async def adopt(self, thread_id: str) -> None:
        """Adopt an existing thread as the holdback.

        Use when you have a thread from a prior execution and want to
        fork from it without re-seeding.  Makes zero API calls.

        Args:
            thread_id: Existing Codex thread ID (UUID)
        """
        self.thread_id = thread_id
        self._seeded = True
        logger.info("Codex holdback adopted: thread=%s", thread_id)

    async def fork(
        self,
        task: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> ForkResult:
        """Fork a new thread from the holdback and execute a task.

        The fork gets a new thread ID but inherits the full holdback
        conversation history.  The holdback is not advanced.  Model is
        pinned explicitly to prevent auto-upgrade.

        Args:
            task: Prompt for the forked session
            context: Optional context for working_dir resolution

        Returns:
            ForkResult with the new thread ID and result
        """
        if not self._seeded:
            raise RuntimeError("Holdback not seeded -- call seed() or adopt() first")

        transport = await self.executor._ensure_transport()

        fork_resp = await transport.thread_fork(
            self.thread_id, model=self.model,
        )
        child_id = fork_resp["thread"]["id"]
        self._fork_count += 1

        cfg = self.executor._merged
        result = await self.executor._run_turn_and_collect(
            transport, child_id, task,
            timeout=cfg.get("timeout", 0),
        )
        self._accumulate_usage(result)

        cached = (result.usage or {}).get("cached_input_tokens", 0)
        logger.info(
            "Codex holdback fork: parent=%s child=%s cached=%s",
            self.thread_id, child_id, cached,
        )

        return ForkResult(
            thread_id=child_id,
            task=task,
            result=result,
            cached_input_tokens=cached,
        )

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
            max_concurrent: Max concurrent forks (None = 4)

        Returns:
            List of ForkResult in same order as tasks
        """
        if not self._seeded:
            raise RuntimeError("Holdback not seeded -- call seed() or adopt() first")

        if max_concurrent is None or max_concurrent <= 0:
            max_concurrent = 4

        semaphore = asyncio.Semaphore(max_concurrent)

        async def _limited_fork(task: str) -> ForkResult:
            async with semaphore:
                return await self.fork(task, context)

        results = await asyncio.gather(
            *[_limited_fork(t) for t in tasks],
            return_exceptions=True,
        )

        final: List[ForkResult] = []
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                final.append(ForkResult(
                    thread_id="",
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
        """Health check / cache verification.

        Codex's Responses API cache is automatic with no TTL to manage.
        This method exists for API parity with Claude Code's
        SessionHoldback.  It performs a minimal fork to verify
        connectivity and that the holdback thread is still valid.

        Args:
            context: Optional context for working_dir resolution

        Returns:
            AgentResult from the health-check invocation
        """
        if not self._seeded:
            raise RuntimeError("Holdback not seeded -- call seed() or adopt() first")

        transport = await self.executor._ensure_transport()

        fork_resp = await transport.thread_fork(
            self.thread_id, model=self.model,
        )
        child_id = fork_resp["thread"]["id"]

        cfg = self.executor._merged
        result = await self.executor._run_turn_and_collect(
            transport, child_id, "health check",
            timeout=cfg.get("timeout", 0),
        )
        self._accumulate_usage(result)

        cached = (result.usage or {}).get("cached_input_tokens", 0)
        logger.info(
            "Codex holdback warm: thread=%s cached=%s",
            self.thread_id, cached,
        )
        return result

    @property
    def stats(self) -> Dict[str, Any]:
        """Current holdback statistics."""
        return {
            "thread_id": self.thread_id,
            "seeded": self._seeded,
            "fork_count": self._fork_count,
            "total_input_tokens": self._total_input_tokens,
            "total_cached_tokens": self._total_cached_tokens,
        }

    # -- Internal -----------------------------------------------------------

    def _accumulate_usage(self, result: AgentResult) -> None:
        if result.usage:
            self._total_input_tokens += result.usage.get("input_tokens", 0)
            self._total_cached_tokens += result.usage.get("cached_input_tokens", 0)

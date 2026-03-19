"""Session holdback pattern for Claude Code CLI adapter.

Maintains a frozen "holdback" session that forks produce cache-warm
children from.  The holdback is never advanced — only forks diverge.

Cache mechanics:
  - Claude Code stores conversation history locally, sends to API on resume
  - API prompt cache is prefix-based with 1-hour TTL (Claude Max plan)
  - Fork sends the same prefix as the holdback → API cache hit
  - Periodic warm() keeps the prefix in API cache without advancing holdback

Cache writes are available immediately after seed returns — no warm
step is required before parallel fan-out.  warm() exists only to
reset the 1-hour TTL during long idle periods.

Usage:
    holdback = SessionHoldback(executor)
    await holdback.seed("Read the codebase and understand the architecture.")
    # Cache is ready — fan out immediately

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

        The API prefix cache is available immediately after this returns.
        No warm step is needed before parallel fan-out.

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

        If the session has been idle for close to 1 hour, call warm()
        before fork_n() to reset the cache TTL.

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

        result = await self.executor._invoke_once(
            task=task,
            session_id=self.session_id,
            resume=True,
            context=context,
            fork_session=True,
        )

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
        """Send a minimal request to reset the API prefix cache TTL.

        Only needed if the holdback has been idle for close to 1 hour.
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

        result = await self.executor._invoke_once(
            task="test",
            session_id=self.session_id,
            resume=True,
            context=context,
            fork_session=True,
        )

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

    def _accumulate_cost(self, result: AgentResult) -> None:
        if result.cost is not None:
            if isinstance(result.cost, (int, float)):
                self._total_cost += float(result.cost)
            elif isinstance(result.cost, dict):
                self._total_cost += float(result.cost.get("total", 0))

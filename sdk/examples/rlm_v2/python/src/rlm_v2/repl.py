"""Persistent REPL primitives for the RLM v2 example."""

from __future__ import annotations

import io
import re
import threading
import traceback
import uuid
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from typing import Any, Callable, Dict, List


REPL_BLOCK_PATTERN = re.compile(r"```repl\s*\n(.*?)\n```", re.DOTALL)


def extract_repl_blocks(text: str) -> list[str]:
    """Extract ```repl code blocks from text in order."""
    if not text:
        return []
    return [m.group(1).strip() for m in REPL_BLOCK_PATTERN.finditer(text)]


def truncate_text(value: Any, max_chars: int) -> str:
    """Convert value to str and truncate to max_chars."""
    text = "" if value is None else str(value)
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"... [+{len(text) - max_chars} chars]"


_SAFE_BUILTINS: dict[str, Any] = {
    "print": print,
    "len": len,
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "list": list,
    "dict": dict,
    "set": set,
    "tuple": tuple,
    "range": range,
    "enumerate": enumerate,
    "zip": zip,
    "map": map,
    "filter": filter,
    "sorted": sorted,
    "sum": sum,
    "min": min,
    "max": max,
    "abs": abs,
    "round": round,
    "any": any,
    "all": all,
    "repr": repr,
    "isinstance": isinstance,
    "type": type,
    "Exception": Exception,
    "ValueError": ValueError,
    "TypeError": TypeError,
    "KeyError": KeyError,
    "IndexError": IndexError,
    "NameError": NameError,
    "RuntimeError": RuntimeError,
    "__import__": __import__,
}


@dataclass
class REPLExecutionResult:
    stdout: str
    stderr: str
    changed_vars: list[str]

    @property
    def had_error(self) -> bool:
        return bool(self.stderr.strip())


class REPLSession:
    """A persistent Python namespace with injected llm_query."""

    def __init__(
        self,
        session_id: str,
        context_value: str,
        llm_query_fn: Callable[[Any, Any], str],
    ):
        self.session_id = session_id
        self.globals: dict[str, Any] = {
            "__builtins__": _SAFE_BUILTINS.copy(),
            "__name__": "__main__",
            "llm_query": llm_query_fn,
        }
        self.locals: dict[str, Any] = {
            "context": context_value,
        }

    def execute(self, code: str) -> REPLExecutionResult:
        """Execute code in this session and return captured output."""
        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()
        before = self._snapshot_locals()

        with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
            try:
                exec(code, self.globals, self.locals)
            except Exception:
                traceback.print_exc(file=stderr_buf)

        after = self._snapshot_locals()
        changed = self._diff_keys(before, after)

        return REPLExecutionResult(
            stdout=stdout_buf.getvalue(),
            stderr=stderr_buf.getvalue(),
            changed_vars=changed,
        )

    def has_variable(self, name: str) -> bool:
        return name in self.locals

    def get_variable(self, name: str) -> Any:
        return self.locals.get(name)

    def _snapshot_locals(self) -> dict[str, Any]:
        """Shallow snapshot of user-facing locals."""
        return {
            key: value
            for key, value in self.locals.items()
            if not key.startswith("_")
        }

    @staticmethod
    def _diff_keys(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
        """Best-effort changed key detection."""
        changed: list[str] = []

        for key, after_value in after.items():
            if key not in before:
                changed.append(key)
                continue

            before_value = before[key]
            if after_value is before_value:
                continue

            try:
                if after_value != before_value:
                    changed.append(key)
            except Exception:
                changed.append(key)

        return sorted(changed)


class REPLRegistry:
    """Thread-safe in-process REPL session registry."""

    _sessions: dict[str, REPLSession] = {}
    _lock = threading.RLock()

    @classmethod
    def create_session(
        cls,
        *,
        context_value: str,
        llm_query_fn: Callable[[Any, Any], str],
        session_id: str | None = None,
    ) -> str:
        sid = session_id or str(uuid.uuid4())
        with cls._lock:
            cls._sessions[sid] = REPLSession(
                session_id=sid,
                context_value=context_value,
                llm_query_fn=llm_query_fn,
            )
        return sid

    @classmethod
    def has_session(cls, session_id: str | None) -> bool:
        if not session_id:
            return False
        with cls._lock:
            return session_id in cls._sessions

    @classmethod
    def get_session(cls, session_id: str) -> REPLSession:
        with cls._lock:
            if session_id not in cls._sessions:
                raise KeyError(f"REPL session not found: {session_id}")
            return cls._sessions[session_id]

    @classmethod
    def delete_session(cls, session_id: str | None) -> None:
        if not session_id:
            return
        with cls._lock:
            cls._sessions.pop(session_id, None)

    @classmethod
    def clear(cls) -> None:
        with cls._lock:
            cls._sessions.clear()

    @classmethod
    def session_count(cls) -> int:
        with cls._lock:
            return len(cls._sessions)


__all__ = [
    "REPLExecutionResult",
    "REPLRegistry",
    "REPLSession",
    "extract_repl_blocks",
    "truncate_text",
]

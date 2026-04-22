"""Compatibility shim for the Claude Code runtime adapter."""

from __future__ import annotations

import json
import logging
import os
from typing import Optional

import flatagents.adapters.claude_code as _impl
from flatagents.adapters import create_claude_code_executor

from ..agents import AgentAdapter, AgentAdapterContext, AgentExecutor, AgentRef

logger = logging.getLogger("flatmachines.adapters.claude_code")
_impl.logger = logger

class ClaudeCodeExecutor(_impl.ClaudeCodeExecutor):
    async def _invoke_once(self, *args, **kwargs):
        _impl._termios = _termios
        return await super()._invoke_once(*args, **kwargs)


_StreamCollector = _impl._StreamCollector
_map_stop_reason = _impl._map_stop_reason
_build_rate_limit_from_events = _impl._build_rate_limit_from_events
_termios = _impl._termios
_DEFAULT_MODEL = _impl._DEFAULT_MODEL
_DEFAULT_EFFORT = _impl._DEFAULT_EFFORT
_DEFAULT_EXIT_SENTINEL = _impl._DEFAULT_EXIT_SENTINEL
_DEFAULT_CONTINUATION_PROMPT = _impl._DEFAULT_CONTINUATION_PROMPT
_DEFAULT_MAX_CONTINUATIONS = _impl._DEFAULT_MAX_CONTINUATIONS
_DEFAULT_RATE_LIMIT_DELAY = _impl._DEFAULT_RATE_LIMIT_DELAY
_DEFAULT_RATE_LIMIT_JITTER = _impl._DEFAULT_RATE_LIMIT_JITTER


class ClaudeCodeAdapter(AgentAdapter):
    type_name = "claude-code"

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
        settings = context.settings.get("agent_runners", {}).get("claude_code", {})
        return ClaudeCodeExecutor(
            config=config,
            config_dir=context.config_dir,
            settings=settings,
        )

    @staticmethod
    def _load_ref(ref: str, config_dir: str) -> Optional[dict]:
        if os.path.isabs(ref):
            path = ref
        else:
            path = os.path.join(config_dir, ref)
        if not os.path.isfile(path):
            return None
        with open(path, "r") as f:
            if path.endswith(".json"):
                return json.load(f)
            try:
                import yaml as _yaml
                return _yaml.safe_load(f)
            except ImportError:
                raise ImportError(f"pyyaml is required to load YAML agent config: {path}")


__all__ = [
    "ClaudeCodeAdapter",
    "ClaudeCodeExecutor",
    "_StreamCollector",
    "_map_stop_reason",
    "_build_rate_limit_from_events",
    "_termios",
    "_DEFAULT_MODEL",
    "_DEFAULT_EFFORT",
    "_DEFAULT_EXIT_SENTINEL",
    "_DEFAULT_CONTINUATION_PROMPT",
    "_DEFAULT_MAX_CONTINUATIONS",
    "_DEFAULT_RATE_LIMIT_DELAY",
    "_DEFAULT_RATE_LIMIT_JITTER",
]

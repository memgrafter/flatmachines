"""Compatibility shim for the Codex CLI runtime adapter."""

from __future__ import annotations

import json
import logging
import os
from typing import Optional

import flatagents.adapters.codex_cli as _impl
from flatagents.adapters import create_codex_cli_executor

from ..agents import AgentAdapter, AgentAdapterContext, AgentExecutor, AgentRef

logger = logging.getLogger("flatmachines.adapters.codex_cli")
_impl.logger = logger

CodexCliExecutor = _impl.CodexCliExecutor
CodexAppServerTransport = _impl.CodexAppServerTransport
_ExecStreamCollector = _impl._ExecStreamCollector
_DEFAULT_MODEL = _impl._DEFAULT_MODEL
_DEFAULT_REASONING_EFFORT = _impl._DEFAULT_REASONING_EFFORT
_DEFAULT_SANDBOX = _impl._DEFAULT_SANDBOX
_DEFAULT_APPROVAL = _impl._DEFAULT_APPROVAL


class CodexCliAdapter(AgentAdapter):
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
        return create_codex_cli_executor(
            config=config,
            config_dir=context.config_dir,
            settings=settings,
        )

    @staticmethod
    def _load_ref(ref: str, config_dir: str) -> Optional[dict]:
        expanded = os.path.expanduser(ref)
        if os.path.isabs(expanded):
            path = expanded
        else:
            path = os.path.join(config_dir, expanded)
        if not os.path.isfile(path):
            raise FileNotFoundError(f"Codex CLI agent config file not found: {path}")
        with open(path, "r") as f:
            if path.endswith(".json"):
                return json.load(f)
            try:
                import yaml as _yaml
                return _yaml.safe_load(f)
            except ImportError:
                raise ImportError(f"pyyaml is required to load YAML agent config: {path}")


__all__ = [
    "CodexCliAdapter",
    "CodexCliExecutor",
    "CodexAppServerTransport",
    "_ExecStreamCollector",
    "_DEFAULT_MODEL",
    "_DEFAULT_REASONING_EFFORT",
    "_DEFAULT_SANDBOX",
    "_DEFAULT_APPROVAL",
]

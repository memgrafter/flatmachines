"""Compatibility shim for the smolagents runtime adapter."""

from __future__ import annotations

from typing import Any, Dict, Optional

from flatagents.adapters.smolagents import *  # noqa: F401,F403
from flatagents.adapters import create_smolagents_executor

from ..agents import AgentAdapter, AgentAdapterContext, AgentExecutor, AgentRef


class SmolagentsAdapter(AgentAdapter):
    type_name = "smolagents"

    def create_executor(
        self,
        *,
        agent_name: str,
        agent_ref: AgentRef,
        context: AgentAdapterContext,
    ) -> AgentExecutor:
        if not agent_ref.ref:
            raise ValueError(f"smolagents reference missing ref for agent '{agent_name}'")
        return create_smolagents_executor(
            ref=agent_ref.ref,
            config_dir=context.config_dir,
            config=agent_ref.config,
        )

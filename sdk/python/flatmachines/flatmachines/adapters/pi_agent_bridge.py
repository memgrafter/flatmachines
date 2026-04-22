"""Compatibility shim for the pi-agent bridge adapter."""

from __future__ import annotations

from flatagents.adapters.pi_agent_bridge import *  # noqa: F401,F403
from flatagents.adapters import create_pi_agent_bridge_executor

from ..agents import AgentAdapter, AgentAdapterContext, AgentExecutor, AgentRef


class PiAgentBridgeAdapter(AgentAdapter):
    type_name = "pi-agent"

    def create_executor(
        self,
        *,
        agent_name: str,
        agent_ref: AgentRef,
        context: AgentAdapterContext,
    ) -> AgentExecutor:
        if not agent_ref.ref:
            raise ValueError(f"pi-agent reference missing ref for agent '{agent_name}'")
        settings = context.settings.get("agent_runners", {}).get("pi_agent", {})
        return create_pi_agent_bridge_executor(
            ref=agent_ref.ref,
            config=agent_ref.config,
            config_dir=context.config_dir,
            settings=settings,
        )

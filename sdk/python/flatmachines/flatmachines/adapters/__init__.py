"""Adapter registry helpers for FlatMachines."""

from __future__ import annotations

from typing import Optional

from ..agents import AgentAdapterRegistry


def register_builtin_adapters(registry: AgentAdapterRegistry) -> None:
    """Register built-in adapters if their dependencies are installed."""
    try:
        from .flatagent import FlatAgentAdapter

        registry.register(FlatAgentAdapter())
    except ImportError:
        pass

    try:
        from .smolagents import SmolagentsAdapter

        registry.register(SmolagentsAdapter())
    except ImportError:
        pass

    try:
        from .pi_agent_bridge import PiAgentBridgeAdapter

        registry.register(PiAgentBridgeAdapter())
    except ImportError:
        pass

    try:
        from .claude_code import ClaudeCodeAdapter

        registry.register(ClaudeCodeAdapter())
    except ImportError:
        pass


def create_registry(with_builtins: bool = True) -> AgentAdapterRegistry:
    registry = AgentAdapterRegistry()
    if with_builtins:
        register_builtin_adapters(registry)
    return registry

"""Single-agent runtime adapters for FlatAgents."""

from .claude_code import ClaudeCodeExecutor, create_claude_code_executor
from .codex_cli import CodexCliExecutor, CodexAppServerTransport, create_codex_cli_executor
from .pi_agent_bridge import PiAgentBridgeExecutor, create_pi_agent_bridge_executor
from .claude_code_sessions import SessionHoldback as ClaudeCodeSessionHoldback, ForkResult as ClaudeCodeForkResult
from .codex_cli_sessions import CodexSessionHoldback, ForkResult as CodexForkResult

__all__ = [
    "ClaudeCodeExecutor",
    "create_claude_code_executor",
    "CodexCliExecutor",
    "CodexAppServerTransport",
    "create_codex_cli_executor",
    "PiAgentBridgeExecutor",
    "create_pi_agent_bridge_executor",
    "ClaudeCodeSessionHoldback",
    "ClaudeCodeForkResult",
    "CodexSessionHoldback",
    "CodexForkResult",
]

try:
    from .smolagents import SmolagentsExecutor, create_smolagents_executor

    __all__.extend([
        "SmolagentsExecutor",
        "create_smolagents_executor",
    ])
except ImportError:  # pragma: no cover - optional dependency
    SmolagentsExecutor = None  # type: ignore[assignment]
    create_smolagents_executor = None  # type: ignore[assignment]

"""Provider exports.

Includes provider-specific rate-limit helpers and first-class OAuth backends
for OpenAI Codex and GitHub Copilot.
"""

from .cerebras import CerebrasRateLimits, extract_cerebras_rate_limits
from .anthropic import AnthropicRateLimits, extract_anthropic_rate_limits
from .openai import OpenAIRateLimits, extract_openai_rate_limits
from .github_copilot_auth import CopilotAuthError
from .github_copilot_client import CopilotClient, CopilotClientError, CopilotHTTPError
from .github_copilot_types import CopilotOAuthCredential, CopilotResult, CopilotToolCall, CopilotUsage
from .openai_codex_auth import CodexAuthError
from .openai_codex_client import CodexClient, CodexClientError, CodexHTTPError
from .openai_codex_types import CodexOAuthCredential, CodexResult, CodexToolCall, CodexUsage

__all__ = [
    # Cerebras
    "CerebrasRateLimits",
    "extract_cerebras_rate_limits",
    # Anthropic
    "AnthropicRateLimits",
    "extract_anthropic_rate_limits",
    # OpenAI
    "OpenAIRateLimits",
    "extract_openai_rate_limits",
    # OpenAI Codex
    "CodexAuthError",
    "CodexClient",
    "CodexClientError",
    "CodexHTTPError",
    "CodexOAuthCredential",
    "CodexResult",
    "CodexToolCall",
    "CodexUsage",
    # GitHub Copilot
    "CopilotAuthError",
    "CopilotClient",
    "CopilotClientError",
    "CopilotHTTPError",
    "CopilotOAuthCredential",
    "CopilotResult",
    "CopilotToolCall",
    "CopilotUsage",
]

"""
Provider-specific rate limit extraction utilities.

These utilities extract provider-specific details from the raw_headers
field of RateLimitInfo. Use them when you need provider-specific
information beyond the normalized core fields.

Example:
    from flatagents import extract_cerebras_rate_limits
    
    response = await agent.call(prompt="Hello")
    if response.rate_limit and response.rate_limit.raw_headers:
        cerebras = extract_cerebras_rate_limits(response.rate_limit.raw_headers)
        if cerebras.remaining_tokens_minute == 0:
            print("Minute limit hit")
"""

from .cerebras import CerebrasRateLimits, extract_cerebras_rate_limits
from .anthropic import AnthropicRateLimits, extract_anthropic_rate_limits
from .openai import OpenAIRateLimits, extract_openai_rate_limits
from .openai_codex_auth import CodexAuthError
from .openai_codex_client import CodexClient, CodexClientError, CodexHTTPError
from .openai_codex_types import CodexOAuthCredential, CodexResult, CodexToolCall, CodexUsage
from .anthropic_claude_code_auth import ClaudeCodeAuthError
from .anthropic_claude_code_client import ClaudeCodeClient, ClaudeCodeClientError, ClaudeCodeHTTPError
from .anthropic_claude_code_types import ClaudeCodeOAuthCredential, ClaudeCodeResult, ClaudeCodeToolCall, ClaudeCodeUsage

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
    # Anthropic Claude Code
    "ClaudeCodeAuthError",
    "ClaudeCodeClient",
    "ClaudeCodeClientError",
    "ClaudeCodeHTTPError",
    "ClaudeCodeOAuthCredential",
    "ClaudeCodeResult",
    "ClaudeCodeToolCall",
    "ClaudeCodeUsage",
]

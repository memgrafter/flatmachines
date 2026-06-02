__version__ = "4.2.1"

from .baseagent import (
    # Base agent (abstract, for multi-step agents)
    FlatAgent as BaseFlatAgent,
    # LLM Backends
    LLMBackend,
    LiteLLMBackend,
    AISuiteBackend,
    # Extractors
    Extractor,
    FreeExtractor,
    FreeThinkingExtractor,
    StructuredExtractor,
    ToolsExtractor,
    RegexExtractor,
    # MCP Types
    MCPToolProvider,
    ToolCall,
    AgentResponse,
    # Response data classes
    UsageInfo,
    CostInfo,
    RateLimitInfo,
    ErrorInfo,
    FinishReason,
    # Header extraction utilities
    extract_headers_from_response,
    extract_headers_from_error,
    extract_rate_limit_info,
    extract_status_code,
    is_retryable_error,
)
from .flatagent import FlatAgent
from .profiles import (
    ProfileManager,
    resolve_model_config,
    load_profile_from_file,
    resolve_profile_config,
)
from .validation import (
    validate_flatagent_config,
    get_flatagent_schema,
    get_asset,
    ValidationWarning,
)
from .monitoring import (
    setup_logging,
    get_logger,
    get_meter,
    AgentMonitor,
    track_operation,
)
from .tools import (
    ToolResult,
    ToolProvider,
    SimpleToolProvider,
)
from .tool_loop import (
    ToolLoopAgent,
    Tool,
    Guardrails,
    ToolLoopResult,
    AggregateUsage,
    StopReason,
    SteeringProvider,
)
from .adapters import (
    ClaudeCodeExecutor,
    create_claude_code_executor,
    CodexCliExecutor,
    CodexAppServerTransport,
    create_codex_cli_executor,
    SmolagentsExecutor,
    create_smolagents_executor,
    PiAgentBridgeExecutor,
    create_pi_agent_bridge_executor,
    ClaudeCodeSessionHoldback,
    ClaudeCodeForkResult,
    CodexSessionHoldback,
    CodexForkResult,
)
# Provider-specific utilities
from .providers import (
    CerebrasRateLimits,
    extract_cerebras_rate_limits,
    AnthropicRateLimits,
    extract_anthropic_rate_limits,
    OpenAIRateLimits,
    extract_openai_rate_limits,
    CodexAuthError,
    CodexClient,
    CodexClientError,
    CodexHTTPError,
    CodexOAuthCredential,
    CodexResult,
    CodexToolCall,
    CodexUsage,
    CopilotAuthError,
    CopilotClient,
    CopilotClientError,
    CopilotHTTPError,
    CopilotOAuthCredential,
    CopilotResult,
    CopilotToolCall,
    CopilotUsage,
)

__all__ = [
    "__version__",
    # Main agent class
    "FlatAgent",
    # Base agent for custom multi-step agents
    "BaseFlatAgent",
    # LLM Backends
    "LLMBackend",
    "LiteLLMBackend",
    "AISuiteBackend",
    # Extractors
    "Extractor",
    "FreeExtractor",
    "FreeThinkingExtractor",
    "StructuredExtractor",
    "ToolsExtractor",
    "RegexExtractor",
    # MCP Types
    "MCPToolProvider",
    "ToolCall",
    "AgentResponse",
    # Response data classes
    "UsageInfo",
    "CostInfo",
    "RateLimitInfo",
    "ErrorInfo",
    "FinishReason",
    # Header extraction utilities
    "extract_headers_from_response",
    "extract_headers_from_error",
    "extract_rate_limit_info",
    "extract_status_code",
    "is_retryable_error",
    # Provider-specific utilities
    "CerebrasRateLimits",
    "extract_cerebras_rate_limits",
    "AnthropicRateLimits",
    "extract_anthropic_rate_limits",
    "OpenAIRateLimits",
    "extract_openai_rate_limits",
    "CodexAuthError",
    "CodexClient",
    "CodexClientError",
    "CodexHTTPError",
    "CodexOAuthCredential",
    "CodexResult",
    "CodexToolCall",
    "CodexUsage",
    "CopilotAuthError",
    "CopilotClient",
    "CopilotClientError",
    "CopilotHTTPError",
    "CopilotOAuthCredential",
    "CopilotResult",
    "CopilotToolCall",
    "CopilotUsage",
    # Validation
    "validate_flatagent_config",
    "get_flatagent_schema",
    "get_asset",
    "ValidationWarning",
    # Monitoring & Observability
    "setup_logging",
    "get_logger",
    "get_meter",
    "AgentMonitor",
    "track_operation",
    # Model Profiles
    "ProfileManager",
    "resolve_model_config",
    "load_profile_from_file",
    "resolve_profile_config",
    # Runtime adapters
    "ClaudeCodeExecutor",
    "create_claude_code_executor",
    "CodexCliExecutor",
    "CodexAppServerTransport",
    "create_codex_cli_executor",
    "SmolagentsExecutor",
    "create_smolagents_executor",
    "PiAgentBridgeExecutor",
    "create_pi_agent_bridge_executor",
    "ClaudeCodeSessionHoldback",
    "ClaudeCodeForkResult",
    "CodexSessionHoldback",
    "CodexForkResult",
    # Tool Use
    "ToolResult",
    "ToolProvider",
    "SimpleToolProvider",
    "ToolLoopAgent",
    "Tool",
    "Guardrails",
    "ToolLoopResult",
    "AggregateUsage",
    "StopReason",
    "SteeringProvider",
]

__version__ = "0.3.4"

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
)
from .flatagent import FlatAgent
from .flatmachine import FlatMachine
from .hooks import (
    MachineHooks,
    LoggingHooks,
    MetricsHooks,
    CompositeHooks,
)
from .expressions import get_expression_engine, ExpressionEngine
from .execution import (
    ExecutionType,
    DefaultExecution,
    ParallelExecution,
    RetryExecution,
    MDAPVotingExecution,
    get_execution_type,
)
from .validation import (
    validate_flatagent_config,
    validate_flatmachine_config,
    get_flatagent_schema,
    get_flatmachine_schema,
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

__all__ = [
    "__version__",
    # Main agent class
    "FlatAgent",
    # Base agent for custom multi-step agents
    "BaseFlatAgent",
    # State machine orchestration
    "FlatMachine",
    # Machine hooks
    "MachineHooks",
    "LoggingHooks",
    "MetricsHooks",
    "CompositeHooks",
    # Expression engines
    "ExpressionEngine",
    "get_expression_engine",
    # Execution types
    "ExecutionType",
    "DefaultExecution",
    "ParallelExecution",
    "RetryExecution",
    "MDAPVotingExecution",
    "get_execution_type",
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
    # Validation
    "validate_flatagent_config",
    "validate_flatmachine_config",
    "get_flatagent_schema",
    "get_flatmachine_schema",
    "get_asset",
    "ValidationWarning",
    # Monitoring & Observability
    "setup_logging",
    "get_logger",
    "get_meter",
    "AgentMonitor",
    "track_operation",
]

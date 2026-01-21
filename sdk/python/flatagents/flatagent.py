"""
FlatAgent - Single-call agent implementation.

A single-call agent executes one prompt/response cycle with optional:
- Input/output schemas
- Response extraction (free, structured, tools, regex)
- MCP tool integration
"""

import asyncio
import json
import os
from typing import Any, Dict, List, Optional, Tuple

from . import __version__
from .monitoring import get_logger
from .utils import strip_markdown_json, check_spec_version
from .baseagent import (
    FlatAgent as BaseFlatAgent,
    LLMBackend,
    LiteLLMBackend,
    AISuiteBackend,
    Extractor,
    FreeExtractor,
    FreeThinkingExtractor,
    StructuredExtractor,
    ToolsExtractor,
    RegexExtractor,
    MCPToolProvider,
    AgentResponse,
    ToolCall,
)

logger = get_logger(__name__)

try:
    import jinja2
except ImportError:
    jinja2 = None

try:
    import litellm
except ImportError:
    litellm = None

try:
    import aisuite
except ImportError:
    aisuite = None


class FlatAgent:
    """
    A single LLM call configured entirely via YAML. No code required.

    v0.6.0 Container format:

        spec: flatagent
        spec_version: "0.6.0"

        data:
          name: greeter

          model:
            provider: cerebras
            name: zai-glm-4.6
            temperature: 0.7

          system: "You are a friendly greeter."

          user: |
            Greet the user named {{ input.name }}.

          output:
            greeting:
              type: str
              description: "A friendly greeting message"

          # Optional MCP configuration
          mcp:
            servers:
              filesystem:
                command: npx
                args: ["-y", "@modelcontextprotocol/server-filesystem", "/docs"]
            tool_filter:
              allow: ["filesystem:read_file"]
            tool_prompt: |
              You have access to these tools:
              {% for tool in tools %}
              - {{ tool.name }}: {{ tool.description }}
              {% endfor %}

        metadata:
          author: "your-name"

    Example usage:
        from flatagents import setup_logging, get_logger
        setup_logging(level="INFO")
        logger = get_logger(__name__)

        agent = FlatAgent(config_file="agent.yaml")
        result = await agent.call(name="Alice")
        logger.info(f"Result: {result}")

    Example with MCP:
        from flatagents import FlatAgent, MCPToolProvider

        agent = FlatAgent(config_file="agent.yaml")
        provider = MyMCPProvider()  # User implements MCPToolProvider protocol
        result = await agent.call(tool_provider=provider, question="List files")

        if result.tool_calls:
            for tc in result.tool_calls:
                tool_result = provider.call_tool(tc.server, tc.tool, tc.arguments)
                # Handle tool result...
    """

    DEFAULT_SYSTEM_PROMPT = "You are a helpful assistant."

    def __init__(
        self,
        config_file: Optional[str] = None,
        config_dict: Optional[Dict] = None,
        tool_provider: Optional["MCPToolProvider"] = None,
        backend: Optional[str] = None,
        profiles_file: Optional[str] = None,
        profiles_dict: Optional[Dict] = None,
        **kwargs
    ):
        if jinja2 is None:
            raise ImportError("jinja2 is required for FlatAgent. Install with: pip install jinja2")

        self._profiles_file = profiles_file
        self._profiles_dict = profiles_dict
        self._load_config(config_file, config_dict, **kwargs)
        self._validate_spec()
        self._parse_agent_config()

        # Determine backend: explicit param > config > auto-detect
        # model can be a string (profile name) or dict (inline config)
        model_config = self.config.get('data', {}).get('model', {})
        config_backend = model_config.get('backend') if isinstance(model_config, dict) else None
        self._backend = backend or config_backend or self._auto_detect_backend()
        self._init_backend()

        # MCP support
        self._tool_provider = tool_provider
        self._tools_cache: Optional[List[Dict]] = None

        # Tracking
        self.total_cost = 0.0
        self.total_api_calls = 0

        logger.info(f"Initialized FlatAgent: {self.agent_name} (backend: {self._backend})")

    def _auto_detect_backend(self) -> str:
        """
        Auto-detect available LLM backend.
        
        Priority:
        1. FLATAGENTS_BACKEND env var (e.g., "litellm" or "aisuite")
        2. litellm if installed (preferred for stability)
        3. aisuite if installed
        """
        # Check env var first (SDK-specific override, not in config)
        env_backend = os.environ.get("FLATAGENTS_BACKEND", "").lower()
        if env_backend in ("litellm", "aisuite"):
            return env_backend
        
        # Prefer litellm for stability
        if litellm is not None:
            return "litellm"
        if aisuite is not None:
            return "aisuite"
        raise ImportError(
            "No LLM backend available. Install one of:\n"
            "  pip install litellm    (recommended)\n"
            "  pip install aisuite"
        )

    def _init_backend(self) -> None:
        """Initialize the selected backend."""
        if self._backend == "aisuite":
            if aisuite is None:
                raise ImportError("aisuite backend selected but not installed. Install with: pip install aisuite")
            self._aisuite_client = aisuite.Client()
        elif self._backend == "litellm":
            if litellm is None:
                raise ImportError("litellm backend selected but not installed. Install with: pip install litellm")
        else:
            raise ValueError(f"Unknown backend: {self._backend}. Use 'aisuite' or 'litellm'.")

    async def _call_llm(self, params: Dict[str, Any]) -> Any:
        """Call the LLM using the selected backend."""
        import asyncio

        if self._backend == "aisuite":
            return await self._call_aisuite(params)
        else:
            return await litellm.acompletion(**params)

    async def _call_aisuite(self, params: Dict[str, Any]) -> Any:
        """Call LLM via aisuite backend."""
        import asyncio

        model = params["model"]
        if "/" in model:
            model = model.replace("/", ":", 1)

        provider_key, model_name = model.split(":", 1)

        # WORKAROUND: aisuite drops tools unless max_turns is set.
        # Use direct provider call for Cerebras.
        if provider_key == "cerebras":
            return await self._call_aisuite_cerebras_direct(model_name, params)

        call_params = {
            "model": model,
            "messages": params["messages"],
            "temperature": params.get("temperature", 0.7),
            "max_tokens": params.get("max_tokens", 2048),
        }
        if "tools" in params:
            call_params["tools"] = params["tools"]

        response = await asyncio.to_thread(
            self._aisuite_client.chat.completions.create,
            **call_params
        )

        return response

    async def _call_aisuite_cerebras_direct(self, model_name: str, params: Dict[str, Any]) -> Any:
        """Direct Cerebras provider call. Workaround for aisuite dropping tools."""
        import asyncio
        from aisuite.provider import ProviderFactory

        config = self._aisuite_client.provider_configs.get("cerebras", {})
        provider = ProviderFactory.create_provider("cerebras", config)

        kwargs = {
            "temperature": params.get("temperature", 0.7),
            "max_tokens": params.get("max_tokens", 2048),
        }
        if "tools" in params:
            kwargs["tools"] = params["tools"]

        response = await asyncio.to_thread(
            provider.chat_completions_create,
            model_name,
            params["messages"],
            **kwargs
        )

        return response

    def _load_config(
        self,
        config_file: Optional[str],
        config_dict: Optional[Dict],
        **kwargs
    ):
        """Load v0.6.0 container config with profile resolution."""
        import os
        try:
            import yaml
        except ImportError:
            yaml = None

        config = {}
        config_dir = os.getcwd()

        if config_file is not None:
            if not os.path.exists(config_file):
                raise FileNotFoundError(f"Configuration file not found: {config_file}")
            with open(config_file, 'r') as f:
                if config_file.endswith('.json'):
                    config = json.load(f) or {}
                else:
                    if yaml is None:
                        raise ImportError("pyyaml is required for YAML config files.")
                    config = yaml.safe_load(f) or {}
            config_dir = os.path.dirname(os.path.abspath(config_file))
        elif config_dict is not None:
            config = config_dict

        self.config = config
        self._config_dir = config_dir

        # Always discover own profiles first; own wins, parent is fallback only
        from .profiles import discover_profiles_file, load_profiles_from_file, resolve_profiles_with_fallback
        parent_profiles_dict = self._profiles_dict
        self._profiles_file = discover_profiles_file(self._config_dir, self._profiles_file)
        own_profiles_dict = load_profiles_from_file(self._profiles_file) if self._profiles_file else None
        self._profiles_dict = resolve_profiles_with_fallback(own_profiles_dict, parent_profiles_dict)

        # Extract model config from data section
        data = config.get('data', {})
        raw_model_config = data.get('model', {})

        # Resolve model config through profiles
        from .profiles import resolve_model_config
        model_config = resolve_model_config(
            raw_model_config,
            config_dir,
            profiles_dict=self._profiles_dict
        )

        # Build model name from provider/name
        provider = model_config.get('provider')
        model_name = model_config.get('name')
        if provider and model_name and '/' not in model_name:
            full_model_name = f"{provider}/{model_name}"
        else:
            full_model_name = model_name

        # Set model attributes (with kwargs override)
        self.model = kwargs.get('model', full_model_name)
        self.temperature = kwargs.get('temperature', model_config.get('temperature', 0.7))
        self.max_tokens = kwargs.get('max_tokens', model_config.get('max_tokens', 2048))

        # Extended model config fields
        self.top_p = kwargs.get('top_p', model_config.get('top_p'))
        self.top_k = kwargs.get('top_k', model_config.get('top_k'))
        self.frequency_penalty = kwargs.get('frequency_penalty', model_config.get('frequency_penalty'))
        self.presence_penalty = kwargs.get('presence_penalty', model_config.get('presence_penalty'))
        self.seed = kwargs.get('seed', model_config.get('seed'))
        self.base_url = kwargs.get('base_url', model_config.get('base_url'))

        # Store full model config for template access (includes custom fields)
        self._model_config_raw = model_config

    def _validate_spec(self):
        """Validate the spec envelope."""
        config = self.config

        if config.get('spec') != 'flatagent':
            raise ValueError(
                f"Invalid spec: expected 'flatagent', got '{config.get('spec')}'. "
                "Config must have: spec: flatagent"
            )

        if 'data' not in config:
            raise ValueError("Config missing 'data' section")

        # Version check with warning
        self.spec_version = check_spec_version(config.get('spec_version'), __version__)

        # Schema validation (warnings only, non-blocking)
        try:
            from .validation import validate_flatagent_config
            validate_flatagent_config(config, warn=True, strict=False)
        except ImportError:
            pass  # jsonschema not installed, skip validation

    def _parse_agent_config(self):
        """Parse the v0.6.0 flatagent configuration."""
        data = self.config['data']
        self.metadata = self.config.get('metadata', {})

        # Agent name
        self.agent_name = data.get('name') or self.metadata.get('name', 'unnamed-agent')

        # Prompts
        self._system_prompt_template = data.get('system', self.DEFAULT_SYSTEM_PROMPT)
        self._user_prompt_template = data.get('user', '')
        self._instruction_suffix = data.get('instruction_suffix', '')

        # Compile Jinja2 templates
        self._jinja_env = jinja2.Environment()
        self._compiled_system = self._jinja_env.from_string(self._system_prompt_template)
        self._compiled_user = self._jinja_env.from_string(self._user_prompt_template)

        # Output schema (stored for reference, extraction uses json_object mode)
        self.output_schema = data.get('output', {})

        # MCP configuration
        self.mcp_config = data.get('mcp')

    # ─────────────────────────────────────────────────────────────────────────
    # MCP Tool Support
    # ─────────────────────────────────────────────────────────────────────────

    def set_tool_provider(self, provider: "MCPToolProvider") -> None:
        """
        Set the MCP tool provider.

        Args:
            provider: An object implementing the MCPToolProvider protocol
        """
        self._tool_provider = provider
        self._tools_cache = None  # Clear cache when provider changes

    def _discover_tools(self) -> List[Dict[str, Any]]:
        """
        Discover and filter tools from configured MCP servers.

        Tools are cached for the lifetime of this agent instance.
        Call set_tool_provider() to reset the cache.

        Returns:
            List of tool definitions with '_server' and '_qualified' metadata
        """
        if self._tools_cache is not None:
            return self._tools_cache

        if not self.mcp_config or not self._tool_provider:
            return []

        tools = []
        servers = self.mcp_config.get('servers', {})
        tool_filter = self.mcp_config.get('tool_filter', {})

        for server_name, server_config in servers.items():
            # Connect to server if not already connected
            self._tool_provider.connect(server_name, server_config)

            # Get tools from this server
            try:
                server_tools = self._tool_provider.get_tools(server_name)
            except Exception as e:
                logger.warning(f"Failed to get tools from server '{server_name}': {e}")
                continue

            for tool in server_tools:
                qualified_name = f"{server_name}:{tool['name']}"
                if self._passes_filter(qualified_name, tool_filter):
                    tools.append({
                        **tool,
                        '_server': server_name,
                        '_qualified': qualified_name
                    })

        self._tools_cache = tools
        logger.info(f"Discovered {len(tools)} tools from {len(servers)} MCP server(s)")
        return tools

    def _passes_filter(self, qualified_name: str, filter_config: Dict) -> bool:
        """
        Check if a tool passes the allow/deny filters.

        Args:
            qualified_name: Tool name in "server:tool" format
            filter_config: Dict with optional 'allow' and 'deny' lists

        Returns:
            True if tool should be included
        """
        allow = filter_config.get('allow', [])
        deny = filter_config.get('deny', [])

        # Deny takes precedence
        for pattern in deny:
            if self._match_pattern(qualified_name, pattern):
                return False

        # If allow list exists, must match at least one pattern
        if allow:
            return any(self._match_pattern(qualified_name, p) for p in allow)

        # No allow list = allow all (that aren't denied)
        return True

    def _match_pattern(self, name: str, pattern: str) -> bool:
        """
        Match a qualified name against a pattern.

        Supports:
        - Exact match: "server:tool"
        - Wildcard: "server:*" matches all tools from server

        Args:
            name: Qualified tool name ("server:tool")
            pattern: Pattern to match against

        Returns:
            True if name matches pattern
        """
        if pattern.endswith(':*'):
            return name.startswith(pattern[:-1])
        return name == pattern

    def _render_tool_prompt(self, tools: List[Dict]) -> str:
        """
        Render the tool_prompt template from the spec.

        Args:
            tools: List of discovered tool definitions

        Returns:
            Rendered tool prompt string, or empty string if no tools/template
        """
        if not tools or not self.mcp_config:
            return ""

        tool_prompt_template = self.mcp_config.get('tool_prompt', '')
        if not tool_prompt_template:
            return ""

        template = self._jinja_env.from_string(tool_prompt_template)
        return template.render(tools=tools)

    def _convert_tools_for_llm(self, tools: List[Dict]) -> List[Dict]:
        """
        Convert MCP tool schemas to OpenAI function calling format.

        Args:
            tools: List of MCP tool definitions

        Returns:
            List of tools in OpenAI function format
        """
        return [
            {
                "type": "function",
                "function": {
                    "name": t['name'],
                    "description": t.get('description', ''),
                    "parameters": t.get('inputSchema', {"type": "object", "properties": {}})
                }
            }
            for t in tools
        ]

    def _find_tool_server(self, tool_name: str, tools: List[Dict]) -> str:
        """
        Find which server a tool belongs to.

        Args:
            tool_name: Name of the tool
            tools: List of discovered tools with '_server' metadata

        Returns:
            Server name, or empty string if not found
        """
        for tool in tools:
            if tool['name'] == tool_name:
                return tool.get('_server', '')
        return ''

    # ─────────────────────────────────────────────────────────────────────────
    # Prompt Rendering
    # ─────────────────────────────────────────────────────────────────────────

    def _render_system_prompt(
        self,
        input_data: Dict[str, Any],
        tools_prompt: str = "",
        tools: Optional[List[Dict]] = None
    ) -> str:
        """
        Render system prompt with input data and optional tools context.

        Args:
            input_data: Input values for {{ input.* }}
            tools_prompt: Rendered tool prompt to inject
            tools: List of tool definitions (available as {{ tools }})

        Returns:
            Rendered system prompt
        """
        # Merge raw config with computed values for template access
        model_config = {
            **self._model_config_raw,
            "name": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "top_p": self.top_p,
            "top_k": self.top_k,
            "frequency_penalty": self.frequency_penalty,
            "presence_penalty": self.presence_penalty,
            "seed": self.seed,
            "base_url": self.base_url,
        }
        return self._compiled_system.render(
            input=input_data,
            tools_prompt=tools_prompt,
            tools=tools or [],
            model=model_config
        )

    def _render_user_prompt(
        self,
        input_data: Dict[str, Any],
        tools_prompt: str = "",
        tools: Optional[List[Dict]] = None
    ) -> str:
        """
        Render user prompt with input data and optional tools context.

        Args:
            input_data: Input values for {{ input.* }}
            tools_prompt: Rendered tool prompt (available as {{ tools_prompt }})
            tools: List of tool definitions (available as {{ tools }})

        Returns:
            Rendered user prompt
        """
        # Merge raw config with computed values for template access
        model_config = {
            **self._model_config_raw,
            "name": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "top_p": self.top_p,
            "top_k": self.top_k,
            "frequency_penalty": self.frequency_penalty,
            "presence_penalty": self.presence_penalty,
            "seed": self.seed,
            "base_url": self.base_url,
        }
        prompt = self._compiled_user.render(
            input=input_data,
            tools_prompt=tools_prompt,
            tools=tools or [],
            model=model_config
        )
        if self._instruction_suffix:
            prompt = f"{prompt}\n\n{self._instruction_suffix}"
        return prompt

    # ─────────────────────────────────────────────────────────────────────────
    # Execution
    # ─────────────────────────────────────────────────────────────────────────

    async def call(
        self,
        tool_provider: Optional["MCPToolProvider"] = None,
        messages: Optional[List[Dict[str, Any]]] = None,
        **input_data
    ) -> "AgentResponse":
        """
        Execute a single LLM call with the given input.

        Args:
            tool_provider: Optional MCPToolProvider (overrides constructor value)
            messages: Optional conversation history (for tool call continuations)
            **input_data: Input values available as {{ input.* }} in templates

        Returns:
            AgentResponse with content, output, and optionally tool_calls
        """
        from .baseagent import AgentResponse, ToolCall

        # Use provided tool provider or fall back to stored one
        if tool_provider is not None:
            self._tool_provider = tool_provider
            self._tools_cache = None  # Clear cache

        # Discover tools if MCP is configured
        tools = self._discover_tools()
        tools_prompt = self._render_tool_prompt(tools)

        # Render prompts
        system_prompt = self._render_system_prompt(input_data, tools_prompt=tools_prompt, tools=tools)
        user_prompt = self._render_user_prompt(input_data, tools_prompt=tools_prompt, tools=tools)

        # Build messages
        if messages:
            # Continue from provided message history
            all_messages = [{"role": "system", "content": system_prompt}] + messages
            # Only add user prompt if input_data was provided
            if input_data:
                all_messages.append({"role": "user", "content": user_prompt})
        else:
            all_messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]

        # Build LLM call parameters
        params = {
            "model": self.model,
            "messages": all_messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }

        # Add extended model parameters if set
        if self.top_p is not None:
            params["top_p"] = self.top_p
        if self.top_k is not None:
            params["top_k"] = self.top_k
        if self.frequency_penalty is not None:
            params["frequency_penalty"] = self.frequency_penalty
        if self.presence_penalty is not None:
            params["presence_penalty"] = self.presence_penalty
        if self.seed is not None:
            params["seed"] = self.seed
        if self.base_url is not None:
            params["api_base"] = self.base_url  # litellm uses api_base

        # Add tools if available
        if tools:
            params["tools"] = self._convert_tools_for_llm(tools)

        # Use JSON mode if we have an output schema and no tools
        if self.output_schema and not tools:
            params["response_format"] = {"type": "json_object"}

        # Call LLM via selected backend
        response = await self._call_llm(params)

        # Track usage
        self.total_api_calls += 1
        if hasattr(response, 'usage') and response.usage:
            input_tokens = getattr(response.usage, 'prompt_tokens', 0)
            output_tokens = getattr(response.usage, 'completion_tokens', 0)
            self.total_cost += (input_tokens * 0.001 + output_tokens * 0.002) / 1000

        # Extract response
        message = response.choices[0].message
        content = message.content

        # Parse output schema if applicable
        output = None
        if self.output_schema and content and not tools:
            try:
                # Strip markdown fences - LLMs sometimes wrap JSON in ```json blocks
                output = json.loads(strip_markdown_json(content))
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse JSON response: {content}")
                output = {"_raw": content}

        # Extract tool calls if present
        tool_calls = None
        if hasattr(message, 'tool_calls') and message.tool_calls:
            tool_calls = []
            for tc in message.tool_calls:
                tool_name = tc.function.name
                server = self._find_tool_server(tool_name, tools)

                try:
                    arguments = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    arguments = {}

                tool_calls.append(ToolCall(
                    id=tc.id,
                    server=server,
                    tool=tool_name,
                    arguments=arguments
                ))

        return AgentResponse(
            content=content,
            output=output,
            tool_calls=tool_calls,
            raw_response=response
        )

    def call_sync(
        self,
        tool_provider: Optional["MCPToolProvider"] = None,
        messages: Optional[List[Dict[str, Any]]] = None,
        **input_data
    ) -> "AgentResponse":
        """Synchronous wrapper for call()."""
        import asyncio
        return asyncio.run(self.call(tool_provider=tool_provider, messages=messages, **input_data))

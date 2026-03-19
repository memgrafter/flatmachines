"""
FlatMachine - State machine orchestration for agents.

A machine defines how agents are connected and executed:
states, transitions, conditions, and loops.

See local/flatmachines-plan.md for the full specification.
"""

import asyncio
import importlib
import json
import os
import re
import time
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, Dict, List, Optional

try:
    from jinja2 import Template
except ImportError:
    Template = None

try:
    import yaml
except ImportError:
    yaml = None

from . import __version__
from .monitoring import get_logger
from .utils import check_spec_version
from .expressions import get_expression_engine, ExpressionEngine
from .execution import get_execution_type, ExecutionType
from .hooks import MachineHooks, LoggingHooks, HooksRegistry
from .agents import (
    AgentAdapterContext,
    AgentAdapterRegistry,
    AgentExecutor,
    AgentResult,
    coerce_agent_result,
    normalize_agent_ref,
)

import uuid
from .persistence import (
    PersistenceBackend,
    LocalFileBackend,
    MemoryBackend,
    SQLiteCheckpointBackend,
    CheckpointManager,
    ConfigStore,
    MachineSnapshot,
    config_hash,
)
from .backends import (
    ResultBackend,
    InMemoryResultBackend,
    LaunchIntent,
    make_uri,
    get_default_result_backend,
)
from .locking import ExecutionLock, LocalFileLock, NoOpLock, SQLiteLeaseLock
from .signals import SignalBackend, TriggerBackend, NoOpTrigger
from .actions import (
    Action,
    HookAction,
    MachineInvoker,
    InlineInvoker,
    QueueInvoker,
)

logger = get_logger(__name__)


class WaitingForSignal(Exception):
    """Raised when a state hits wait_for with no signal available.

    The main loop catches this, checkpoints with waiting_channel, and returns.
    """
    def __init__(self, channel: str):
        self.channel = channel
        super().__init__(f"Waiting for signal on channel: {channel}")


class FlatMachine:
    """
    State machine orchestration for agents.

    Executes a sequence of states, evaluations transitions and
    managing context flow between agents.

    Supports:
    - Persistence (checkpoint/resume)
    - Concurrency control (locking)
    - Machine launching (peer machine execution)
    """

    def __init__(
        self,
        config_file: Optional[str] = None,
        config_dict: Optional[Dict] = None,
        hooks: Optional[MachineHooks] = None,
        hooks_registry: Optional[HooksRegistry] = None,
        persistence: Optional[PersistenceBackend] = None,
        lock: Optional[ExecutionLock] = None,
        invoker: Optional[MachineInvoker] = None,
        result_backend: Optional[ResultBackend] = None,
        signal_backend: Optional[SignalBackend] = None,
        trigger_backend: Optional[TriggerBackend] = None,
        agent_registry: Optional[AgentAdapterRegistry] = None,
        agent_adapters: Optional[list] = None,
        profiles_file: Optional[str] = None,
        tool_provider=None,
        config_store: Optional[ConfigStore] = None,
        **kwargs
    ):
        """
        Initialize the machine.

        Args:
            config_file: Path to YAML/JSON config file
            config_dict: Configuration dictionary
            hooks: Custom hooks for extensibility (bypasses registry)
            hooks_registry: Registry for resolving hooks by name from config
            persistence: Storage backend (overrides config)
            lock: Concurrency lock (overrides config)
            invoker: Strategy for invoking other machines
            result_backend: Backend for inter-machine result storage
            signal_backend: Signal storage for wait_for states (optional)
            trigger_backend: Trigger activation after signals (optional)
            agent_registry: Registry of agent adapters (optional)
            agent_adapters: List of agent adapters to register (optional)
            profiles_file: Optional profiles.yml path for adapters that use it
            tool_provider: Default ToolProvider for tool_loop states (optional)
            config_store: Content-addressed config store for cross-SDK resume (optional)
            **kwargs: Override config values
        """
        if Template is None:
            raise ImportError("jinja2 is required. Install with: pip install jinja2")

        # Extract execution_id if passed (for launched machines)
        self.execution_id = kwargs.pop('_execution_id', None) or str(uuid.uuid4())
        self.parent_execution_id = kwargs.pop('_parent_execution_id', None)

        # Extract _config_dir override (used for launched machines)
        config_dir_override = kwargs.pop('_config_dir', None)

        # Adapter-specific profile hints (optional, used by adapter implementations)
        self._profiles_dict = kwargs.pop('_profiles_dict', None)
        self._profiles_file = profiles_file or kwargs.pop('_profiles_file', None)

        self._load_config(config_file, config_dict)

        # Capture raw config for content-addressed config store
        self._config_raw: Optional[str] = self._capture_config_raw(config_file, config_dict)
        self._config_hash: Optional[str] = None  # Set on first checkpoint save

        # Allow launcher to override config_dir for launched machines
        if config_dir_override:
            self._config_dir = config_dir_override

        # Merge kwargs into config data (shallow merge)
        if kwargs and 'data' in self.config:
            self.config['data'].update(kwargs)
            
        self._validate_spec()
        self._parse_machine_config()

        # Set up Jinja2 environment with custom filters
        from jinja2 import Environment
        import json

        def _json_finalize(value):
            """Auto-serialize lists and dicts to JSON in Jinja2 output.

            This ensures {{ output.items }} renders as ["a", "b"] (valid JSON)
            instead of ['a', 'b'] (Python repr), allowing json.loads() to work.
            """
            if isinstance(value, (list, dict)):
                return json.dumps(value)
            return value

        self._jinja_env = Environment(finalize=_json_finalize)
        # Add fromjson filter for parsing JSON strings in templates
        # Usage: {% for item in context.items | fromjson %}
        self._jinja_env.filters['fromjson'] = json.loads

        # Set up expression engine
        expression_mode = self.data.get("expression_engine", "simple")
        self._expression_engine = get_expression_engine(expression_mode)

        # Hooks registry + resolution
        self._hooks_registry = hooks_registry or HooksRegistry()
        self._hooks = self._resolve_hooks(hooks)

        # Agent adapter registry
        if agent_registry is not None:
            self._agent_registry = agent_registry
        elif agent_adapters:
            self._agent_registry = AgentAdapterRegistry(agent_adapters)
        else:
            from .adapters import create_registry
            self._agent_registry = create_registry()

        # Agent executor cache
        self._agents: Dict[str, AgentExecutor] = {}

        # Execution tracking
        self.total_api_calls = 0
        self.total_cost = 0.0

        # Config store for cross-SDK resume (content-addressed)
        # Set before _initialize_persistence so sqlite can auto-wire it.
        self._config_store = config_store

        # Persistence & Locking
        self._initialize_persistence(persistence, lock)

        # Result backend for inter-machine communication
        self.result_backend = result_backend or get_default_result_backend()

        # Signal & trigger backends for wait_for states
        self.signal_backend = signal_backend
        self.trigger_backend = trigger_backend or NoOpTrigger()

        # Tool provider for tool_loop states
        self._tool_provider = tool_provider

        # Current step counter (used by tool loop for checkpoints)
        self._current_step = 0

        # Pending launches (outbox pattern)
        self._pending_launches: list[LaunchIntent] = []

        # Background tasks for fire-and-forget launches
        self._background_tasks: set[asyncio.Task] = set()

        # Invoker (for launching peer machines)
        self.invoker = invoker or InlineInvoker()

        logger.info(f"Initialized FlatMachine: {self.machine_name} (ID: {self.execution_id})")

    @property
    def agent_registry(self) -> AgentAdapterRegistry:
        return self._agent_registry

    def _initialize_persistence(
        self,
        persistence: Optional[PersistenceBackend],
        lock: Optional[ExecutionLock]
    ) -> None:
        """Initialize persistence and locking components.

        Supports declarative backend selection via config:
            backend: "memory" | "local" | "sqlite"

        For sqlite, reads ``db_path`` from config (falls back to
        env ``FLATMACHINES_DB_PATH``, then ``flatmachines.sqlite``).

        Raises ``ValueError`` for unrecognized backend types to prevent
        silent misconfiguration.
        """
        # Get config
        p_config = self.data.get('persistence', {})

        enabled = p_config.get('enabled', True)
        backend_type = p_config.get('backend', 'memory')

        # Resolve db_path for sqlite (config → env → default)
        db_path = (
            p_config.get('db_path')
            or os.environ.get('FLATMACHINES_DB_PATH')
            or 'flatmachines.sqlite'
        )

        # Persistence Backend
        if persistence:
            self.persistence = persistence
        elif not enabled:
            self.persistence = MemoryBackend()
        elif backend_type == 'local':
            self.persistence = LocalFileBackend()
        elif backend_type == 'memory':
            self.persistence = MemoryBackend()
        elif backend_type == 'sqlite':
            self.persistence = SQLiteCheckpointBackend(db_path=db_path)
        else:
            raise ValueError(
                f"Unknown persistence backend '{backend_type}'. "
                f"Supported backends: 'memory', 'local', 'sqlite'."
            )

        # Lock
        if lock:
            self.lock = lock
        elif not enabled:
            self.lock = NoOpLock()
        elif backend_type == 'local':
            self.lock = LocalFileLock()
        elif backend_type == 'sqlite':
            self.lock = SQLiteLeaseLock(
                db_path=db_path,
                owner_id=self.execution_id,
                phase="machine",
            )
        else:
            self.lock = NoOpLock()

        # Auto-wire config_store from SQLite persistence when absent
        if (
            self._config_store is None
            and isinstance(self.persistence, SQLiteCheckpointBackend)
        ):
            self._config_store = self.persistence.config_store

        # Checkpoint events (default set)
        default_events = ['machine_start', 'state_enter', 'execute', 'state_exit', 'machine_end', 'waiting', 'tool_call']
        self.checkpoint_events = set(p_config.get('checkpoint_on', default_events))

    def _build_machine_metadata(self, state_name: str) -> MappingProxyType:
        """Build immutable machine metadata for context.machine."""
        return MappingProxyType({
            "execution_id": self.execution_id,
            "machine_name": self.machine_name,
            "parent_execution_id": self.parent_execution_id,
            "spec_version": self.spec_version,
            "step": self._current_step,
            "current_state": state_name,
            "total_api_calls": self.total_api_calls,
            "total_cost": self.total_cost,
        })

    def _inject_machine_metadata(self, context: Dict[str, Any], state_name: str) -> Dict[str, Any]:
        """Inject immutable context.machine into context. Overwrites any existing value."""
        context["machine"] = self._build_machine_metadata(state_name)
        return context

    def _load_config(
        self,
        config_file: Optional[str],
        config_dict: Optional[Dict]
    ) -> None:
        """Load configuration from file or dict."""
        config = {}

        if config_file is not None:
            if not os.path.exists(config_file):
                raise FileNotFoundError(f"Config file not found: {config_file}")

            with open(config_file, 'r') as f:
                if config_file.endswith('.json'):
                    config = json.load(f) or {}
                else:
                    if yaml is None:
                        raise ImportError("pyyaml required for YAML files")
                    config = yaml.safe_load(f) or {}

            # Store config file path for relative agent references
            self._config_dir = os.path.dirname(os.path.abspath(config_file))
        elif config_dict is not None:
            config = config_dict
            self._config_dir = os.getcwd()
        else:
            raise ValueError("Must provide config_file or config_dict")

        self.config = config

    @staticmethod
    def _capture_config_raw(
        config_file: Optional[str],
        config_dict: Optional[Dict],
    ) -> Optional[str]:
        """Capture the raw config as a normalized YAML string.

        For file-based configs, reads the file verbatim.
        For dict-based configs, serializes to YAML.
        """
        if config_file is not None:
            with open(config_file, "r") as f:
                return f.read()
        if config_dict is not None:
            if yaml is None:
                return json.dumps(config_dict, indent=2, default=str)
            return yaml.dump(config_dict, default_flow_style=False, sort_keys=False)
        return None

    def _validate_spec(self) -> None:
        """Validate the spec envelope."""
        spec = self.config.get('spec')
        if spec != 'flatmachine':
            raise ValueError(
                f"Invalid spec: expected 'flatmachine', got '{spec}'"
            )

        if 'data' not in self.config:
            raise ValueError("Config missing 'data' section")

        # Version check with warning
        self.spec_version = check_spec_version(self.config.get('spec_version'), __version__)

        # Schema validation (warnings only, non-blocking)
        try:
            from .validation import validate_flatmachine_config
            validate_flatmachine_config(self.config, warn=True, strict=False)
        except ImportError:
            pass  # jsonschema not installed, skip validation

    def _parse_machine_config(self) -> None:
        """Parse the machine configuration."""
        self.data = self.config['data']
        self.metadata = self.config.get('metadata', {})

        self.machine_name = self.data.get('name', 'unnamed-machine')
        self.initial_context = self.data.get('context', {})
        self.agent_refs = self.data.get('agents', {})
        self.machine_refs = self.data.get('machines', {})
        self.states = self.data.get('states', {})
        self.settings = self.data.get('settings', {})

        # Find initial and final states
        self._initial_state = None
        self._final_states = set()

        for name, state in self.states.items():
            if state.get('type') == 'initial':
                if self._initial_state is not None:
                    raise ValueError("Multiple initial states defined")
                self._initial_state = name
            if state.get('type') == 'final':
                self._final_states.add(name)

        if self._initial_state is None:
            # Default to 'start' if exists, otherwise first state
            if 'start' in self.states:
                self._initial_state = 'start'
            elif self.states:
                self._initial_state = next(iter(self.states))
            else:
                raise ValueError("No states defined")

    @property
    def hooks_registry(self) -> HooksRegistry:
        """Access the hooks registry for registering hooks by name."""
        return self._hooks_registry

    def _resolve_hooks(self, hooks: Optional[MachineHooks]) -> MachineHooks:
        """
        Resolve hooks from explicit arg or config via registry.

        Priority: explicit hooks= arg > config hooks: > no hooks

        Config hooks are resolved via the HooksRegistry by name:
            hooks: "my-hooks"
            hooks: { name: "my-hooks", args: { key: "val" } }
            hooks: ["logging", { name: "my-hooks", args: {} }]
        """
        if hooks is not None:
            return hooks

        hooks_config = self.data.get('hooks')
        if not hooks_config:
            return MachineHooks()

        return self._hooks_registry.resolve(hooks_config)

    def _get_executor(self, agent_name: str) -> AgentExecutor:
        """Get or load an agent executor by name."""
        if agent_name in self._agents:
            return self._agents[agent_name]

        if agent_name not in self.agent_refs:
            raise ValueError(f"Unknown agent: {agent_name}")

        raw_ref = self.agent_refs[agent_name]
        agent_ref = normalize_agent_ref(raw_ref)

        adapter_context = AgentAdapterContext(
            config_dir=self._config_dir,
            settings=self.settings,
            machine_name=self.machine_name,
            profiles_file=self._profiles_file,
            profiles_dict=self._profiles_dict,
        )

        executor = self._agent_registry.create_executor(
            agent_name=agent_name,
            agent_ref=agent_ref,
            context=adapter_context,
        )

        self._agents[agent_name] = executor
        return executor

    # Pattern for bare path references: output, output.foo, context.bar.baz
    _PATH_PATTERN = re.compile(r'^(output|context|input)(\.[a-zA-Z_][a-zA-Z0-9_]*)*$')

    def _resolve_path(self, path: str, variables: Dict[str, Any]) -> Any:
        """Resolve a dotted path like 'output.chapters' to its value."""
        parts = path.split('.')
        value = variables
        for part in parts:
            if isinstance(value, Mapping):
                value = value.get(part)
            else:
                return None
        return value

    def _render_template(self, template_str: str, variables: Dict[str, Any]) -> Any:
        """Render a Jinja2 template string or resolve a bare path reference.

        Bare paths (no ``{{ }}``): resolved directly, preserving native type.
        Jinja templates (``{{ }}``): rendered to a string.  Jinja is for
        rendering — it always returns strings.
        """
        if not isinstance(template_str, str):
            return template_str

        stripped = template_str.strip()

        # No template syntax — check for bare path reference (preserves type)
        if '{{' not in stripped and '{%' not in stripped:
            if self._PATH_PATTERN.match(stripped):
                return self._resolve_path(stripped, variables)
            return template_str

        # Jinja template — render to string
        template = self._jinja_env.from_string(template_str)
        return template.render(**variables)

    def _render_dict(self, data: Dict[str, Any], variables: Dict[str, Any]) -> Dict[str, Any]:
        """Recursively render all template strings in a dict."""
        result = {}
        for key, value in data.items():
            if isinstance(value, str):
                result[key] = self._render_template(value, variables)
            elif isinstance(value, dict):
                result[key] = self._render_dict(value, variables)
            elif isinstance(value, list):
                result[key] = [
                    self._render_template(v, variables) if isinstance(v, str) else v
                    for v in value
                ]
            else:
                result[key] = value
        return result

    def _evaluate_condition(self, condition: str, context: Dict[str, Any]) -> bool:
        """Evaluate a transition condition."""
        variables = {"context": context}
        return bool(self._expression_engine.evaluate(condition, variables))

    def _get_error_recovery_state(
        self,
        state_config: Dict[str, Any],
        error: Exception
    ) -> Optional[str]:
        """
        Get recovery state from on_error config.
        
        Supports two formats:
        - Simple: on_error: "error_state"
        - Granular: on_error: {default: "error_state", RateLimitError: "retry_state"}
        """
        on_error = state_config.get('on_error')
        if not on_error:
            return None
        
        # Simple format: on_error: "state_name"
        if isinstance(on_error, str):
            return on_error
        
        # Granular format: on_error: {error_type: state_name, default: fallback}
        error_type = type(error).__name__
        return on_error.get(error_type) or on_error.get('default')

    def _find_next_state(
        self,
        state_name: str,
        context: Dict[str, Any]
    ) -> Optional[str]:
        """Find the next state based on transitions."""
        state = self.states.get(state_name, {})
        transitions = state.get('transitions', [])

        for transition in transitions:
            condition = transition.get('condition', '')
            to_state = transition.get('to')

            if not to_state:
                continue

            # No condition = default transition
            if not condition:
                return to_state

            # Evaluate condition
            if self._evaluate_condition(condition, context):
                return to_state

        return None

    def _resolve_config(self, name: str) -> Dict[str, Any]:
        """Resolve a component reference (agent/machine) to a config dict."""
        ref = self.agent_refs.get(name)
        if not ref:
            raise ValueError(f"Unknown component reference: {name}")

        if isinstance(ref, dict):
            return ref

        if isinstance(ref, str):
            path = ref
            if not os.path.isabs(path):
                path = os.path.join(self._config_dir, path)
            
            if not os.path.exists(path):
                raise FileNotFoundError(f"Component file not found: {path}")

            with open(path, 'r') as f:
                if path.endswith('.json'):
                    return json.load(f) or {}
                # Assume yaml
                if yaml:
                    return yaml.safe_load(f) or {}
                raise ImportError("pyyaml required for YAML files")
        
        raise ValueError(f"Invalid reference type: {type(ref)}")

    def _resolve_machine_config(self, name: str) -> tuple[Dict[str, Any], str]:
        """
        Resolve a machine reference to a config dict and its config directory.
        
        Returns:
            Tuple of (config_dict, config_dir) where config_dir is the directory
            containing the machine config file (for resolving relative paths).
        """
        ref = self.machine_refs.get(name)
        if not ref:
            raise ValueError(f"Unknown machine reference: {name}. Check 'machines:' section in config.")

        if isinstance(ref, dict):
            # Inline config - use parent's config_dir
            return ref, self._config_dir

        if isinstance(ref, str):
            path = ref
            if not os.path.isabs(path):
                path = os.path.join(self._config_dir, path)
            
            if not os.path.exists(path):
                raise FileNotFoundError(f"Machine config file not found: {path}")

            # The peer's config_dir is the directory containing its config file
            peer_config_dir = os.path.dirname(os.path.abspath(path))

            with open(path, 'r') as f:
                if path.endswith('.json'):
                    config = json.load(f) or {}
                elif yaml:
                    config = yaml.safe_load(f) or {}
                else:
                    raise ImportError("pyyaml required for YAML files")
            
            return config, peer_config_dir
        
        raise ValueError(f"Invalid machine reference type: {type(ref)}")

    # =========================================================================
    # Pending Launches (Outbox Pattern) - v0.4.0
    # =========================================================================

    def _add_pending_launch(
        self,
        execution_id: str,
        machine: str,
        input_data: Dict[str, Any]
    ) -> LaunchIntent:
        """Add a launch intent to the pending list (outbox pattern)."""
        intent = LaunchIntent(
            execution_id=execution_id,
            machine=machine,
            input=input_data,
            launched=False
        )
        self._pending_launches.append(intent)
        return intent

    def _mark_launched(self, execution_id: str) -> None:
        """Mark a pending launch as launched."""
        for intent in self._pending_launches:
            if intent.execution_id == execution_id:
                intent.launched = True
                break

    def _clear_pending_launch(self, execution_id: str) -> None:
        """Remove a completed launch from pending list."""
        self._pending_launches = [
            i for i in self._pending_launches
            if i.execution_id != execution_id
        ]

    def _get_pending_intents(self) -> list[Dict[str, Any]]:
        """Get pending launches as dicts for snapshot."""
        return [intent.to_dict() for intent in self._pending_launches]

    async def _resume_pending_launches(self) -> None:
        """Resume any pending launches that weren't completed."""
        for intent in self._pending_launches:
            if intent.launched:
                continue
            # Check if child already has a result
            uri = make_uri(intent.execution_id, "result")
            if await self.result_backend.exists(uri):
                continue
            # Re-launch
            logger.info(f"Resuming launch: {intent.machine} (ID: {intent.execution_id})")
            task = asyncio.create_task(
                self._launch_and_write(intent.machine, intent.execution_id, intent.input)
            )
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

    # =========================================================================
    # Machine Invocation - v0.4.0
    # =========================================================================

    async def _launch_and_write(
        self,
        machine_name: str,
        child_id: str,
        input_data: Dict[str, Any]
    ) -> Any:
        """Launch a peer machine and write its result to the backend."""
        target_config, peer_config_dir = self._resolve_machine_config(machine_name)

        # Peer machines share the hooks registry so they can resolve hooks by name
        # Use peer's config_dir so relative paths (e.g., ./agents/judge.yml) resolve correctly
        peer = FlatMachine(
            config_dict=target_config,
            hooks_registry=self._hooks_registry,
            result_backend=self.result_backend,
            signal_backend=self.signal_backend,
            trigger_backend=self.trigger_backend,
            agent_registry=self.agent_registry,
            persistence=self.persistence,
            lock=self.lock,
            config_store=self._config_store,
            _config_dir=peer_config_dir,
            _execution_id=child_id,
            _parent_execution_id=self.execution_id,
            _profiles_dict=self._profiles_dict,
            _profiles_file=self._profiles_file,
        )

        try:
            result = await peer.execute(input=input_data)
            # Write result to backend
            uri = make_uri(child_id, "result")
            await self.result_backend.write(uri, result)
            return result
        except Exception as e:
            # Write error to backend so parent knows
            uri = make_uri(child_id, "result")
            await self.result_backend.write(uri, {"_error": str(e), "_error_type": type(e).__name__})
            raise

    async def _invoke_machine_single(
        self,
        machine_name: str,
        input_data: Dict[str, Any],
        timeout: Optional[float] = None
    ) -> Any:
        """Invoke a single peer machine with blocking read."""
        child_id = str(uuid.uuid4())

        # Checkpoint intent (outbox pattern)
        self._add_pending_launch(child_id, machine_name, input_data)

        # Launch and execute
        result = await self._launch_and_write(machine_name, child_id, input_data)

        # Mark completed and clear
        self._mark_launched(child_id)
        self._clear_pending_launch(child_id)

        return result

    async def _invoke_machines_parallel(
        self,
        machines: list[str],
        input_data: Dict[str, Any],
        mode: str = "settled",
        timeout: Optional[float] = None
    ) -> Dict[str, Any]:
        """Invoke multiple machines in parallel."""
        child_ids = {m: str(uuid.uuid4()) for m in machines}

        # Checkpoint all intents
        for machine_name, child_id in child_ids.items():
            self._add_pending_launch(child_id, machine_name, input_data)

        # Launch all
        tasks = {}
        for machine_name, child_id in child_ids.items():
            task = asyncio.create_task(
                self._launch_and_write(machine_name, child_id, input_data)
            )
            tasks[machine_name] = task

        results = {}
        errors = {}

        if mode == "settled":
            # Wait for all to complete
            gathered = await asyncio.gather(*tasks.values(), return_exceptions=True)
            for machine_name, result in zip(tasks.keys(), gathered):
                if isinstance(result, Exception):
                    errors[machine_name] = result
                    results[machine_name] = {"_error": str(result), "_error_type": type(result).__name__}
                else:
                    results[machine_name] = result

        elif mode == "any":
            # Wait for first to complete
            done, pending = await asyncio.wait(
                tasks.values(),
                return_when=asyncio.FIRST_COMPLETED,
                timeout=timeout
            )
            # Find which machine finished
            for machine_name, task in tasks.items():
                if task in done:
                    try:
                        results[machine_name] = task.result()
                    except Exception as e:
                        results[machine_name] = {"_error": str(e), "_error_type": type(e).__name__}
                    break
            # Let pending tasks continue in background
            for task in pending:
                self._background_tasks.add(task)
                task.add_done_callback(self._background_tasks.discard)

        # Clear pending launches
        for child_id in child_ids.values():
            self._mark_launched(child_id)
            self._clear_pending_launch(child_id)

        return results

    async def _invoke_foreach(
        self,
        items: list,
        as_var: str,
        key_expr: Optional[str],
        machine_name: str,
        input_template: Dict[str, Any],
        mode: str = "settled",
        timeout: Optional[float] = None
    ) -> Any:
        """Invoke a machine for each item in a list."""
        child_ids = {}
        item_inputs = {}

        for i, item in enumerate(items):
            # Compute key
            if key_expr:
                variables = {as_var: item, "context": {}, "input": {}}
                item_key = self._render_template(key_expr, variables)
            else:
                item_key = i

            child_id = str(uuid.uuid4())
            child_ids[item_key] = child_id

            # Render input for this item
            variables = {as_var: item, "context": {}, "input": {}}
            item_input = self._render_dict(input_template, variables)
            item_inputs[item_key] = item_input

            self._add_pending_launch(child_id, machine_name, item_input)

        # Launch all
        tasks = {}
        for item_key, child_id in child_ids.items():
            task = asyncio.create_task(
                self._launch_and_write(machine_name, child_id, item_inputs[item_key])
            )
            tasks[item_key] = task

        results = {}

        if mode == "settled":
            gathered = await asyncio.gather(*tasks.values(), return_exceptions=True)
            for item_key, result in zip(tasks.keys(), gathered):
                if isinstance(result, Exception):
                    results[item_key] = {"_error": str(result), "_error_type": type(result).__name__}
                else:
                    results[item_key] = result

        elif mode == "any":
            done, pending = await asyncio.wait(
                tasks.values(),
                return_when=asyncio.FIRST_COMPLETED,
                timeout=timeout
            )
            for item_key, task in tasks.items():
                if task in done:
                    try:
                        results[item_key] = task.result()
                    except Exception as e:
                        results[item_key] = {"_error": str(e), "_error_type": type(e).__name__}
                    break
            for task in pending:
                self._background_tasks.add(task)
                task.add_done_callback(self._background_tasks.discard)

        # Clear pending launches
        for child_id in child_ids.values():
            self._mark_launched(child_id)
            self._clear_pending_launch(child_id)

        # Return dict if key_expr provided, else list
        if key_expr:
            return results
        else:
            return [results[i] for i in sorted(results.keys()) if isinstance(i, int)]

    async def _launch_fire_and_forget(
        self,
        machines: list[str],
        input_data: Dict[str, Any]
    ) -> None:
        """Launch machines without waiting for results (fire-and-forget).
        
        Delegates to self.invoker.launch() for cloud-agnostic execution.
        The invoker determines HOW the launch happens (inline task, queue, etc).
        """
        for machine_name in machines:
            child_id = str(uuid.uuid4())
            target_config, _ = self._resolve_machine_config(machine_name)
            
            # Record intent before launch (outbox pattern)
            self._add_pending_launch(child_id, machine_name, input_data)
            
            # Delegate to invoker
            await self.invoker.launch(
                caller_machine=self,
                target_config=target_config,
                input_data=input_data,
                execution_id=child_id
            )
            
            self._mark_launched(child_id)

    async def _run_hook(self, method_name: str, *args) -> Any:
        """Run a hook method, awaiting if it's a coroutine."""
        method = getattr(self._hooks, method_name)
        result = method(*args)
        if asyncio.iscoroutine(result):
            return await result
        return result

    async def _execute_state(
        self,
        state_name: str,
        context: Dict[str, Any]
    ) -> tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
        """
        Execute a single state.
        
        Returns:
            Tuple of (updated_context, agent_output)
        """
        state = self.states.get(state_name, {})
        output = None

        # 0. Handle 'wait_for' (external signal — checkpoint and exit)
        wait_for_expr = state.get('wait_for')
        if wait_for_expr:
            variables = {"context": context, "input": context}
            channel = self._render_template(wait_for_expr, variables)

            # Try to consume a signal (available on resume, or pre-loaded)
            signal = None
            if self.signal_backend:
                signal = await self.signal_backend.consume(channel)

            if signal is None:
                # No signal available — checkpoint and exit
                raise WaitingForSignal(channel=channel)

            # Signal consumed — its data becomes output for this state
            output = signal.data

            # Apply output_to_context mapping
            output_mapping = state.get('output_to_context', {})
            if output_mapping:
                safe_output = output if isinstance(output, dict) else {"value": output}
                variables = {"context": context, "output": safe_output, "input": context}
                for ctx_key, template in output_mapping.items():
                    context[ctx_key] = self._render_template(template, variables)

            return context, output

        # 1. Handle 'action' (hooks/custom actions)
        action_name = state.get('action')
        if action_name:
            action_impl = HookAction(self._hooks)
            context = await action_impl.execute(action_name, context, config={})

        # 2. Handle 'launch' (fire-and-forget machine execution)
        launch_spec = state.get('launch')
        if launch_spec:
            launch_input_spec = state.get('launch_input', {})
            variables = {"context": context, "input": context}
            launch_input = self._render_dict(launch_input_spec, variables)

            # Normalize to list
            machines_to_launch = [launch_spec] if isinstance(launch_spec, str) else launch_spec
            await self._launch_fire_and_forget(machines_to_launch, launch_input)

        # 3. Handle 'machine' (peer machine execution with blocking read)
        machine_spec = state.get('machine')
        foreach_expr = state.get('foreach')

        if machine_spec or foreach_expr:
            input_spec = state.get('input', {})
            variables = {"context": context, "input": context}
            mode = state.get('mode', 'settled')
            timeout = state.get('timeout')

            if foreach_expr:
                # Dynamic parallelism: foreach
                items = self._render_template(foreach_expr, variables)
                if not isinstance(items, list):
                    raise ValueError(f"foreach expression must yield a list, got {type(items)}")

                as_var = state.get('as', 'item')
                key_expr = state.get('key')
                machine_name = machine_spec if isinstance(machine_spec, str) else machine_spec[0]

                output = await self._invoke_foreach(
                    items=items,
                    as_var=as_var,
                    key_expr=key_expr,
                    machine_name=machine_name,
                    input_template=input_spec,
                    mode=mode,
                    timeout=timeout
                )

            elif isinstance(machine_spec, list):
                # Parallel execution: machine: [a, b, c]
                machine_input = self._render_dict(input_spec, variables)

                # Handle MachineInput objects (with per-machine inputs)
                if machine_spec and isinstance(machine_spec[0], dict):
                    # machine: [{name: a, input: {...}}, ...]
                    machine_names = [m['name'] for m in machine_spec]
                    # TODO: Support per-machine inputs
                    output = await self._invoke_machines_parallel(
                        machines=machine_names,
                        input_data=machine_input,
                        mode=mode,
                        timeout=timeout
                    )
                else:
                    # machine: [a, b, c]
                    output = await self._invoke_machines_parallel(
                        machines=machine_spec,
                        input_data=machine_input,
                        mode=mode,
                        timeout=timeout
                    )

            else:
                # Single machine: machine: child
                machine_input = self._render_dict(input_spec, variables)
                output = await self._invoke_machine_single(
                    machine_name=machine_spec,
                    input_data=machine_input,
                    timeout=timeout
                )

            output_mapping = state.get('output_to_context', {})
            if output_mapping:
                safe_output = output or {}
                variables = {"context": context, "output": safe_output, "input": context}
                for ctx_key, template in output_mapping.items():
                    context[ctx_key] = self._render_template(template, variables)

        # 4. Handle 'agent' (LLM execution)
        agent_name = state.get('agent')
        if agent_name:
            if state.get('tool_loop'):
                context, output = await self._execute_tool_loop(
                    state_name, state, agent_name, context
                )
            else:
                executor = self._get_executor(agent_name)
                input_spec = state.get('input', {})
                variables = {"context": context, "input": context}
                agent_input = self._render_dict(input_spec, variables)

                execution_config = state.get('execution')
                execution_type = get_execution_type(execution_config)
                result = await execution_type.execute(executor, agent_input, context=context)
                agent_result = coerce_agent_result(result)

                if agent_result.error:
                    err = agent_result.error
                    raise RuntimeError(f"{err.get('type', 'AgentError')}: {err.get('message', 'unknown')}")

                output = agent_result.output_payload()

                self._accumulate_agent_metrics(agent_result)

                output_mapping = state.get('output_to_context', {})
                if output_mapping:
                    variables = {"context": context, "output": output, "input": context}
                    for ctx_key, template in output_mapping.items():
                        context[ctx_key] = self._render_template(template, variables)

        # Handle final state output
        if state.get('type') == 'final':
            output_spec = state.get('output', {})
            if output_spec:
                variables = {"context": context}
                output = self._render_dict(output_spec, variables)

        return context, output

    # ─────────────────────────────────────────────────────────────────────
    # Tool Loop
    # ─────────────────────────────────────────────────────────────────────

    def _resolve_tool_provider(self, state_name: str):
        """Resolve ToolProvider: hooks first, then constructor default."""
        provider = self._hooks.get_tool_provider(state_name)
        if provider is not None:
            return provider
        return self._tool_provider

    def _resolve_tool_definitions(self, agent_name: str, tool_provider) -> List[Dict[str, Any]]:
        """Merge tool definitions from provider and agent YAML config.

        Provider definitions override YAML definitions (matched by name).
        """
        # Get definitions from provider
        provider_defs: List[Dict[str, Any]] = []
        if tool_provider is not None:
            provider_defs = tool_provider.get_tool_definitions() or []

        # Get definitions from agent YAML config
        agent_config = self._get_agent_config(agent_name)
        yaml_defs: List[Dict[str, Any]] = []
        if agent_config:
            yaml_defs = agent_config.get("data", {}).get("tools", []) or []

        if not provider_defs:
            return yaml_defs
        if not yaml_defs:
            return provider_defs

        # Merge: provider overrides YAML by function name
        provider_names = set()
        for d in provider_defs:
            fn = d.get("function", {})
            if fn.get("name"):
                provider_names.add(fn["name"])

        merged = list(provider_defs)
        for d in yaml_defs:
            fn = d.get("function", {})
            if fn.get("name") not in provider_names:
                merged.append(d)

        return merged

    def _get_agent_config(self, agent_name: str) -> Optional[Dict[str, Any]]:
        """Get the raw agent config dict for an agent name."""
        agents_map = self.data.get("agents", {})
        ref = agents_map.get(agent_name)
        if ref is None:
            return None
        if isinstance(ref, dict):
            # Inline config or typed ref
            if ref.get("spec") == "flatagent":
                return ref
            if "config" in ref and isinstance(ref["config"], dict):
                return ref["config"]
        # String path — load from file
        if isinstance(ref, str):
            config_path = os.path.join(self._config_dir, ref)
            if os.path.exists(config_path):
                if yaml is not None:
                    with open(config_path, 'r') as f:
                        return yaml.safe_load(f)
        return None

    def _render_guardrail(self, value, variables: Dict[str, Any], target_type: type):
        """Render a guardrail value through Jinja2 if it's a template string."""
        if value is None:
            return None
        if isinstance(value, str):
            rendered = self._render_template(value, variables)
            return target_type(rendered)
        return target_type(value)

    def _build_assistant_message(self, result: AgentResult) -> Dict[str, Any]:
        """Build an assistant message dict from AgentResult for chain continuation."""
        msg: Dict[str, Any] = {"role": "assistant", "content": result.content or ""}
        if result.tool_calls:
            msg["tool_calls"] = [
                {
                    "id": tc.get("id", ""),
                    "type": "function",
                    "function": {
                        "name": tc.get("name", ""),
                        "arguments": json.dumps(tc.get("arguments", {}))
                            if not isinstance(tc.get("arguments"), str)
                            else tc.get("arguments", "{}"),
                    },
                }
                for tc in result.tool_calls
            ]
        return msg

    def _find_conditional_transition(
        self,
        state_name: str,
        context: Dict[str, Any],
    ) -> Optional[str]:
        """Evaluate only conditional transitions. Used mid-tool-loop.

        Unconditional transitions (no ``condition`` field) are skipped —
        they are the natural exit path, evaluated only when the loop completes.
        """
        state = self.states.get(state_name, {})
        transitions = state.get('transitions', [])

        for transition in transitions:
            condition = transition.get('condition')
            to_state = transition.get('to')

            if not condition or not to_state:
                continue  # Skip unconditional transitions

            if self._evaluate_condition(condition, context):
                return to_state

        return None

    def _extract_cost(self, result: AgentResult) -> float:
        """Extract cost from an AgentResult for local loop tracking."""
        if result.cost is not None:
            if isinstance(result.cost, (int, float)):
                return float(result.cost)
            if isinstance(result.cost, dict):
                total = result.cost.get("total")
                if isinstance(total, (int, float)):
                    return float(total)
        # Fallback: check usage dict
        usage = result.usage or {}
        if isinstance(usage, dict):
            cost = usage.get("cost")
            if isinstance(cost, (int, float)):
                return float(cost)
            if isinstance(cost, dict):
                total = cost.get("total")
                if isinstance(total, (int, float)):
                    return float(total)
        return 0.0

    async def _execute_tool_loop(
        self,
        state_name: str,
        state: Dict[str, Any],
        agent_name: str,
        context: Dict[str, Any],
    ) -> tuple:
        """
        Execute an agent in tool-loop mode.

        Each tool call is an individually checkpointed step:
        1. Call agent via execute_with_tools (with tools + message chain)
        2. If agent returns tool_calls:
           a. Fire on_tool_calls hook (once per LLM response)
           b. For EACH tool call in the response:
              i.   Execute tool via ToolProvider
              ii.  Append result to chain
              iii. Fire on_tool_result hook
              iv.  Checkpoint with tool_loop_state
              v.   Evaluate conditional transitions — if any match, EXIT
           c. Check guardrails (max_turns, max_tool_calls, cost)
           d. Go to step 1
        3. If agent returns content (no tool_calls):
           a. Loop is done. Return output for normal transition evaluation.

        Returns:
            Tuple of (updated_context, output_dict)
        """
        # Parse guardrails from state config — Jinja2 templates supported
        loop_config = state.get('tool_loop', {})
        if isinstance(loop_config, bool):
            loop_config = {}

        variables = {"context": context, "input": context}
        max_turns = self._render_guardrail(loop_config.get('max_turns', 20), variables, int)
        max_tool_calls = self._render_guardrail(loop_config.get('max_tool_calls', 50), variables, int)
        tool_timeout = self._render_guardrail(loop_config.get('tool_timeout', 30.0), variables, float)
        total_timeout = self._render_guardrail(loop_config.get('total_timeout', 600.0), variables, float)
        max_cost = self._render_guardrail(loop_config.get('max_cost'), variables, float)
        allowed_tools = set(loop_config.get('allowed_tools', []))
        denied_tools = set(loop_config.get('denied_tools', []))

        # Get agent executor — must support execute_with_tools
        executor = self._get_executor(agent_name)
        try:
            # Check capability
            executor.execute_with_tools
        except AttributeError:
            adapter_type = type(executor).__name__
            raise RuntimeError(
                f"Agent '{agent_name}' ({adapter_type}) does not support "
                f"machine-driven tool loops. Implement execute_with_tools "
                f"on the adapter or remove tool_loop from state '{state_name}'."
            )

        # Get tool provider
        tool_provider = self._resolve_tool_provider(state_name)

        # Resolve tool definitions
        tool_defs = self._resolve_tool_definitions(agent_name, tool_provider)

        # Build initial input
        input_spec = state.get('input', {})
        variables = {"context": context, "input": context}
        agent_input = self._render_dict(input_spec, variables)

        # Restore chain from prior round only when state+agent identity matches.
        # This preserves prefix cache for same-state continuation while preventing
        # cross-state/agent chain bleed.
        saved_chain = context.pop('_tool_loop_chain', None)
        saved_chain_state = context.pop('_tool_loop_chain_state', None)
        saved_chain_agent = context.pop('_tool_loop_chain_agent', None)
        has_prior_chain = bool(
            saved_chain
            and saved_chain_state == state_name
            and saved_chain_agent == agent_name
        )
        chain: List[Dict[str, Any]] = saved_chain if has_prior_chain else []
        turns = 0
        tool_calls_count = 0
        loop_cost = 0.0
        start_time = time.monotonic()
        last_content: Optional[str] = None

        while True:
            # --- Guardrail checks ---
            if time.monotonic() - start_time >= total_timeout:
                context['_tool_loop_stop'] = 'timeout'
                break
            if turns >= max_turns:
                context['_tool_loop_stop'] = 'max_turns'
                break
            if max_cost is not None and loop_cost >= max_cost:
                context['_tool_loop_stop'] = 'cost_limit'
                break

            # --- Call agent via execute_with_tools ---
            if turns == 0 and not has_prior_chain:
                # First call ever — render user prompt from input_data
                result = await executor.execute_with_tools(
                    input_data=agent_input,
                    tools=tool_defs,
                    messages=None,
                    context=context,
                )
            else:
                # Continuation — pass chain (preserves prefix cache)
                result = await executor.execute_with_tools(
                    input_data={},
                    tools=tool_defs,
                    messages=chain,
                    context=context,
                )

            turns += 1
            self._accumulate_agent_metrics(result)
            loop_cost += self._extract_cost(result)

            # Update context with loop metadata
            context['_tool_loop_turns'] = turns
            context['_tool_loop_cost'] = loop_cost
            context['_tool_calls_count'] = tool_calls_count
            context['_tool_loop_content'] = result.content
            context['_tool_loop_usage'] = result.usage

            # --- Handle error ---
            if result.error:
                raise RuntimeError(
                    f"{result.error.get('type', 'AgentError')}: "
                    f"{result.error.get('message', 'unknown')}"
                )

            # --- Seed chain on first turn ---
            if turns == 1 and not has_prior_chain and result.rendered_user_prompt:
                chain.append({"role": "user", "content": result.rendered_user_prompt})

            # --- Build assistant message and append to chain ---
            assistant_msg = self._build_assistant_message(result)
            chain.append(assistant_msg)
            last_content = result.content

            # --- No tool calls = loop complete ---
            if result.finish_reason != "tool_use":
                break

            pending_calls = result.tool_calls or []

            # --- Guardrail: tool call count ---
            if tool_calls_count + len(pending_calls) > max_tool_calls:
                context['_tool_loop_stop'] = 'max_tool_calls'
                break

            # --- HOOK: on_tool_calls (once per LLM response) ---
            context = await self._run_hook(
                'on_tool_calls', state_name, pending_calls, context,
            )

            if context.get('_abort_tool_loop'):
                context['_tool_loop_stop'] = 'aborted'
                break

            # --- Execute tools ONE AT A TIME with per-tool hooks + checkpoints ---
            skip_tools = set(context.pop('_skip_tools', []))

            for tc in pending_calls:
                tc_name = tc.get('name') or tc.get('tool')
                tc_id = tc.get('id')
                tc_args = tc.get('arguments', {})

                # Skip if hook requested
                if tc_id in skip_tools or tc_name in skip_tools:
                    chain.append({
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": f"Tool '{tc_name}' was skipped by policy.",
                    })
                    continue

                # Check allow/deny
                if denied_tools and tc_name in denied_tools:
                    chain.append({
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": f"Tool '{tc_name}' is not allowed.",
                    })
                    continue
                if allowed_tools and tc_name not in allowed_tools:
                    chain.append({
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": f"Tool '{tc_name}' is not allowed.",
                    })
                    continue

                # Execute single tool
                if tool_provider is not None:
                    try:
                        tool_result = await asyncio.wait_for(
                            tool_provider.execute_tool(tc_name, tc_id, tc_args),
                            timeout=tool_timeout,
                        )
                    except asyncio.TimeoutError:
                        from flatagents.tools import ToolResult as _ToolResult
                        tool_result = _ToolResult(
                            content=f"Tool '{tc_name}' timed out after {tool_timeout}s",
                            is_error=True,
                        )
                    except Exception as e:
                        from flatagents.tools import ToolResult as _ToolResult
                        tool_result = _ToolResult(
                            content=f"Error executing '{tc_name}': {e}",
                            is_error=True,
                        )
                else:
                    from flatagents.tools import ToolResult as _ToolResult
                    tool_result = _ToolResult(
                        content=f"No tool provider configured for '{tc_name}'",
                        is_error=True,
                    )

                tool_calls_count += 1

                tool_result_dict = {
                    "tool_call_id": tc_id,
                    "name": tc_name,
                    "arguments": tc_args,
                    "content": tool_result.content,
                    "is_error": tool_result.is_error,
                }

                chain.append({
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "content": tool_result.content,
                })

                context['_tool_calls_count'] = tool_calls_count

                # --- HOOK: on_tool_result (per tool call) ---
                context = await self._run_hook(
                    'on_tool_result', state_name, tool_result_dict, context,
                )

                # --- Checkpoint after each tool call ---
                await self._save_checkpoint(
                    'tool_call', state_name, self._current_step, context,
                    tool_loop_state={
                        "chain": chain,
                        "turns": turns,
                        "tool_calls_count": tool_calls_count,
                        "loop_cost": loop_cost,
                    },
                )

                # --- Evaluate conditional transitions after each tool call ---
                if context.get('_abort_tool_loop'):
                    context['_tool_loop_stop'] = 'aborted'
                    break

                next_state = self._find_conditional_transition(state_name, context)
                if next_state is not None:
                    context['_tool_loop_stop'] = 'transition'
                    context['_tool_loop_next_state'] = next_state
                    break

            # Check if inner loop broke out
            if context.get('_tool_loop_stop'):
                break

            # --- Inject steering messages from hook ---
            steering = context.pop('_steering_messages', None)
            if steering:
                for msg in steering:
                    chain.append(msg)

        # Save chain identity for potential continuation (preserves prefix cache)
        context['_tool_loop_chain'] = chain
        context['_tool_loop_chain_state'] = state_name
        context['_tool_loop_chain_agent'] = agent_name

        # --- Build output ---
        output = {
            "content": last_content,
            "_tool_calls_count": tool_calls_count,
            "_tool_loop_turns": turns,
            "_tool_loop_cost": loop_cost,
            "_tool_loop_stop": context.get('_tool_loop_stop', 'complete'),
        }

        # Apply output_to_context mapping
        output_mapping = state.get('output_to_context', {})
        if output_mapping:
            variables = {"context": context, "output": output, "input": context}
            for ctx_key, template in output_mapping.items():
                context[ctx_key] = self._render_template(template, variables)

        return context, output

    def _accumulate_agent_metrics(self, result: AgentResult) -> None:
        """Accumulate usage/cost from an AgentResult."""
        if result.cost is not None:
            if isinstance(result.cost, (int, float)):
                self.total_cost += result.cost
            elif isinstance(result.cost, dict):
                total = result.cost.get("total")
                if isinstance(total, (int, float)):
                    self.total_cost += total

        usage = result.usage or {}
        if isinstance(usage, dict):
            api_calls = usage.get("api_calls")
            if api_calls is None:
                api_calls = usage.get("requests") or usage.get("calls")
            if api_calls:
                self.total_api_calls += api_calls

            if result.cost is None:
                cost = usage.get("cost")
                if isinstance(cost, (int, float)):
                    self.total_cost += cost
                elif isinstance(cost, dict):
                    total = cost.get("total")
                    if isinstance(total, (int, float)):
                        self.total_cost += total

    async def _save_checkpoint(
        self,
        event: str,
        state_name: str,
        step: int,
        context: Dict[str, Any],
        output: Optional[Dict[str, Any]] = None,
        waiting_channel: Optional[str] = None,
        tool_loop_state: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Save a checkpoint if configured."""
        if event not in self.checkpoint_events:
            return

        # Convert MappingProxyType to plain dict for JSON serialization
        checkpoint_context = dict(context)
        if "machine" in checkpoint_context and isinstance(checkpoint_context["machine"], MappingProxyType):
            checkpoint_context["machine"] = dict(checkpoint_context["machine"])

        # Store config in content-addressed store on first checkpoint
        if self._config_hash is None and self._config_raw and self._config_store:
            self._config_hash = await self._config_store.put(self._config_raw)

        snapshot = MachineSnapshot(
            execution_id=self.execution_id,
            machine_name=self.machine_name,
            spec_version=self.spec_version,
            current_state=state_name,
            context=checkpoint_context,
            step=step,
            event=event,
            output=output,
            total_api_calls=self.total_api_calls,
            total_cost=self.total_cost,
            parent_execution_id=self.parent_execution_id,
            pending_launches=self._get_pending_intents() if self._pending_launches else None,
            waiting_channel=waiting_channel,
            tool_loop_state=tool_loop_state,
            config_hash=self._config_hash,
        )

        manager = CheckpointManager(self.persistence, self.execution_id)
        await manager.save_checkpoint(snapshot)

    async def execute(
        self,
        input: Optional[Dict[str, Any]] = None,
        max_steps: int = 1000,
        max_agent_calls: Optional[int] = None,
        resume_from: Optional[str] = None
    ) -> Dict[str, Any]:
        """Execute the machine."""
        if resume_from:
            self.execution_id = resume_from
            logger.info(f"Resuming execution: {self.execution_id}")

        if not await self.lock.acquire(self.execution_id):
            raise RuntimeError(f"Could not acquire lock for execution {self.execution_id}")

        try:
            context = {}
            current_state = None
            step = 0
            final_output = {}
            hit_agent_limit = False
            manager = CheckpointManager(self.persistence, self.execution_id)

            if resume_from:
                snapshot = await manager.load_latest()
                if snapshot:
                    context = snapshot.context
                    step = snapshot.step
                    current_state = snapshot.current_state
                    # Restore execution metrics
                    self.total_api_calls = snapshot.total_api_calls or 0
                    self.total_cost = snapshot.total_cost or 0.0
                    # Restore pending launches (outbox pattern)
                    if snapshot.pending_launches:
                        self._pending_launches = [
                            LaunchIntent.from_dict(intent)
                            for intent in snapshot.pending_launches
                        ]
                        await self._resume_pending_launches()
                    if snapshot.event == 'machine_end':
                        logger.info("Execution already completed.")
                        return snapshot.output or {}
                    # Rebuild context.machine from live properties (discard stale snapshot copy)
                    context = self._inject_machine_metadata(context, current_state)
                    logger.info(f"Restored from snapshot: step={step}, state={current_state}")
                else:
                    logger.warning(f"No snapshot found for {resume_from}, starting fresh.")

            if not current_state:
                current_state = self._initial_state
                input = input or {}
                variables = {"input": input}
                context = self._render_dict(self.initial_context, variables)
                context = self._inject_machine_metadata(context, current_state)

                await self._save_checkpoint('machine_start', 'start', step, context)
                context = await self._run_hook('on_machine_start', context)

            logger.info(f"Starting execution loop at: {current_state}")

            while current_state and step < max_steps:
                if max_agent_calls is not None and self.total_api_calls >= max_agent_calls:
                    hit_agent_limit = True
                    break
                step += 1
                self._current_step = step
                is_final = current_state in self._final_states
                context = self._inject_machine_metadata(context, current_state)

                await self._save_checkpoint('state_enter', current_state, step, context)
                context = await self._run_hook('on_state_enter', current_state, context)

                await self._save_checkpoint('execute', current_state, step, context)

                try:
                    context, output = await self._execute_state(current_state, context)
                    if output and is_final:
                        final_output = output
                except WaitingForSignal as ws:
                    # Checkpoint with waiting_channel and exit
                    await self._save_checkpoint(
                        'waiting', current_state, step, context,
                        waiting_channel=ws.channel,
                    )
                    logger.info(f"Machine paused, waiting for signal on: {ws.channel}")
                    return {"_waiting": True, "_channel": ws.channel}
                except Exception as e:
                    context['last_error'] = str(e)
                    context['last_error_type'] = type(e).__name__
                    
                    state_config = self.states.get(current_state, {})
                    recovery_state = self._get_error_recovery_state(state_config, e)
                    
                    if not recovery_state:
                         recovery_state = await self._run_hook('on_error', current_state, e, context)
                    
                    if recovery_state:
                        logger.warning(f"Error in {current_state}, transitioning to {recovery_state}: {e}")
                        current_state = recovery_state
                        context = self._inject_machine_metadata(context, current_state)
                        continue
                    raise

                await self._save_checkpoint(
                    'state_exit', 
                    current_state, 
                    step, 
                    context, 
                    output=output if is_final else None
                )

                output = await self._run_hook('on_state_exit', current_state, context, output)

                if max_agent_calls is not None and self.total_api_calls >= max_agent_calls:
                    hit_agent_limit = True
                    break

                if is_final:
                    logger.info(f"Reached final state: {current_state}")
                    break

                if '_tool_loop_next_state' in context:
                    next_state = context.pop('_tool_loop_next_state')
                    context.pop('_tool_loop_stop', None)
                else:
                    next_state = self._find_next_state(current_state, context)
                
                if next_state:
                    next_state = await self._run_hook('on_transition', current_state, next_state, context)

                logger.debug(f"Transition: {current_state} -> {next_state}")
                current_state = next_state

            if step >= max_steps:
                logger.warning(f"Machine hit max_steps limit ({max_steps})")
            if hit_agent_limit and max_agent_calls is not None:
                logger.warning(f"Machine hit max_agent_calls limit ({max_agent_calls})")

            await self._save_checkpoint('machine_end', 'end', step, context, output=final_output)
            final_output = await self._run_hook('on_machine_end', context, final_output)

            return final_output

        finally:
            # Wait for any launched peer machines to complete
            # This ensures peer equality - launched machines have equal right to finish
            if self._background_tasks:
                await asyncio.gather(*self._background_tasks, return_exceptions=True)
            await self.lock.release(self.execution_id)

    def execute_sync(
        self,
        input: Optional[Dict[str, Any]] = None,
        max_steps: int = 1000,
        max_agent_calls: Optional[int] = None
    ) -> Dict[str, Any]:
        """Synchronous wrapper for execute()."""
        import asyncio
        return asyncio.run(self.execute(input=input, max_steps=max_steps, max_agent_calls=max_agent_calls))


__all__ = ["FlatMachine"]

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
import random
import re
from typing import Any, Dict, Optional

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
from .hooks import MachineHooks, LoggingHooks
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
    CheckpointManager,
    MachineSnapshot
)
from .backends import (
    ResultBackend,
    InMemoryResultBackend,
    LaunchIntent,
    make_uri,
    get_default_result_backend,
)
from .locking import ExecutionLock, LocalFileLock, NoOpLock
from .actions import (
    Action,
    HookAction,
    MachineInvoker,
    InlineInvoker,
    QueueInvoker,
)

logger = get_logger(__name__)


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
        persistence: Optional[PersistenceBackend] = None,
        lock: Optional[ExecutionLock] = None,
        invoker: Optional[MachineInvoker] = None,
        result_backend: Optional[ResultBackend] = None,
        agent_registry: Optional[AgentAdapterRegistry] = None,
        agent_adapters: Optional[list] = None,
        profiles_file: Optional[str] = None,
        **kwargs
    ):
        """
        Initialize the machine.

        Args:
            config_file: Path to YAML/JSON config file
            config_dict: Configuration dictionary
            hooks: Custom hooks for extensibility
            persistence: Storage backend (overrides config)
            lock: Concurrency lock (overrides config)
            invoker: Strategy for invoking other machines
            result_backend: Backend for inter-machine result storage
            agent_registry: Registry of agent adapters (optional)
            agent_adapters: List of agent adapters to register (optional)
            profiles_file: Optional profiles.yml path for adapters that use it
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

        # Hooks - load from config or use provided/default
        self._hooks = self._load_hooks(hooks)

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

        # Persistence & Locking
        self._initialize_persistence(persistence, lock)

        # Result backend for inter-machine communication
        self.result_backend = result_backend or get_default_result_backend()

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
        """Initialize persistence and locking components."""
        # Get config
        p_config = self.data.get('persistence', {})
        # Global features config override (simulated for now, would be in kwargs/settings)
        # For now, rely on machine.yml or defaults
        
        enabled = p_config.get('enabled', True) # Default enabled? Or disable? 
        # Plan says: "Global Defaults... backend: local".
        # Let's default to enabled=False for backward compat if not configured? 
        # Or follow plan default? Plan implies explicit configure.
        # Let's default to MemoryBackend if enabled but no backend specified
        
        backend_type = p_config.get('backend', 'memory')
        
        # Persistence Backend
        if persistence:
            self.persistence = persistence
        elif not enabled:
            self.persistence = MemoryBackend() # Fallback, unsaved
        elif backend_type == 'local':
            self.persistence = LocalFileBackend()
        elif backend_type == 'memory':
            self.persistence = MemoryBackend()
        else:
            logger.warning(f"Unknown backend '{backend_type}', using memory")
            self.persistence = MemoryBackend()
            
        # Lock
        if lock:
            self.lock = lock
        elif not enabled:
            self.lock = NoOpLock()
        elif backend_type == 'local':
            self.lock = LocalFileLock() 
        else:
            self.lock = NoOpLock()
            
        # Checkpoint events (default set)
        default_events = ['machine_start', 'state_enter', 'execute', 'state_exit', 'machine_end']
        self.checkpoint_events = set(p_config.get('checkpoint_on', default_events))

        # Auto-resume config
        resume_config = p_config.get('resume', {})
        self._resume_max_retries = int(resume_config.get('max_retries', 0))
        self._resume_backoffs = resume_config.get('backoffs', [1.0])
        self._resume_jitter = float(resume_config.get('jitter', 0.0))


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
        self._machine_on_error = self.data.get('on_error')

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

    def _load_hooks(self, hooks: Optional[MachineHooks]) -> MachineHooks:
        """
        Load hooks from config or use provided/default.

        Invocation patterns:

        LOCAL (development, single-process):
            hooks:
              file: "./hooks.py"    # Relative to config dir
              class: "MyHooks"
            - Loads from file path with sys.path manipulation
            - Supports sibling imports (from repl import X)
            - Hooks CAN be stateful (same process)

        DISTRIBUTED (Lambda, Cloud Run, multi-process):
            hooks:
              module: "mypackage.hooks"  # Installed package
              class: "MyHooks"
            - Loads from installed package (pip install)
            - No sys.path manipulation needed
            - Hooks MUST be stateless (checkpoint/restore loses instance state)

        Priority: explicit arg > file > module > default
        """
        if hooks is not None:
            return hooks

        hooks_config = self.data.get('hooks')
        if not hooks_config:
            return MachineHooks()

        class_name = hooks_config.get('class')
        if not class_name:
            logger.warning(f"Hooks config missing 'class', using default")
            return MachineHooks()

        # Route to appropriate loader based on invocation pattern
        if hooks_config.get('file'):
            hooks_class = self._load_hooks_local(hooks_config)
        elif hooks_config.get('module'):
            hooks_class = self._load_hooks_distributed(hooks_config)
        else:
            logger.warning(f"Hooks config needs 'file' or 'module', using default")
            return MachineHooks()

        if hooks_class is None:
            return MachineHooks()

        # Instantiate
        try:
            return hooks_class(**hooks_config.get('args', {}))
        except Exception as e:
            logger.error(f"Failed to instantiate {class_name}: {e}")
            return MachineHooks()

    def _load_hooks_local(self, config: Dict[str, Any]) -> Optional[type]:
        """
        LOCAL: Load hooks from file path.

        Use for development and single-process execution:
        - File path relative to machine config
        - sys.path manipulation for sibling imports
        - Hooks can be stateful (same process)
        """
        import sys

        file_path = config['file']
        class_name = config['class']

        if not os.path.isabs(file_path):
            file_path = os.path.join(self._config_dir, file_path)

        hooks_dir = os.path.dirname(os.path.abspath(file_path))
        added = hooks_dir not in sys.path

        try:
            if added:
                sys.path.insert(0, hooks_dir)
            try:
                spec = importlib.util.spec_from_file_location("hooks", file_path)
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    return getattr(module, class_name)
            finally:
                if added and hooks_dir in sys.path:
                    sys.path.remove(hooks_dir)
        except Exception as e:
            logger.error(f"LOCAL hooks failed ({file_path}): {e}")
        return None

    def _load_hooks_distributed(self, config: Dict[str, Any]) -> Optional[type]:
        """
        DISTRIBUTED: Load hooks from installed package.

        Use for Lambda, Cloud Run, checkpoint/restore:
        - Package installed via pip (requirements.txt)
        - No sys.path manipulation
        - Hooks MUST be stateless (state in context)
        """
        module_name = config['module']
        class_name = config['class']

        try:
            module = importlib.import_module(module_name)
            return getattr(module, class_name)
        except (ImportError, AttributeError) as e:
            logger.error(f"DISTRIBUTED hooks failed ({module_name}.{class_name}): {e}")
        return None

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
            if isinstance(value, dict):
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
        
        Resolution order:
        1. State-level on_error (from state_config)
        2. Machine-level on_error (from data.on_error)
        
        Supports two formats at each level:
        - Simple: on_error: "error_state"
        - Granular: on_error: {default: "error_state", RateLimitError: "retry_state"}
        """
        # Try state-level first, then machine-level
        for on_error in (state_config.get('on_error'), self._machine_on_error):
            if not on_error:
                continue

            # Simple format: on_error: "state_name"
            if isinstance(on_error, str):
                return on_error

            # Granular format: on_error: {error_type: state_name, default: fallback}
            error_type = type(error).__name__
            result = on_error.get(error_type) or on_error.get('default')
            if result:
                return result

        return None

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

        # Peer machines are independent - they load their own hooks from config
        # (via the hooks: section in their machine.yml)
        # Use peer's config_dir so relative paths (e.g., ./agents/judge.yml) resolve correctly
        peer = FlatMachine(
            config_dict=target_config,
            result_backend=self.result_backend,
            agent_registry=self.agent_registry,
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
        output: Optional[Dict[str, Any]] = None
    ) -> None:
        """Save a checkpoint if configured."""
        if event not in self.checkpoint_events:
            return

        snapshot = MachineSnapshot(
            execution_id=self.execution_id,
            machine_name=self.machine_name,
            spec_version=self.spec_version,
            current_state=state_name,
            context=context,
            step=step,
            event=event,
            output=output,
            total_api_calls=self.total_api_calls,
            total_cost=self.total_cost,
            parent_execution_id=self.parent_execution_id,
            pending_launches=self._get_pending_intents() if self._pending_launches else None,
        )

        manager = CheckpointManager(self.persistence, self.execution_id)
        await manager.save_checkpoint(snapshot)

    async def _execute_inner(
        self,
        input: Optional[Dict[str, Any]] = None,
        max_steps: int = 1000,
        max_agent_calls: Optional[int] = None,
        resume_from: Optional[str] = None
    ) -> Dict[str, Any]:
        """Core execution loop. Called by execute(), which handles auto-resume retry."""
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
                logger.info(f"Restored from snapshot: step={step}, state={current_state}")
            else:
                logger.warning(f"No snapshot found for {resume_from}, starting fresh.")

        if not current_state:
            current_state = self._initial_state
            input = input or {}
            variables = {"input": input}
            context = self._render_dict(self.initial_context, variables)


            await self._save_checkpoint('machine_start', 'start', step, context)
            context = await self._run_hook('on_machine_start', context)

        logger.info(f"Starting execution loop at: {current_state}")

        while current_state and step < max_steps:
            if max_agent_calls is not None and self.total_api_calls >= max_agent_calls:
                hit_agent_limit = True
                break
            step += 1
            is_final = current_state in self._final_states

            await self._save_checkpoint('state_enter', current_state, step, context)
            context = await self._run_hook('on_state_enter', current_state, context)

            await self._save_checkpoint('execute', current_state, step, context)

            try:
                context, output = await self._execute_state(current_state, context)
                if output and is_final:
                    final_output = output
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

    async def execute(
        self,
        input: Optional[Dict[str, Any]] = None,
        max_steps: int = 1000,
        max_agent_calls: Optional[int] = None,
        resume_from: Optional[str] = None
    ) -> Dict[str, Any]:
        """Execute the machine.

        If ``persistence.resume`` is configured, unhandled exceptions trigger
        automatic retry from the latest checkpoint. Otherwise exceptions
        propagate directly to the caller.
        """
        if resume_from:
            self.execution_id = resume_from
            logger.info(f"Resuming execution: {self.execution_id}")

        if not await self.lock.acquire(self.execution_id):
            raise RuntimeError(f"Could not acquire lock for execution {self.execution_id}")

        try:
            last_error: Optional[Exception] = None

            for attempt in range(1 + self._resume_max_retries):
                try:
                    # First attempt uses caller's resume_from; retries always
                    # resume from our own execution_id (the last checkpoint).
                    effective_resume = resume_from if attempt == 0 else self.execution_id
                    return await self._execute_inner(
                        input=input,
                        max_steps=max_steps,
                        max_agent_calls=max_agent_calls,
                        resume_from=effective_resume,
                    )
                except Exception as exc:
                    last_error = exc
                    if attempt >= self._resume_max_retries:
                        raise

                    backoffs = self._resume_backoffs
                    delay = backoffs[min(attempt, len(backoffs) - 1)]
                    if self._resume_jitter > 0:
                        delay += random.uniform(0, self._resume_jitter)

                    logger.warning(
                        "Execution %s attempt %d/%d failed, resuming in %.1fs: %s",
                        self.execution_id, attempt + 1,
                        1 + self._resume_max_retries, delay, exc,
                    )

                    # Release and re-acquire lock around the delay so we don't
                    # hold it while sleeping.
                    await self.lock.release(self.execution_id)
                    await asyncio.sleep(delay)
                    if not await self.lock.acquire(self.execution_id):
                        raise RuntimeError(
                            f"Could not re-acquire lock for execution {self.execution_id}"
                        ) from exc

            raise last_error  # type: ignore[misc]

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

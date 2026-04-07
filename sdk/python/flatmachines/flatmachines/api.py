"""
FlatMachine Execution API.

A single, unified API for machine lifecycle management:
create, start, get, list, resume, and cancel.

Wraps FlatMachine construction, persistence lookups, and execution
into a stateless service layer that can be used directly, via CLI,
or as the foundation for an HTTP/gRPC service.

Usage:

    api = MachineExecutionAPI(persistence=backend, config_store=store)

    # Create from config file
    handle = await api.create(config_file="./my_machine.yml")

    # Start execution
    result = await api.start(handle.execution_id, input={"key": "value"})

    # Or create + start in one call
    result = await api.run(config_file="./my_machine.yml", input={"key": "value"})

    # Get status of a running/completed machine
    info = await api.get(execution_id)

    # List machines by status
    active = await api.list(status="active")
    waiting = await api.list(waiting_channel="approval/task-001")

    # Resume a waiting machine
    result = await api.resume(execution_id)
"""

import uuid
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .persistence import (
    PersistenceBackend,
    MemoryBackend,
    CheckpointManager,
    ConfigStore,
    MachineSnapshot,
)
from .locking import ExecutionLock, NoOpLock
from .signals import SignalBackend, TriggerBackend
from .backends import ResultBackend, get_default_result_backend
from .hooks import MachineHooks, HooksRegistry
from .agents import AgentAdapterRegistry

logger = logging.getLogger(__name__)


@dataclass
class MachineHandle:
    """Lightweight reference to a created machine, prior to execution."""

    execution_id: str
    machine_name: str
    spec_version: str
    config_dict: Optional[Dict[str, Any]] = None
    config_file: Optional[str] = None


@dataclass
class MachineInfo:
    """Status snapshot of a machine execution."""

    execution_id: str
    machine_name: str
    current_state: str
    step: int
    event: Optional[str] = None
    output: Optional[Dict[str, Any]] = None
    total_api_calls: int = 0
    total_cost: float = 0.0
    parent_execution_id: Optional[str] = None
    waiting_channel: Optional[str] = None
    created_at: Optional[str] = None

    @property
    def is_completed(self) -> bool:
        return self.event == "machine_end"

    @property
    def is_waiting(self) -> bool:
        return self.waiting_channel is not None

    @property
    def is_active(self) -> bool:
        return not self.is_completed and not self.is_waiting


class MachineExecutionAPI:
    """Unified API for FlatMachine lifecycle management.

    Provides create/start/get/list/resume/cancel operations over a
    persistence backend.  Stateless — all state lives in the persistence
    layer.  Thread-safe for concurrent callers when the underlying
    persistence and lock backends support it.

    Args:
        persistence: Checkpoint storage backend (default: MemoryBackend).
        lock: Concurrency lock (default: NoOpLock).
        config_store: Content-addressed config store (optional).
        signal_backend: Signal storage for wait_for states (optional).
        trigger_backend: Trigger activation (optional).
        result_backend: Inter-machine result backend (optional).
        hooks: Default MachineHooks instance (optional).
        hooks_registry: Registry for resolving hooks by name (optional).
        agent_registry: Agent adapter registry (optional).
        profiles_file: Default profiles.yml path (optional).
        tool_provider: Default ToolProvider for tool_loop states (optional).
    """

    def __init__(
        self,
        persistence: Optional[PersistenceBackend] = None,
        lock: Optional[ExecutionLock] = None,
        config_store: Optional[ConfigStore] = None,
        signal_backend: Optional[SignalBackend] = None,
        trigger_backend: Optional[TriggerBackend] = None,
        result_backend: Optional[ResultBackend] = None,
        hooks: Optional[MachineHooks] = None,
        hooks_registry: Optional[HooksRegistry] = None,
        agent_registry: Optional[AgentAdapterRegistry] = None,
        profiles_file: Optional[str] = None,
        tool_provider: Any = None,
    ):
        self._persistence = persistence or MemoryBackend()
        self._lock = lock or NoOpLock()
        self._config_store = config_store
        self._signal_backend = signal_backend
        self._trigger_backend = trigger_backend
        self._result_backend = result_backend
        self._hooks = hooks
        self._hooks_registry = hooks_registry
        self._agent_registry = agent_registry
        self._profiles_file = profiles_file
        self._tool_provider = tool_provider

    def _build_machine(
        self,
        config_file: Optional[str] = None,
        config_dict: Optional[Dict[str, Any]] = None,
        execution_id: Optional[str] = None,
        hooks: Optional[MachineHooks] = None,
        **kwargs,
    ):
        """Construct a FlatMachine with the API's default backends.

        Caller-supplied arguments override API defaults.
        """
        from .flatmachine import FlatMachine

        build_kwargs: Dict[str, Any] = {}

        if execution_id:
            build_kwargs["_execution_id"] = execution_id

        return FlatMachine(
            config_file=config_file,
            config_dict=config_dict,
            persistence=self._persistence,
            lock=self._lock,
            config_store=self._config_store,
            signal_backend=self._signal_backend,
            trigger_backend=self._trigger_backend,
            result_backend=self._result_backend or get_default_result_backend(),
            hooks=hooks or self._hooks,
            hooks_registry=self._hooks_registry,
            agent_registry=self._agent_registry,
            profiles_file=self._profiles_file,
            tool_provider=self._tool_provider,
            **build_kwargs,
            **kwargs,
        )

    # ─── Create ───────────────────────────────────────────────────────────

    async def create(
        self,
        config_file: Optional[str] = None,
        config_dict: Optional[Dict[str, Any]] = None,
        execution_id: Optional[str] = None,
        **kwargs,
    ) -> MachineHandle:
        """Create a machine instance without starting execution.

        Returns a MachineHandle that can be passed to ``start()``.
        The machine is constructed and validated but no states are executed.

        Args:
            config_file: Path to YAML/JSON config file.
            config_dict: Configuration dictionary (alternative to file).
            execution_id: Predetermined execution ID (auto-generated if omitted).
            **kwargs: Additional FlatMachine constructor arguments.

        Returns:
            MachineHandle with the assigned execution_id.
        """
        machine = self._build_machine(
            config_file=config_file,
            config_dict=config_dict,
            execution_id=execution_id,
            **kwargs,
        )
        return MachineHandle(
            execution_id=machine.execution_id,
            machine_name=machine.machine_name,
            spec_version=machine.spec_version,
            config_dict=config_dict,
            config_file=config_file,
        )

    # ─── Start ────────────────────────────────────────────────────────────

    async def start(
        self,
        execution_id: Optional[str] = None,
        *,
        config_file: Optional[str] = None,
        config_dict: Optional[Dict[str, Any]] = None,
        input: Optional[Dict[str, Any]] = None,
        max_steps: int = 1000,
        max_agent_calls: Optional[int] = None,
        hooks: Optional[MachineHooks] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """Start machine execution.

        Can be called with:
        - ``execution_id`` only: reconstructs from checkpoint (resume).
        - ``config_file`` or ``config_dict``: creates and runs a new machine.
        - ``execution_id`` + config: creates with predetermined ID and runs.

        Args:
            execution_id: Execution ID (for resume or predetermined ID).
            config_file: Path to config file.
            config_dict: Config dictionary.
            input: Input data for initial context.
            max_steps: Maximum state transitions.
            max_agent_calls: Maximum total agent API calls.
            hooks: Override hooks for this execution.
            **kwargs: Additional FlatMachine constructor arguments.

        Returns:
            The machine's final output dict.
        """
        machine = self._build_machine(
            config_file=config_file,
            config_dict=config_dict,
            execution_id=execution_id,
            hooks=hooks,
            **kwargs,
        )
        return await machine.execute(
            input=input,
            max_steps=max_steps,
            max_agent_calls=max_agent_calls,
        )

    # ─── Run (create + start) ────────────────────────────────────────────

    async def run(
        self,
        config_file: Optional[str] = None,
        config_dict: Optional[Dict[str, Any]] = None,
        input: Optional[Dict[str, Any]] = None,
        max_steps: int = 1000,
        max_agent_calls: Optional[int] = None,
        hooks: Optional[MachineHooks] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """Create and execute a machine in one call.

        Convenience method equivalent to ``create()`` + ``start()``.

        Returns:
            The machine's final output dict.
        """
        return await self.start(
            config_file=config_file,
            config_dict=config_dict,
            input=input,
            max_steps=max_steps,
            max_agent_calls=max_agent_calls,
            hooks=hooks,
            **kwargs,
        )

    # ─── Get ──────────────────────────────────────────────────────────────

    async def get(self, execution_id: str) -> Optional[MachineInfo]:
        """Get the current status of a machine execution.

        Loads the latest checkpoint and returns a MachineInfo snapshot.
        Returns None if no checkpoint exists for the given ID.

        Args:
            execution_id: The execution ID to look up.

        Returns:
            MachineInfo or None.
        """
        manager = CheckpointManager(self._persistence, execution_id)
        snapshot = await manager.load_latest()
        if snapshot is None:
            return None
        return self._snapshot_to_info(snapshot)

    # ─── List ─────────────────────────────────────────────────────────────

    async def list(
        self,
        *,
        status: Optional[str] = None,
        waiting_channel: Optional[str] = None,
    ) -> List[MachineInfo]:
        """List machine executions, optionally filtered.

        Args:
            status: Filter by status:
                - ``"completed"``: machines with ``machine_end`` event.
                - ``"waiting"``: machines with a ``waiting_channel``.
                - ``"active"``: machines that are neither completed nor waiting.
                - ``None``: all machines.
            waiting_channel: Filter by specific waiting channel.

        Returns:
            List of MachineInfo snapshots.
        """
        # Map status to persistence query params
        event_filter = None
        if status == "completed":
            event_filter = "machine_end"
        if status == "waiting" and not waiting_channel:
            # Need to find all with any waiting_channel — list all, then filter
            pass

        if waiting_channel:
            exec_ids = await self._persistence.list_execution_ids(
                waiting_channel=waiting_channel,
            )
        elif event_filter:
            exec_ids = await self._persistence.list_execution_ids(event=event_filter)
        else:
            exec_ids = await self._persistence.list_execution_ids()

        results = []
        for eid in exec_ids:
            info = await self.get(eid)
            if info is None:
                continue

            # Post-filter for status categories not directly queryable
            if status == "active" and not info.is_active:
                continue
            if status == "waiting" and not info.is_waiting:
                continue

            results.append(info)

        return results

    # ─── Resume ───────────────────────────────────────────────────────────

    async def resume(
        self,
        execution_id: str,
        *,
        config_file: Optional[str] = None,
        config_dict: Optional[Dict[str, Any]] = None,
        max_steps: int = 1000,
        max_agent_calls: Optional[int] = None,
        hooks: Optional[MachineHooks] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """Resume a previously checkpointed machine execution.

        If ``config_file`` or ``config_dict`` is provided, the machine is
        reconstructed from that config.  Otherwise the API attempts to
        load the config from the config store (requires ``config_store``
        and a checkpoint with ``config_hash``).

        Args:
            execution_id: The execution to resume.
            config_file: Config file for reconstruction.
            config_dict: Config dict for reconstruction.
            max_steps: Maximum state transitions.
            max_agent_calls: Maximum agent API calls.
            hooks: Override hooks.
            **kwargs: Additional FlatMachine constructor arguments.

        Returns:
            The machine's final output dict.
        """
        # If no config provided, try loading from config store
        if config_file is None and config_dict is None:
            config_dict = await self._load_config_for_execution(execution_id)

        machine = self._build_machine(
            config_file=config_file,
            config_dict=config_dict,
            hooks=hooks,
            **kwargs,
        )
        return await machine.execute(
            resume_from=execution_id,
            max_steps=max_steps,
            max_agent_calls=max_agent_calls,
        )

    # ─── Delete ───────────────────────────────────────────────────────────

    async def delete(self, execution_id: str) -> bool:
        """Delete all checkpoint data for an execution.

        Returns True if data existed, False otherwise.
        """
        info = await self.get(execution_id)
        if info is None:
            return False
        await self._persistence.delete_execution(execution_id)
        return True

    # ─── Helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _snapshot_to_info(snapshot: MachineSnapshot) -> MachineInfo:
        return MachineInfo(
            execution_id=snapshot.execution_id,
            machine_name=snapshot.machine_name,
            current_state=snapshot.current_state,
            step=snapshot.step,
            event=snapshot.event,
            output=snapshot.output,
            total_api_calls=snapshot.total_api_calls or 0,
            total_cost=snapshot.total_cost or 0.0,
            parent_execution_id=snapshot.parent_execution_id,
            waiting_channel=snapshot.waiting_channel,
            created_at=snapshot.created_at,
        )

    async def _load_config_for_execution(
        self, execution_id: str
    ) -> Dict[str, Any]:
        """Load config dict from config store using the checkpoint's config_hash."""
        if self._config_store is None:
            raise RuntimeError(
                f"Cannot resume {execution_id}: no config_file/config_dict provided "
                "and no config_store configured on the API."
            )
        manager = CheckpointManager(self._persistence, execution_id)
        snapshot = await manager.load_latest()
        if snapshot is None:
            raise RuntimeError(f"No checkpoint found for execution {execution_id}")
        if not snapshot.config_hash:
            raise RuntimeError(
                f"Checkpoint for {execution_id} has no config_hash. "
                "Machine was created without a config_store."
            )
        raw = await self._config_store.get(snapshot.config_hash)
        if raw is None:
            raise RuntimeError(
                f"Config not found in store for hash {snapshot.config_hash}."
            )
        try:
            import yaml
            return yaml.safe_load(raw)
        except ImportError:
            import json
            return json.loads(raw)


__all__ = [
    "MachineExecutionAPI",
    "MachineHandle",
    "MachineInfo",
]

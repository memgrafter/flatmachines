"""
Machine resume abstraction.

Provides an ABC for resuming parked machines and a concrete implementation
that reconstructs from the config stored in a content-addressed ConfigStore,
referenced by the checkpoint's ``config_hash``.

Usage (simple — no hooks):

    resumer = ConfigStoreResumer(signal_backend, persistence, config_store)
    dispatcher = SignalDispatcher(signal_backend, persistence, resumer=resumer)

Usage (with hooks registry):

    registry = HooksRegistry()
    registry.register("my-hooks", MyHooks)
    resumer = ConfigStoreResumer(
        signal_backend, persistence, config_store,
        hooks_registry=registry,
    )

Usage (subclass for app-specific reconstruction):

    class MyResumer(ConfigStoreResumer):
        def __init__(self, signal_backend, persistence, config_store, db_path):
            super().__init__(signal_backend, persistence, config_store)
            self._db_path = db_path

        async def build_machine(self, execution_id, snapshot, config_dict):
            machine = await super().build_machine(execution_id, snapshot, config_dict)
            # ... customize machine ...
            return machine
"""

import inspect
import json
import logging
from abc import ABC, abstractmethod
from typing import Any, Awaitable, Callable, Dict, Optional, Protocol

from .hooks import MachineHooks, HooksRegistry
from .persistence import (
    CheckpointManager,
    ConfigStore,
    MachineSnapshot,
    PersistenceBackend,
)
from .signals import SignalBackend

logger = logging.getLogger(__name__)


class ReferenceResolver(Protocol):
    """Resolve string refs in agents/machines during portable resume.

    Called with the owner machine identity (name + config hash), the ref kind
    ("agent" or "machine"), ref key name, and string ref value.

    Return an inline config dict to replace the string ref, or None if unknown.
    """

    def __call__(
        self,
        *,
        machine_name: str,
        config_hash: str,
        ref_kind: str,
        ref_name: str,
        ref_value: str,
    ) -> Optional[Dict[str, Any]] | Awaitable[Optional[Dict[str, Any]]]:
        ...


class MachineResumer(ABC):
    """Knows how to reconstruct and resume a parked machine from checkpoint."""

    @abstractmethod
    async def resume(self, execution_id: str, signal_data: Any) -> Any:
        """Resume a parked machine.

        Args:
            execution_id: The execution ID of the parked machine.
            signal_data: Data from the signal that triggered resume.

        Returns:
            The machine's final output dict.
        """
        ...


class ConfigStoreResumer(MachineResumer):
    """Resumes a machine from config stored in a content-addressed ConfigStore.

    Reads ``config_hash`` from the checkpoint, fetches the raw config from the
    store, parses it, and reconstructs the FlatMachine.

    Supports optional hooks, hooks_registry, and tool_provider injection.
    If a hooks_registry is provided and the machine config references hooks
    by name, they will be resolved automatically — same as initial execution.

    For app-specific reconstruction (custom DB connections, environment setup,
    etc.), subclass and override ``build_machine()``.

    Args:
        signal_backend: Signal storage backend.
        persistence_backend: Checkpoint persistence backend.
        config_store: Content-addressed config store.
        ref_resolver: Optional resolver for string refs in agents/machines.
            Portable resume rejects path/string refs unless this is provided.
        hooks: Explicit MachineHooks instance (bypasses registry).
        hooks_registry: Registry for resolving hooks by name from config.
        tool_provider: Default ToolProvider for tool_loop states.
    """

    def __init__(
        self,
        signal_backend: SignalBackend,
        persistence_backend: PersistenceBackend,
        config_store: ConfigStore,
        ref_resolver: Optional[ReferenceResolver] = None,
        hooks: Optional[MachineHooks] = None,
        hooks_registry: Optional[HooksRegistry] = None,
        tool_provider: Optional[Any] = None,
    ):
        self._signal_backend = signal_backend
        self._persistence = persistence_backend
        self._config_store = config_store
        self._ref_resolver = ref_resolver
        self._hooks = hooks
        self._hooks_registry = hooks_registry
        self._tool_provider = tool_provider

    async def _load_snapshot(self, execution_id: str) -> MachineSnapshot:
        """Load the latest checkpoint for an execution ID."""
        snapshot = await CheckpointManager(
            self._persistence, execution_id
        ).load_latest()
        if not snapshot:
            raise RuntimeError(f"No checkpoint found for execution {execution_id}")
        return snapshot

    async def _resolve_ref(
        self,
        *,
        machine_name: str,
        config_hash: str,
        ref_kind: str,
        ref_name: str,
        ref_value: str,
    ) -> Dict[str, Any]:
        """Resolve a string ref using the optional registry callback."""
        if self._ref_resolver is None:
            raise RuntimeError(
                "Portable resume does not support string/path refs without a ref_resolver. "
                f"Found {ref_kind}s.{ref_name}={ref_value!r} in machine={machine_name} hash={config_hash}."
            )

        resolved = self._ref_resolver(
            machine_name=machine_name,
            config_hash=config_hash,
            ref_kind=ref_kind,
            ref_name=ref_name,
            ref_value=ref_value,
        )
        if inspect.isawaitable(resolved):
            resolved = await resolved

        if resolved is None:
            raise RuntimeError(
                f"ref_resolver could not resolve {ref_kind}s.{ref_name}={ref_value!r} "
                f"for machine={machine_name} hash={config_hash}."
            )
        if not isinstance(resolved, dict):
            raise TypeError(
                "ref_resolver must return a dict (inline config) or None; "
                f"got {type(resolved)} for {ref_kind}s.{ref_name}."
            )
        return resolved

    async def _materialize_string_refs(
        self,
        config_dict: Dict[str, Any],
        *,
        machine_name: str,
        config_hash: str,
    ) -> Dict[str, Any]:
        """Materialize string refs in agents/machines via ref_resolver.

        In portable/hash-based resume we do not guess path semantics (cwd/config_dir).
        String refs are treated as unresolved references and require explicit resolution.
        """
        data = config_dict.get("data")
        if not isinstance(data, dict):
            return config_dict

        for ref_kind, section in (("agent", "agents"), ("machine", "machines")):
            refs = data.get(section)
            if not isinstance(refs, dict):
                continue
            for ref_name, ref_value in list(refs.items()):
                if not isinstance(ref_value, str):
                    continue
                refs[ref_name] = await self._resolve_ref(
                    machine_name=machine_name,
                    config_hash=config_hash,
                    ref_kind=ref_kind,
                    ref_name=ref_name,
                    ref_value=ref_value,
                )

        return config_dict

    async def _load_config(self, snapshot: MachineSnapshot) -> Dict[str, Any]:
        """Load and parse config from the config store."""
        if not snapshot.config_hash:
            raise RuntimeError(
                f"No config_hash in checkpoint for execution {snapshot.execution_id}. "
                f"Machine was created without a config_store. "
                f"Provide a custom MachineResumer subclass for this case."
            )

        raw = await self._config_store.get(snapshot.config_hash)
        if raw is None:
            raise RuntimeError(
                f"Config not found in store for hash {snapshot.config_hash}. "
                f"The config store may have been cleaned up."
            )

        # Parse YAML or JSON
        try:
            import yaml
            config_dict = yaml.safe_load(raw)
        except ImportError:
            config_dict = json.loads(raw)

        return await self._materialize_string_refs(
            config_dict,
            machine_name=snapshot.machine_name,
            config_hash=snapshot.config_hash,
        )

    async def build_machine(
        self,
        execution_id: str,
        snapshot: MachineSnapshot,
        config_dict: Dict[str, Any],
    ):
        """Construct a FlatMachine ready for resume.

        Override this method to customize machine reconstruction (e.g.
        inject app-specific hooks, tools, or environment).

        Args:
            execution_id: The execution ID to resume.
            snapshot: The latest checkpoint snapshot.
            config_dict: Parsed machine config from the config store.

        Returns:
            A FlatMachine instance configured for resume.
        """
        from .flatmachine import FlatMachine

        return FlatMachine(
            config_dict=config_dict,
            persistence=self._persistence,
            signal_backend=self._signal_backend,
            config_store=self._config_store,
            hooks=self._hooks,
            hooks_registry=self._hooks_registry,
            tool_provider=self._tool_provider,
        )

    async def resume(self, execution_id: str, signal_data: Any) -> Any:
        """Load checkpoint, reconstruct machine, and resume execution."""
        snapshot = await self._load_snapshot(execution_id)
        config_dict = await self._load_config(snapshot)
        machine = await self.build_machine(execution_id, snapshot, config_dict)
        result = await machine.execute(resume_from=execution_id)
        logger.info(f"Resumed {execution_id}: {result}")
        return result


# Backward-compatible alias
ConfigFileResumer = ConfigStoreResumer

__all__ = [
    "MachineResumer",
    "ReferenceResolver",
    "ConfigStoreResumer",
    "ConfigFileResumer",
]

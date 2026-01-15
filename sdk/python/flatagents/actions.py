from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, TYPE_CHECKING
import logging

if TYPE_CHECKING:
    from .flatmachine import FlatMachine

logger = logging.getLogger(__name__)

class Action(ABC):
    """
    Base class for state actions (when state has 'action:' key).
    """
    
    @abstractmethod
    async def execute(
        self,
        action_name: str,
        context: Dict[str, Any],
        config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Execute the action.
        Returns modified context.
        """
        pass

class HookAction(Action):
    """
    Default action: delegates to machine hooks (on_action).
    """
    
    def __init__(self, hooks):
        self.hooks = hooks
        
    async def execute(
        self,
        action_name: str,
        context: Dict[str, Any],
        config: Dict[str, Any]
    ) -> Dict[str, Any]:
        return self.hooks.on_action(action_name, context)

# -------------------------------------------------------------------------
# Machine Invokers (Graph Execution)
# -------------------------------------------------------------------------

class MachineInvoker(ABC):
    """
    Interface for invoking other machines (graph execution).
    """
    
    @abstractmethod
    async def invoke(
        self,
        caller_machine: 'FlatMachine',
        target_config: Dict[str, Any],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Invoke another machine.
        Returns output (if sync) or raises exception (if async/detached).
        """
        pass

class InlineInvoker(MachineInvoker):
    """
    Default v1 Invoker.
    Runs target machine in same process (synchronous await).
    """
    
    async def invoke(
        self,
        caller_machine: 'FlatMachine',
        target_config: Dict[str, Any],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        from .flatmachine import FlatMachine  # lazy import to avoid cycle
        import hashlib
        
        # Get machine name from nested data.name (not top-level)
        target_name = target_config.get('data', {}).get('name', 'unknown')
        
        # Create a unique ID per invocation by hashing the context
        # This ensures each loop iteration gets its own checkpoint
        context_hash = hashlib.md5(str(sorted(context.items())).encode()).hexdigest()[:8]
        target_id = f"{caller_machine.execution_id}:peer:{target_name}:{context_hash}"

        logger.info(f"Launching peer machine: {target_name} (ID: {target_id})")
        
        # Determine if we should reuse launcher's persistence/lock
        # (Usually yes for inline execution)
        target = FlatMachine(
            config_dict=target_config,  # Must use config_dict, not config
            # Pass down launcher's backend/lock to keep everything in same storage
            persistence=caller_machine.persistence,
            lock=caller_machine.lock,
            # Inherit config_dir so relative agent paths resolve correctly
            _config_dir=caller_machine._config_dir
        )
        
        # Execute peer
        # Note: resume_from=target_id ensures if we crash and retry, we pick up
        # where the peer left off (or use its existing result)
        result = await target.execute(
            input=context,
            resume_from=target_id
        )
        
        # Aggregate peer machine stats back to launcher
        caller_machine.total_api_calls += target.total_api_calls
        caller_machine.total_cost += target.total_cost
        
        return result

class CloudInvoker(MachineInvoker):
    """STUB: Future AWS Step Functions / Lambda invoker."""
    async def invoke(self, caller, target, context):
        raise NotImplementedError("Distributed execution is a v2 feature")

class HttpInvoker(MachineInvoker):
    """STUB: Future REST/Webhook invoker."""
    async def invoke(self, caller, target, context):
        raise NotImplementedError("HTTP execution is a v2 feature")

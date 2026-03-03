from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, TYPE_CHECKING
import logging
import os

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
        import asyncio
        result = self.hooks.on_action(action_name, context)
        if asyncio.iscoroutine(result):
            return await result
        return result

# -------------------------------------------------------------------------
# Machine Invokers (Graph Execution)
# -------------------------------------------------------------------------

class MachineInvoker(ABC):
    """
    Interface for invoking other machines (graph execution).
    
    See flatagents-runtime.d.ts for canonical interface definition.
    """
    
    @abstractmethod
    async def invoke(
        self,
        caller_machine: 'FlatMachine',
        target_config: Dict[str, Any],
        input_data: Dict[str, Any],
        execution_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Invoke another machine and wait for result.
        
        Args:
            caller_machine: The machine initiating the call
            target_config: Config dict for the target machine
            input_data: Input to pass to the target machine
            execution_id: Optional predetermined ID (for resume support)
        
        Returns:
            The target machine's output
        """
        pass
    
    @abstractmethod
    async def launch(
        self,
        caller_machine: 'FlatMachine',
        target_config: Dict[str, Any],
        input_data: Dict[str, Any],
        execution_id: str
    ) -> None:
        """
        Launch a machine fire-and-forget style.
        
        The launched machine runs independently. Results are written
        to the result backend using the execution_id.
        
        Args:
            caller_machine: The machine initiating the launch
            target_config: Config dict for the target machine
            input_data: Input to pass to the target machine
            execution_id: The predetermined execution ID for the launched machine
        """
        pass

class InlineInvoker(MachineInvoker):
    """
    Default Invoker for local execution.
    
    - invoke(): Runs target machine in same event loop, awaits result
    - launch(): Creates background task, returns immediately
    
    Both share the same persistence/lock backends as the caller.
    """
    
    def __init__(self):
        # Track background tasks for cleanup
        self._background_tasks: set = set()
    
    async def invoke(
        self,
        caller_machine: 'FlatMachine',
        target_config: Dict[str, Any],
        input_data: Dict[str, Any],
        execution_id: Optional[str] = None
    ) -> Dict[str, Any]:
        from .flatmachine import FlatMachine  # lazy import to avoid cycle
        import hashlib
        
        target_name = target_config.get('data', {}).get('name', 'unknown')
        
        # Generate execution_id if not provided
        if not execution_id:
            context_hash = hashlib.md5(str(sorted(input_data.items())).encode()).hexdigest()[:8]
            execution_id = f"{caller_machine.execution_id}:peer:{target_name}:{context_hash}"

        logger.info(f"Invoking peer machine: {target_name} (ID: {execution_id})")
        
        target = FlatMachine(
            config_dict=target_config,
            hooks_registry=getattr(caller_machine, "_hooks_registry", None),
            persistence=caller_machine.persistence,
            lock=caller_machine.lock,
            result_backend=caller_machine.result_backend,
            agent_registry=caller_machine.agent_registry,
            _config_dir=caller_machine._config_dir,
            _execution_id=execution_id,
            _parent_execution_id=caller_machine.execution_id,
            _profiles_dict=getattr(caller_machine, "_profiles_dict", None),
            _profiles_file=getattr(caller_machine, "_profiles_file", None),
        )
        
        result = await target.execute(input=input_data, resume_from=execution_id)
        
        # Aggregate stats back to caller
        caller_machine.total_api_calls += target.total_api_calls
        caller_machine.total_cost += target.total_cost
        
        return result
    
    async def launch(
        self,
        caller_machine: 'FlatMachine',
        target_config: Dict[str, Any],
        input_data: Dict[str, Any],
        execution_id: str
    ) -> None:
        import asyncio
        from .flatmachine import FlatMachine
        from .backends import make_uri
        
        target_name = target_config.get('data', {}).get('name', 'unknown')
        logger.info(f"Launching peer machine (fire-and-forget): {target_name} (ID: {execution_id})")
        
        async def _execute_and_write():
            target = FlatMachine(
                config_dict=target_config,
                hooks_registry=getattr(caller_machine, "_hooks_registry", None),
                persistence=caller_machine.persistence,
                lock=caller_machine.lock,
                result_backend=caller_machine.result_backend,
                agent_registry=caller_machine.agent_registry,
                _config_dir=caller_machine._config_dir,
                _execution_id=execution_id,
                _parent_execution_id=caller_machine.execution_id,
                _profiles_dict=getattr(caller_machine, "_profiles_dict", None),
                _profiles_file=getattr(caller_machine, "_profiles_file", None),
            )
            
            try:
                result = await target.execute(input=input_data)
                # Write result to backend so parent can read if needed
                uri = make_uri(execution_id, "result")
                await caller_machine.result_backend.write(uri, result)
            except Exception as e:
                uri = make_uri(execution_id, "result")
                await caller_machine.result_backend.write(uri, {
                    "_error": str(e),
                    "_error_type": type(e).__name__
                })
                raise
        
        # Create background task
        task = asyncio.create_task(_execute_and_write())
        caller_machine._background_tasks.add(task)
        task.add_done_callback(caller_machine._background_tasks.discard)


class QueueInvoker(MachineInvoker):
    """
    Invoker that enqueues launches to an external queue.
    
    For production deployments using SQS, Cloud Tasks, etc.
    Subclass and implement _enqueue() for your queue provider.
    """
    
    async def invoke(
        self,
        caller_machine: 'FlatMachine',
        target_config: Dict[str, Any],
        input_data: Dict[str, Any],
        execution_id: Optional[str] = None
    ) -> Dict[str, Any]:
        # For queue-based invocation, we launch and then poll for result
        import uuid
        from .backends import make_uri
        
        if not execution_id:
            execution_id = str(uuid.uuid4())
        
        await self.launch(caller_machine, target_config, input_data, execution_id)
        
        # Block until result is available
        uri = make_uri(execution_id, "result")
        return await caller_machine.result_backend.read(uri, block=True)
    
    async def launch(
        self,
        caller_machine: 'FlatMachine',
        target_config: Dict[str, Any],
        input_data: Dict[str, Any],
        execution_id: str
    ) -> None:
        await self._enqueue(execution_id, target_config, input_data)
    
    async def _enqueue(
        self,
        execution_id: str,
        config: Dict[str, Any],
        input_data: Dict[str, Any]
    ) -> None:
        """Override in subclass to enqueue to your queue provider."""
        raise NotImplementedError("Subclass must implement _enqueue()")


class SubprocessInvoker(MachineInvoker):
    """
    Invoker that launches machines as independent subprocesses.
    
    For local distributed execution where each worker is a separate process.
    Used by the parallelization checker to spawn worker machines.
    
    The subprocess runs `python -m flatmachines.run` with the machine config,
    enabling true process isolation and independent lifecycle.
    """
    
    def __init__(self, 
                 machine_path: Optional[str] = None,
                 working_dir: Optional[str] = None):
        """
        Args:
            machine_path: Base path for resolving machine configs
            working_dir: Working directory for spawned processes
        """
        self.machine_path = machine_path
        self.working_dir = working_dir
    
    async def invoke(
        self,
        caller_machine: 'FlatMachine',
        target_config: Dict[str, Any],
        input_data: Dict[str, Any],
        execution_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Launch subprocess and poll for result."""
        import uuid
        from .backends import make_uri
        
        if not execution_id:
            execution_id = str(uuid.uuid4())
        
        await self.launch(caller_machine, target_config, input_data, execution_id)
        
        # Block until result is available
        uri = make_uri(execution_id, "result")
        return await caller_machine.result_backend.read(uri, block=True)
    
    async def launch(
        self,
        caller_machine: 'FlatMachine',
        target_config: Dict[str, Any],
        input_data: Dict[str, Any],
        execution_id: str
    ) -> None:
        """Launch machine as independent subprocess (fire-and-forget)."""
        import subprocess
        import sys
        import json
        import tempfile
        import os
        
        target_name = target_config.get('data', {}).get('name', 'unknown')
        logger.info(f"Launching subprocess: {target_name} (ID: {execution_id})")
        
        # Write config to temp file for subprocess to read
        with tempfile.NamedTemporaryFile(
            mode='w', 
            suffix='.json', 
            delete=False,
            dir=self.working_dir
        ) as f:
            json.dump(target_config, f)
            config_path = f.name
        
        # Build command
        cmd = [
            sys.executable, "-m", "flatmachines.run",
            "--config", config_path,
            "--input", json.dumps(input_data),
            "--execution-id", execution_id,
        ]
        
        # Add parent execution ID for lineage tracking
        if caller_machine.execution_id:
            cmd.extend(["--parent-id", caller_machine.execution_id])
        
        # Spawn detached process
        cwd = self.working_dir or caller_machine._config_dir
        
        # Use Popen for fire-and-forget — inherit stdout/stderr
        subprocess.Popen(
            cmd,
            cwd=cwd,
            start_new_session=True  # Detach from parent process group
        )
        
        logger.debug(f"Subprocess launched: {' '.join(cmd)}")


def launch_machine(
    machine_config: str,
    input_data: Dict[str, Any],
    execution_id: Optional[str] = None,
    working_dir: Optional[str] = None,
    parent_id: Optional[str] = None
) -> str:
    """
    Fire-and-forget machine execution via subprocess.
    
    Standalone utility function for launching machines without an existing
    FlatMachine context. Useful for trigger scripts and manual invocation.
    
    Args:
        machine_config: Path to machine YAML file
        input_data: Input dictionary for the machine
        execution_id: Optional predetermined execution ID
        working_dir: Working directory for the subprocess
        parent_id: Optional parent execution ID for lineage
        
    Returns:
        The execution ID of the launched machine
        
    Example:
        # From a trigger script
        exec_id = launch_machine(
            "job_worker.yml",
            {"pool_id": "paper_analysis"},
            working_dir="/path/to/project"
        )
    """
    import subprocess
    import sys
    import json
    import uuid
    
    if not execution_id:
        execution_id = str(uuid.uuid4())
    
    cmd = [
        sys.executable, "-m", "flatmachines.run",
        "--config", machine_config,
        "--input", json.dumps(input_data),
        "--execution-id", execution_id,
    ]
    
    if parent_id:
        cmd.extend(["--parent-id", parent_id])
    
    subprocess.Popen(
        cmd,
        cwd=working_dir,
        env=os.environ.copy(),  # Pass parent environment (includes PYTHONPATH, venv)
        start_new_session=True
    )
    
    logger.info(f"Launched machine subprocess: {machine_config} (ID: {execution_id})")
    return execution_id


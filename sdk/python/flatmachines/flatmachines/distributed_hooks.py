"""
Base hooks for distributed worker patterns.

Provides ready-to-use action handlers for:
- Pool management (get_pool_state, claim_job, complete_job, fail_job)
- Worker lifecycle (register_worker, deregister_worker, heartbeat)
- Reaper (list_stale_workers, reap_worker, reap_stale_workers)
- Auto-scaling (calculate_spawn, spawn_workers)

Users extend this class and add custom job-processing actions.

Example:
    from flatmachines import DistributedWorkerHooks, SQLiteRegistrationBackend, SQLiteWorkBackend
    
    class MyHooks(DistributedWorkerHooks):
        def __init__(self):
            super().__init__(
                registration=SQLiteRegistrationBackend(db_path="./data/workers.db"),
                work=SQLiteWorkBackend(db_path="./data/workers.db"),
            )
        
        async def _process_my_job(self, context):
            # Custom job processing
            return context
"""

import logging
from typing import Dict, Any, Optional, Protocol, List, TYPE_CHECKING

from .hooks import MachineHooks
from .distributed import (
    RegistrationBackend,
    WorkBackend,
    WorkerRegistration,
    WorkerFilter,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class DistributedWorkerHooks(MachineHooks):
    """
    Ready-to-use hooks for distributed worker patterns.
    
    Provides standard actions for work distribution, worker lifecycle,
    stale worker cleanup, and auto-scaling.
    
    Extend this class and add your own job-processing actions.
    """
    
    def __init__(
        self,
        registration: RegistrationBackend,
        work: WorkBackend,
    ):
        """
        Initialize with backend instances.
        
        Args:
            registration: Backend for worker registration/lifecycle
            work: Backend for work pool operations
        """
        self._registration = registration
        self._work = work
    
    async def on_action(self, state_name: str, action: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Route action names to handler methods for a state-local action."""
        
        # Standard distributed worker actions
        handlers = {
            # Pool state (for checkers)
            "get_pool_state": self._get_pool_state,
            
            # Job operations (for workers)
            "claim_job": self._claim_job,
            "complete_job": self._complete_job,
            "fail_job": self._fail_job,
            
            # Worker lifecycle
            "register_worker": self._register_worker,
            "deregister_worker": self._deregister_worker,
            "heartbeat": self._heartbeat,
            
            # Reaper operations
            "list_stale_workers": self._list_stale_workers,
            "reap_worker": self._reap_worker,
            "reap_stale_workers": self._reap_stale_workers,
            
            # Auto-scaling
            "calculate_spawn": self._calculate_spawn,
            "spawn_workers": self._spawn_workers,
        }
        
        handler = handlers.get(action)
        if handler:
            return await handler(context)
        
        # Fall through to subclass or default behavior
        return context
    
    # -------------------------------------------------------------------------
    # Pool State Actions (for parallelization checker)
    # -------------------------------------------------------------------------
    
    async def _get_pool_state(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Get current pool depth and active worker count."""
        pool_id = context.get("pool_id", "default")
        
        pool = self._work.pool(pool_id)
        workers = await self._registration.list(WorkerFilter(status="active"))
        
        # Merge output into context (preserve existing context keys)
        context["queue_depth"] = await pool.size()
        context["active_workers"] = len(workers)
        return context
    
    # -------------------------------------------------------------------------
    # Job Actions (for job workers)
    # -------------------------------------------------------------------------
    
    async def _claim_job(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Atomically claim the next available job."""
        pool_id = context.get("pool_id", "default")
        worker_id = context.get("worker_id")
        
        if not worker_id:
            raise ValueError("worker_id is required for claim_job")
        
        pool = self._work.pool(pool_id)
        item = await pool.claim(worker_id)
        
        if item:
            context["job"] = item.data
            context["job_id"] = item.id
        else:
            context["job"] = None
            context["job_id"] = None
        return context
    
    async def _complete_job(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Mark job as successfully completed."""
        pool_id = context.get("pool_id", "default")
        job_id = context.get("job_id")
        result = context.get("result")
        
        if not job_id:
            raise ValueError("job_id is required for complete_job")
        
        pool = self._work.pool(pool_id)
        await pool.complete(job_id, result)
        
        return context
    
    async def _fail_job(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Mark job as failed. Will retry or poison based on attempts."""
        pool_id = context.get("pool_id", "default")
        job_id = context.get("job_id")
        error = context.get("error")
        
        if not job_id:
            raise ValueError("job_id is required for fail_job")
        
        pool = self._work.pool(pool_id)
        await pool.fail(job_id, error)
        
        return context
    
    # -------------------------------------------------------------------------
    # Worker Lifecycle Actions
    # -------------------------------------------------------------------------
    
    async def _register_worker(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Register a new worker."""
        import socket
        import os
        
        worker_id = context.get("worker_id")
        if not worker_id:
            raise ValueError("worker_id is required for register_worker")
        
        registration = WorkerRegistration(
            worker_id=worker_id,
            host=socket.gethostname(),
            pid=os.getpid(),
            capabilities=context.get("capabilities", []),
        )
        
        record = await self._registration.register(registration)
        
        # Merge output into context
        context["worker_id"] = record.worker_id
        context["status"] = record.status
        context["registered_at"] = record.started_at
        return context
    
    async def _deregister_worker(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Mark worker as terminated (clean shutdown)."""
        worker_id = context.get("worker_id")
        if not worker_id:
            raise ValueError("worker_id is required for deregister_worker")
        
        await self._registration.update_status(worker_id, "terminated")
        
        return context
    
    async def _heartbeat(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Send heartbeat for a worker."""
        worker_id = context.get("worker_id")
        if not worker_id:
            raise ValueError("worker_id is required for heartbeat")
        
        await self._registration.heartbeat(worker_id)
        
        return context
    
    # -------------------------------------------------------------------------
    # Reaper Actions
    # -------------------------------------------------------------------------
    
    async def _list_stale_workers(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Find workers that have missed heartbeat threshold."""
        threshold = context.get("stale_threshold_seconds", 60)
        
        workers = await self._registration.list(WorkerFilter(
            status="active",
            stale_threshold_seconds=threshold,
        ))
        
        stale_workers = [
            {
                "worker_id": w.worker_id,
                "last_heartbeat": w.last_heartbeat,
                "host": w.host,
            }
            for w in workers
        ]
        
        # Merge into context with count for condition evaluation
        context["workers"] = stale_workers
        context["stale_count"] = len(stale_workers)
        return context
    
    async def _reap_worker(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Mark worker as lost and release their claimed jobs."""
        worker = context.get("worker")
        pool_id = context.get("pool_id", "default")
        
        if not worker:
            raise ValueError("worker is required for reap_worker")
        
        worker_id = worker.get("worker_id")
        
        # Mark as lost
        await self._registration.update_status(worker_id, "lost")
        
        # Release any jobs claimed by this worker
        pool = self._work.pool(pool_id)
        released = await pool.release_by_worker(worker_id)
        
        context["reaped_worker_id"] = worker_id
        context["jobs_released"] = released
        return context
    
    async def _reap_stale_workers(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Reap all stale workers in one action (batch processing)."""
        stale_workers = context.get("stale_workers", [])
        pool_id = context.get("pool_id", "default")
        
        reaped = []
        total_jobs_released = 0
        
        for worker in stale_workers:
            worker_id = worker.get("worker_id")
            
            # Mark as lost
            await self._registration.update_status(worker_id, "lost")
            
            # Release any jobs claimed by this worker
            pool = self._work.pool(pool_id)
            released = await pool.release_by_worker(worker_id)
            
            reaped.append(worker_id)
            total_jobs_released += released
        
        context["reaped_workers"] = reaped
        context["reaped_count"] = len(reaped)
        context["total_jobs_released"] = total_jobs_released
        return context
    
    # -------------------------------------------------------------------------
    # Auto-Scaling Actions (for parallelization checker)
    # -------------------------------------------------------------------------
    
    async def _calculate_spawn(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Calculate how many workers to spawn based on pool state.
        
        Default strategy: workers_needed = min(queue_depth, max_workers)
        Override this method for custom scaling logic.
        """
        queue_depth = int(context.get("queue_depth", 0))
        active_workers = int(context.get("active_workers", 0))
        max_workers = int(context.get("max_workers", 3))
        
        # Workers needed = min(queue_depth, max_workers)
        workers_needed = min(queue_depth, max_workers)
        
        # Workers to spawn = max(0, workers_needed - active_workers)
        workers_to_spawn = max(0, workers_needed - active_workers)
        
        context["workers_needed"] = workers_needed
        context["workers_to_spawn"] = workers_to_spawn
        context["spawn_list"] = list(range(workers_to_spawn))  # For foreach iteration
        return context
    
    async def _spawn_workers(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Spawn worker subprocesses based on workers_to_spawn count.
        
        Requires `worker_config_path` in context - the path to the worker YAML.
        """
        import uuid
        from .actions import launch_machine
        
        workers_to_spawn = int(context.get("workers_to_spawn", 0))
        pool_id = context.get("pool_id", "default")
        worker_config_path = context.get("worker_config_path")
        
        if not worker_config_path and workers_to_spawn > 0:
            raise ValueError("worker_config_path required in context for spawn_workers")
        
        spawned_ids = []
        for i in range(workers_to_spawn):
            worker_id = f"worker-{uuid.uuid4().hex[:8]}"
            
            # Launch worker in subprocess
            launch_machine(
                machine_config=worker_config_path,
                input_data={
                    "pool_id": pool_id,
                    "worker_id": worker_id,
                },
            )
            
            spawned_ids.append(worker_id)
            logger.info(f"Spawned worker subprocess: {worker_id}")
        
        context["spawned_ids"] = spawned_ids
        context["spawned_count"] = len(spawned_ids)
        return context

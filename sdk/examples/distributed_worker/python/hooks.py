"""
Demo-specific hooks for the distributed worker example.

Extends the SDK's DistributedWorkerHooks with example-specific actions.
"""

import os
import asyncio
from typing import Dict, Any, Optional
from pathlib import Path

from flatmachines import (
    DistributedWorkerHooks,
    SQLiteRegistrationBackend,
    SQLiteWorkBackend,
)


# Default database path (relative to example directory)
DEFAULT_DB_PATH = str(Path(__file__).parent.parent / "data" / "worker.sqlite")


class DemoHooks(DistributedWorkerHooks):
    """
    Demo-specific hooks that extend the SDK base class.
    
    Only adds the demo-specific actions:
    - echo_delay: Simulated job processing with delay
    """
    
    def __init__(self, db_path: Optional[str] = None):
        db_path = db_path or os.environ.get("WORKER_DB_PATH", DEFAULT_DB_PATH)
        
        # Ensure data directory exists
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        
        # Initialize base class with backends
        super().__init__(
            registration=SQLiteRegistrationBackend(db_path=db_path),
            work=SQLiteWorkBackend(db_path=db_path),
        )
    
    async def on_action(self, action: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Route demo-specific actions, fallback to base class."""
        
        # Demo-specific actions
        if action == "echo_delay":
            return await self._echo_delay(context)
        
        # Delegate to base class for standard distributed worker actions
        return await super().on_action(action, context)
    
    # -------------------------------------------------------------------------
    # Demo-Specific Actions
    # -------------------------------------------------------------------------
    
    async def _echo_delay(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Simulate processing with a delay (for echo_processor)."""
        delay = context.get("delay_seconds", 1)
        
        # Actually wait
        await asyncio.sleep(delay)
        
        context["processed"] = True
        context["delay_applied"] = delay
        return context


# Backward compatibility alias
DistributedWorkerHooks = DemoHooks

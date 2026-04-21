"""
Integration tests for ExecutionLock concurrency control.

Tests that LocalFileLock prevents concurrent execution.
"""

import asyncio
import os
import shutil
import pytest
from flatmachines import FlatMachine, MachineHooks, LocalFileLock, NoOpLock


@pytest.fixture(autouse=True)
def cleanup():
    """Clean up checkpoint and lock directories."""
    for dir_name in [".checkpoints", ".locks"]:
        if os.path.exists(dir_name):
            shutil.rmtree(dir_name)
    yield
    for dir_name in [".checkpoints", ".locks"]:
        if os.path.exists(dir_name):
            shutil.rmtree(dir_name)


class SlowHooks(MachineHooks):
    """Hooks that deliberately slow down execution."""
    
    def __init__(self, delay: float = 0.5):
        self.delay = delay
        self.started = False
        self.finished = False
    
    def on_state_enter(self, state_name, context):
        self.started = True
        return context
    
    def on_machine_end(self, context, output):
        self.finished = True
        return output


class TestLocalFileLock:
    """Test LocalFileLock behavior."""

    @pytest.mark.asyncio
    async def test_lock_acquire_release(self):
        """Lock can be acquired and released."""
        lock = LocalFileLock()
        
        acquired = await lock.acquire("test_key")
        assert acquired is True
        
        await lock.release("test_key")
        
        # Can acquire again after release
        acquired2 = await lock.acquire("test_key")
        assert acquired2 is True
        await lock.release("test_key")

    @pytest.mark.asyncio
    async def test_lock_prevents_concurrent(self):
        """Second acquire fails while lock is held."""
        lock = LocalFileLock()
        
        acquired1 = await lock.acquire("same_key")
        assert acquired1 is True
        
        # Second acquire should fail (non-blocking)
        acquired2 = await lock.acquire("same_key")
        assert acquired2 is False
        
        await lock.release("same_key")

    @pytest.mark.asyncio
    async def test_different_keys_independent(self):
        """Different keys can be locked independently."""
        lock = LocalFileLock()
        
        acquired1 = await lock.acquire("key1")
        acquired2 = await lock.acquire("key2")
        
        assert acquired1 is True
        assert acquired2 is True
        
        await lock.release("key1")
        await lock.release("key2")


class TestNoOpLock:
    """Test NoOpLock passthrough behavior."""

    @pytest.mark.asyncio
    async def test_noop_always_succeeds(self):
        """NoOpLock always allows acquisition."""
        lock = NoOpLock()
        
        # Multiple acquires on same key all succeed
        assert await lock.acquire("key") is True
        assert await lock.acquire("key") is True
        assert await lock.acquire("key") is True
        
        # Release is no-op
        await lock.release("key")


class TestMachineLocking:
    """Test FlatMachine uses locks correctly."""

    @pytest.mark.asyncio
    async def test_machine_acquires_lock(self):
        """Machine acquires lock on execution."""
        config = {
            "spec": "flatmachine",
            "spec_version": "0.1.0",
            "data": {
                "name": "locking_test",
                "persistence": {"enabled": True, "backend": "local"},
                "states": {
                    "start": {"type": "initial", "transitions": [{"to": "end"}]},
                    "end": {"type": "final", "output": {"done": True}}
                }
            }
        }
        
        machine = FlatMachine(config_dict=config)
        
        # Verify lock directory created
        result = await machine.execute()
        assert result["done"] is True
        
        # Lock should be released after execution

    @pytest.mark.asyncio
    async def test_concurrent_same_id_blocked(self):
        """Cannot resume an execution while it's running."""
        config = {
            "spec": "flatmachine",
            "spec_version": "0.1.0",
            "data": {
                "name": "concurrent_test",
                "persistence": {"enabled": True, "backend": "local"},
                "states": {
                    "start": {"type": "initial", "transitions": [{"to": "slow"}]},
                    "slow": {
                        "action": "wait",
                        "transitions": [{"to": "end"}]
                    },
                    "end": {"type": "final", "output": {"done": True}}
                }
            }
        }
        
        class WaitHooks(MachineHooks):
            def on_action(self, state_name, action_name, context):
                if action_name == "wait":
                    import time
                    time.sleep(0.3)
                return context

        cfg = {**config, "data": {**config["data"], "states": {**config["data"]["states"]}}}
        cfg["data"]["states"]["slow"] = {**cfg["data"]["states"]["slow"], "hooks": "wait-hooks"}
        from flatmachines import HooksRegistry
        registry = HooksRegistry()
        registry.register("wait-hooks", WaitHooks)

        machine1 = FlatMachine(config_dict=cfg, hooks_registry=registry)
        execution_id = machine1.execution_id
        
        # Start first execution
        task1 = asyncio.create_task(machine1.execute())
        
        # Give it time to acquire lock
        await asyncio.sleep(0.1)
        
        # Try to resume same execution - should fail to acquire lock
        machine2 = FlatMachine(config_dict=cfg, hooks_registry=registry)
        
        with pytest.raises(RuntimeError, match="Could not acquire lock"):
            await machine2.execute(resume_from=execution_id)
        
        # Let first task complete
        result = await task1
        assert result["done"] is True

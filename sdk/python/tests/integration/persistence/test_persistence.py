"""
Integration tests for FlatMachine persistence features.

Tests checkpoint/resume functionality with simulated crashes.
"""

import asyncio
import os
import shutil
import pytest
from flatmachines import FlatMachine, MachineHooks


class CounterHooks(MachineHooks):
    """Test hooks that increment a counter and can simulate crashes."""
    
    def __init__(self, crash_at: int = None):
        self.crash_at = crash_at
        self.crashed = False
    
    def on_action(self, action_name, context):
        if action_name == "increment":
            context["count"] = context.get("count", 0) + 1
            
            # Simulate crash at specified count
            if self.crash_at and context["count"] == self.crash_at and not self.crashed:
                self.crashed = True
                raise RuntimeError(f"Simulated crash at count {self.crash_at}")
                
        return context


def get_counter_config():
    """Return a simple counter machine config."""
    return {
        "spec": "flatmachine",
        "spec_version": "0.1.0",
        "data": {
            "name": "counter",
            "context": {"count": 0},
            "persistence": {
                "enabled": True,
                "backend": "local"
            },
            "states": {
                "start": {
                    "type": "initial",
                    "transitions": [{"to": "count_up"}]
                },
                "count_up": {
                    "action": "increment",
                    "transitions": [
                        {"condition": "context.count >= 5", "to": "end"},
                        {"to": "count_up"}
                    ]
                },
                "end": {
                    "type": "final",
                    "output": {"final_count": "context.count"}
                }
            }
        }
    }


@pytest.fixture(autouse=True)
def cleanup():
    """Clean up checkpoint and lock directories before and after tests."""
    for dir_name in [".checkpoints", ".locks"]:
        if os.path.exists(dir_name):
            shutil.rmtree(dir_name)
    yield
    for dir_name in [".checkpoints", ".locks"]:
        if os.path.exists(dir_name):
            shutil.rmtree(dir_name)


class TestCheckpointResume:
    """Test checkpoint and resume functionality."""

    @pytest.mark.asyncio
    async def test_simple_execution_no_crash(self):
        """Machine runs to completion without crash."""
        config = get_counter_config()
        machine = FlatMachine(config_dict=config, hooks=CounterHooks())
        
        result = await machine.execute()
        
        assert result["final_count"] == 5

    @pytest.mark.asyncio
    async def test_crash_and_resume(self):
        """Machine crashes, then resumes from checkpoint."""
        config = get_counter_config()
        
        # Run 1: Crash at count 3
        machine1 = FlatMachine(config_dict=config, hooks=CounterHooks(crash_at=3))
        execution_id = machine1.execution_id
        
        with pytest.raises(RuntimeError, match="Simulated crash"):
            await machine1.execute()
        
        # Run 2: Resume (no crash configured)
        machine2 = FlatMachine(config_dict=config, hooks=CounterHooks())
        result = await machine2.execute(resume_from=execution_id)
        
        assert result["final_count"] == 5

    @pytest.mark.asyncio
    async def test_resume_already_completed(self):
        """Resuming an already completed execution returns cached result."""
        config = get_counter_config()
        
        # Run to completion
        machine1 = FlatMachine(config_dict=config, hooks=CounterHooks())
        execution_id = machine1.execution_id
        result1 = await machine1.execute()
        
        assert result1["final_count"] == 5
        
        # Resume completed execution
        machine2 = FlatMachine(config_dict=config, hooks=CounterHooks())
        result2 = await machine2.execute(resume_from=execution_id)
        
        # Should return same result without re-execution
        assert result2["final_count"] == 5


class TestMemoryBackend:
    """Test with in-memory persistence (ephemeral)."""

    @pytest.mark.asyncio
    async def test_memory_backend_no_persistence(self):
        """Memory backend doesn't persist across instances."""
        config = get_counter_config()
        config["data"]["persistence"]["backend"] = "memory"
        
        machine = FlatMachine(config_dict=config, hooks=CounterHooks())
        result = await machine.execute()
        
        assert result["final_count"] == 5


class TestCheckpointEvents:
    """Test checkpoint event configuration."""

    @pytest.mark.asyncio
    async def test_minimal_checkpoints(self):
        """Machine works with minimal checkpoint events configured."""
        config = get_counter_config()
        config["data"]["persistence"]["checkpoint_on"] = ["machine_start", "machine_end"]
        
        machine = FlatMachine(config_dict=config, hooks=CounterHooks())
        result = await machine.execute()
        
        assert result["final_count"] == 5

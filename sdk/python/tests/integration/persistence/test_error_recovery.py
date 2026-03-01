"""
Integration tests for error recovery with checkpoint/resume.

Tests on_error transitions combined with persistence.
"""

import asyncio
import os
import shutil
import pytest
from flatmachines import FlatMachine, MachineHooks


class ErrorRecoveryHooks(MachineHooks):
    """Hooks that can trigger errors and track recovery."""
    
    def __init__(self, fail_at_count: int = None, fail_once: bool = True):
        self.fail_at_count = fail_at_count
        self.fail_once = fail_once
        self.failed = False
        self.recovery_entered = False
        self.attempts = 0
    
    def on_action(self, action_name, context):
        if action_name == "increment":
            context["count"] = context.get("count", 0) + 1
            self.attempts += 1
            
            # Trigger failure at specific count
            if self.fail_at_count and context["count"] == self.fail_at_count:
                if not self.failed or not self.fail_once:
                    self.failed = True
                    raise ValueError(f"Deliberate failure at count {self.fail_at_count}")
        
        elif action_name == "recover":
            self.recovery_entered = True
            context["recovered"] = True
            
        return context


def get_error_recovery_config():
    """Machine config with on_error recovery path."""
    return {
        "spec": "flatmachine",
        "spec_version": "0.1.0",
        "data": {
            "name": "error_recovery",
            "context": {"count": 0},
            "persistence": {"enabled": True, "backend": "local"},
            "states": {
                "start": {
                    "type": "initial",
                    "transitions": [{"to": "count_up"}]
                },
                "count_up": {
                    "action": "increment",
                    "on_error": "recovery",  # Declarative error handling
                    "transitions": [
                        {"condition": "context.count >= 5", "to": "end"},
                        {"to": "count_up"}
                    ]
                },
                "recovery": {
                    "action": "recover",
                    "transitions": [{"to": "end"}]
                },
                "end": {
                    "type": "final",
                    "output": {
                        "final_count": "context.count",
                        "recovered": "{{ context.recovered | default(false) }}"
                    }
                }
            }
        }
    }


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


class TestDeclarativeErrorRecovery:
    """Test on_error declarative error handling."""

    @pytest.mark.asyncio
    async def test_on_error_transitions_to_recovery(self):
        """Error triggers transition to recovery state."""
        config = get_error_recovery_config()
        hooks = ErrorRecoveryHooks(fail_at_count=3)
        
        machine = FlatMachine(config_dict=config, hooks=hooks)
        result = await machine.execute()
        
        # Should have transitioned to recovery, then end
        assert hooks.recovery_entered is True
        assert result["recovered"] == "True"  # Jinja renders bool as string
        # Count should be 3 (where it failed)
        assert result["final_count"] == 3

    @pytest.mark.asyncio
    async def test_no_error_completes_normally(self):
        """Without errors, normal execution path."""
        config = get_error_recovery_config()
        hooks = ErrorRecoveryHooks()  # No failure configured
        
        machine = FlatMachine(config_dict=config, hooks=hooks)
        result = await machine.execute()
        
        assert hooks.recovery_entered is False
        assert result["final_count"] == 5
        assert result["recovered"] == "False"  # Jinja renders as string


class TestErrorWithResume:
    """Test error handling combined with checkpoint/resume."""

    @pytest.mark.asyncio
    async def test_crash_resume_continues(self):
        """Crash (no on_error), resume, complete normally."""
        
        # Config WITHOUT on_error - errors will crash
        config = {
            "spec": "flatmachine",
            "spec_version": "0.1.0",
            "data": {
                "name": "crash_test",
                "context": {"count": 0},
                "persistence": {"enabled": True, "backend": "local"},
                "states": {
                    "start": {"type": "initial", "transitions": [{"to": "count_up"}]},
                    "count_up": {
                        "action": "increment",
                        # NO on_error - will crash
                        "transitions": [
                            {"condition": "context.count >= 3", "to": "end"},
                            {"to": "count_up"}
                        ]
                    },
                    "end": {"type": "final", "output": {"final_count": "context.count"}}
                }
            }
        }
        
        class CrashOnceHooks(MachineHooks):
            def __init__(self, crash_at: int):
                self.crash_at = crash_at
                self.crashed = False
            
            def on_action(self, action_name, context):
                if action_name == "increment":
                    context["count"] = context.get("count", 0) + 1
                    if context["count"] == self.crash_at and not self.crashed:
                        self.crashed = True
                        raise RuntimeError("Crash!")
                return context
        
        # Run 1: Crash at count 1
        hooks1 = CrashOnceHooks(crash_at=1)
        machine1 = FlatMachine(config_dict=config, hooks=hooks1)
        execution_id = machine1.execution_id
        
        with pytest.raises(RuntimeError, match="Crash!"):
            await machine1.execute()
        
        # Run 2: Resume with hooks that don't crash
        hooks2 = CrashOnceHooks(crash_at=99)  # Won't crash
        machine2 = FlatMachine(config_dict=config, hooks=hooks2)
        result = await machine2.execute(resume_from=execution_id)
        
        # Should complete normally
        assert result["final_count"] == 3


class TestErrorContext:
    """Test error information in context."""

    @pytest.mark.asyncio
    async def test_last_error_in_context(self):
        """Error info available in context after failure."""
        
        class ErrorCheckHooks(MachineHooks):
            def __init__(self):
                self.error_context = None
            
            def on_action(self, action_name, context):
                if action_name == "fail":
                    raise TypeError("Custom error message")
                elif action_name == "check_error":
                    self.error_context = {
                        "last_error": context.get("last_error"),
                        "last_error_type": context.get("last_error_type")
                    }
                return context
        
        config = {
            "spec": "flatmachine",
            "spec_version": "0.1.0",
            "data": {
                "name": "error_context_test",
                "persistence": {"enabled": True, "backend": "memory"},
                "states": {
                    "start": {"type": "initial", "transitions": [{"to": "fail_state"}]},
                    "fail_state": {
                        "action": "fail",
                        "on_error": "check_state",
                        "transitions": [{"to": "end"}]
                    },
                    "check_state": {
                        "action": "check_error",
                        "transitions": [{"to": "end"}]
                    },
                    "end": {"type": "final", "output": {"done": True}}
                }
            }
        }
        
        hooks = ErrorCheckHooks()
        machine = FlatMachine(config_dict=config, hooks=hooks)
        result = await machine.execute()
        
        # Verify error info was captured
        assert hooks.error_context["last_error"] == "Custom error message"
        assert hooks.error_context["last_error_type"] == "TypeError"

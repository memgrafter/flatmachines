"""Unit tests for agent file ref resolution at machine load time.

Verifies that file-based agent refs (both string shorthand and typed
dict refs) are resolved into embedded config dicts, making the machine
config self-contained for checkpoint/resume.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict
from unittest.mock import AsyncMock, patch

import pytest

from flatmachines import FlatMachine
from flatmachines.agents import AgentRef, AgentAdapterContext, normalize_agent_ref


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _minimal_machine(agents: Dict[str, Any]) -> Dict[str, Any]:
    """Build a minimal valid machine config with the given agents dict."""
    return {
        "spec": "flatmachine",
        "spec_version": "0.8.0",
        "data": {
            "name": "test-ref-resolution",
            "agents": agents,
            "states": {
                "start": {
                    "type": "initial",
                    "agent": list(agents.keys())[0] if agents else "noop",
                    "input": {"task": "hello"},
                    "transitions": [{"to": "done"}],
                },
                "done": {"type": "final"},
            },
        },
    }


def _write_json(dir_path: str, filename: str, data: dict) -> str:
    """Write a JSON file and return its path."""
    path = os.path.join(dir_path, filename)
    with open(path, "w") as f:
        json.dump(data, f)
    return path


def _write_yaml(dir_path: str, filename: str, data: dict) -> str:
    """Write a YAML file and return its path."""
    import yaml

    path = os.path.join(dir_path, filename)
    with open(path, "w") as f:
        yaml.dump(data, f)
    return path


# ---------------------------------------------------------------------------
# Typed ref resolution (claude-code style)
# ---------------------------------------------------------------------------

class TestTypedRefResolution:
    """Test resolution of {type: ..., ref: ./file.json} agent refs."""

    def test_claude_code_json_ref_resolved(self, tmp_path):
        """claude-code ref pointing to a JSON file is resolved at load time."""
        claude_config = {
            "model": "sonnet",
            "effort": "high",
            "permission_mode": "bypassPermissions",
            "tools": ["Bash", "Read", "Write", "Edit"],
        }
        _write_json(str(tmp_path), "claude-coder.json", claude_config)

        machine_config = _minimal_machine({
            "coder": {
                "type": "claude-code",
                "ref": "./claude-coder.json",
            }
        })
        machine_path = _write_json(str(tmp_path), "machine.json", machine_config)

        m = FlatMachine(config_file=machine_path)

        # ref should be gone, config should contain file contents
        agent = m.agent_refs["coder"]
        assert "ref" not in agent
        assert agent["type"] == "claude-code"
        assert agent["config"]["model"] == "sonnet"
        assert agent["config"]["tools"] == ["Bash", "Read", "Write", "Edit"]
        assert agent["config"]["permission_mode"] == "bypassPermissions"

    def test_inline_config_overrides_file(self, tmp_path):
        """Inline config keys override file config keys."""
        file_config = {
            "model": "sonnet",
            "max_budget_usd": 1.0,
            "effort": "low",
        }
        _write_json(str(tmp_path), "base.json", file_config)

        machine_config = _minimal_machine({
            "coder": {
                "type": "claude-code",
                "ref": "./base.json",
                "config": {
                    "max_budget_usd": 5.0,  # override
                    "timeout": 300,  # new key
                },
            }
        })
        machine_path = _write_json(str(tmp_path), "machine.json", machine_config)

        m = FlatMachine(config_file=machine_path)

        agent = m.agent_refs["coder"]
        assert agent["config"]["model"] == "sonnet"  # from file
        assert agent["config"]["max_budget_usd"] == 5.0  # inline wins
        assert agent["config"]["effort"] == "low"  # from file
        assert agent["config"]["timeout"] == 300  # inline addition

    def test_multiple_agents_different_refs(self, tmp_path):
        """Multiple agents can each reference different config files."""
        _write_json(str(tmp_path), "planner.json", {
            "model": "opus",
            "tools": ["Read", "Grep", "Glob"],
        })
        _write_json(str(tmp_path), "implementer.json", {
            "model": "sonnet",
            "tools": ["Bash", "Read", "Write", "Edit"],
        })

        machine_config = _minimal_machine({
            "planner": {
                "type": "claude-code",
                "ref": "./planner.json",
            },
            "implementer": {
                "type": "claude-code",
                "ref": "./implementer.json",
            },
        })
        machine_path = _write_json(str(tmp_path), "machine.json", machine_config)

        m = FlatMachine(config_file=machine_path)

        assert m.agent_refs["planner"]["config"]["model"] == "opus"
        assert m.agent_refs["implementer"]["config"]["model"] == "sonnet"
        assert "ref" not in m.agent_refs["planner"]
        assert "ref" not in m.agent_refs["implementer"]

    def test_yaml_ref_resolved(self, tmp_path):
        """YAML config files are also resolved."""
        _write_yaml(str(tmp_path), "agent.yml", {
            "model": "opus",
            "effort": "max",
        })

        machine_config = _minimal_machine({
            "coder": {
                "type": "claude-code",
                "ref": "./agent.yml",
            }
        })
        machine_path = _write_json(str(tmp_path), "machine.json", machine_config)

        m = FlatMachine(config_file=machine_path)

        assert m.agent_refs["coder"]["config"]["model"] == "opus"
        assert "ref" not in m.agent_refs["coder"]

    def test_nonexistent_ref_left_alone(self, tmp_path):
        """If the ref file doesn't exist, the ref is left unresolved."""
        machine_config = _minimal_machine({
            "coder": {
                "type": "claude-code",
                "ref": "./does-not-exist.json",
            }
        })
        machine_path = _write_json(str(tmp_path), "machine.json", machine_config)

        m = FlatMachine(config_file=machine_path)

        # ref stays — adapter will handle or fail at runtime
        assert m.agent_refs["coder"]["ref"] == "./does-not-exist.json"


# ---------------------------------------------------------------------------
# String shorthand resolution (flatagent style)
# ---------------------------------------------------------------------------

class TestStringRefResolution:
    """Test resolution of string agent refs (flatagent shorthand)."""

    def test_flatagent_yaml_ref_resolved(self, tmp_path):
        """String ref to a flatagent YAML file is resolved at load time."""
        agent_config = {
            "spec": "flatagent",
            "spec_version": "2.3.0",
            "data": {
                "name": "extractor",
                "model": {"provider": "anthropic", "name": "claude-sonnet-4-20250514"},
                "system": "Extract data.",
                "user": "{{ input.text }}",
            },
        }
        _write_yaml(str(tmp_path), "extractor.yml", agent_config)

        machine_config = _minimal_machine({
            "extractor": "./extractor.yml",
        })
        machine_path = _write_json(str(tmp_path), "machine.json", machine_config)

        m = FlatMachine(config_file=machine_path)

        # String should be replaced by the loaded dict
        agent = m.agent_refs["extractor"]
        assert isinstance(agent, dict)
        assert agent["spec"] == "flatagent"
        assert agent["data"]["name"] == "extractor"

    def test_string_ref_nonexistent_left_alone(self, tmp_path):
        """Non-file string refs are left as-is."""
        machine_config = _minimal_machine({
            "agent": "not-a-file-path",
        })
        machine_path = _write_json(str(tmp_path), "machine.json", machine_config)

        m = FlatMachine(config_file=machine_path)

        assert m.agent_refs["agent"] == "not-a-file-path"


# ---------------------------------------------------------------------------
# Inline config (no ref) is untouched
# ---------------------------------------------------------------------------

class TestInlineConfig:
    """Inline agent configs without refs are not modified."""

    def test_inline_claude_code_untouched(self, tmp_path):
        machine_config = _minimal_machine({
            "coder": {
                "type": "claude-code",
                "config": {
                    "model": "sonnet",
                    "tools": ["Bash", "Read"],
                },
            }
        })
        machine_path = _write_json(str(tmp_path), "machine.json", machine_config)

        m = FlatMachine(config_file=machine_path)

        assert m.agent_refs["coder"]["config"]["model"] == "sonnet"
        assert "ref" not in m.agent_refs["coder"]

    def test_inline_flatagent_untouched(self, tmp_path):
        machine_config = _minimal_machine({
            "agent": {
                "spec": "flatagent",
                "spec_version": "2.3.0",
                "data": {
                    "model": {"provider": "openai", "name": "gpt-4"},
                    "system": "Hello.",
                    "user": "{{ input.q }}",
                },
            },
        })
        machine_path = _write_json(str(tmp_path), "machine.json", machine_config)

        m = FlatMachine(config_file=machine_path)

        agent = m.agent_refs["agent"]
        assert agent["spec"] == "flatagent"


# ---------------------------------------------------------------------------
# Checkpoint / _config_raw contains resolved refs
# ---------------------------------------------------------------------------

class TestConfigRawResolution:
    """Verify that _config_raw (used for checkpoints) contains resolved refs."""

    def test_config_raw_contains_resolved_config(self, tmp_path):
        """_config_raw should serialize the resolved config, not the original."""
        claude_config = {"model": "opus", "effort": "high"}
        _write_json(str(tmp_path), "claude.json", claude_config)

        machine_config = _minimal_machine({
            "coder": {
                "type": "claude-code",
                "ref": "./claude.json",
            }
        })
        machine_path = _write_json(str(tmp_path), "machine.json", machine_config)

        m = FlatMachine(config_file=machine_path)

        # _config_raw should contain resolved config
        assert m._config_raw is not None
        assert "ref" not in m._config_raw or "claude.json" not in m._config_raw
        # The model value from the file should be present
        assert "opus" in m._config_raw

    def test_config_raw_from_dict_also_resolved(self, tmp_path):
        """dict-based config also gets refs resolved in _config_raw."""
        claude_config = {"model": "sonnet", "tools": ["Bash"]}
        _write_json(str(tmp_path), "cc.json", claude_config)

        machine_config = _minimal_machine({
            "coder": {
                "type": "claude-code",
                "ref": os.path.join(str(tmp_path), "cc.json"),  # absolute path
            }
        })

        m = FlatMachine(config_dict=machine_config)

        assert m._config_raw is not None
        assert "sonnet" in m._config_raw


# ---------------------------------------------------------------------------
# Claude Code adapter fallback ref resolution
# ---------------------------------------------------------------------------

class TestClaudeCodeAdapterRefFallback:
    """Test that the adapter can resolve refs directly (without FlatMachine)."""

    def test_adapter_resolves_ref(self, tmp_path):
        from flatmachines.adapters.claude_code import ClaudeCodeAdapter

        claude_config = {"model": "opus", "effort": "max"}
        _write_json(str(tmp_path), "agent.json", claude_config)

        adapter = ClaudeCodeAdapter()
        agent_ref = AgentRef(
            type="claude-code",
            ref="./agent.json",
        )
        ctx = AgentAdapterContext(
            config_dir=str(tmp_path),
            settings={},
            machine_name="test",
        )

        executor = adapter.create_executor(
            agent_name="coder",
            agent_ref=agent_ref,
            context=ctx,
        )

        # Should have resolved the ref into config
        args = executor._build_args("hello", "s1", resume=False)
        assert "opus" in args

    def test_adapter_prefers_config_over_ref(self, tmp_path):
        """If config is already populated, ref is ignored."""
        from flatmachines.adapters.claude_code import ClaudeCodeAdapter

        _write_json(str(tmp_path), "agent.json", {"model": "opus"})

        adapter = ClaudeCodeAdapter()
        agent_ref = AgentRef(
            type="claude-code",
            ref="./agent.json",
            config={"model": "sonnet"},  # already resolved
        )
        ctx = AgentAdapterContext(
            config_dir=str(tmp_path),
            settings={},
            machine_name="test",
        )

        executor = adapter.create_executor(
            agent_name="coder",
            agent_ref=agent_ref,
            context=ctx,
        )

        args = executor._build_args("hello", "s1", resume=False)
        # config wins — should use sonnet, not opus
        idx = args.index("--model")
        assert args[idx + 1] == "sonnet"


# ---------------------------------------------------------------------------
# normalize_agent_ref still works after resolution
# ---------------------------------------------------------------------------

class TestNormalizeAfterResolution:
    """Verify normalize_agent_ref handles resolved refs correctly."""

    def test_resolved_typed_ref(self):
        """After resolution, typed ref has config but no ref."""
        raw = {"type": "claude-code", "config": {"model": "sonnet"}}
        ref = normalize_agent_ref(raw)
        assert ref.type == "claude-code"
        assert ref.config == {"model": "sonnet"}
        assert ref.ref is None

    def test_resolved_flatagent_inline(self):
        """After resolution, flatagent string becomes inline dict."""
        raw = {
            "spec": "flatagent",
            "spec_version": "2.3.0",
            "data": {
                "model": {"provider": "openai", "name": "gpt-4"},
                "system": "Hello.",
                "user": "{{ input.q }}",
            },
        }
        ref = normalize_agent_ref(raw)
        assert ref.type == "flatagent"
        assert ref.config == raw
        assert ref.ref is None

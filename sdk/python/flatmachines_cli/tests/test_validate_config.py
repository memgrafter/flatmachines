"""Tests for validate_self_improve_config() and profiles.yml."""

import os
import tempfile
from pathlib import Path

import pytest
import yaml

from flatmachines_cli.improve import validate_self_improve_config


CONFIG_DIR = Path(__file__).parent.parent / "config"


class TestValidateBuiltinConfig:
    """Test validation of the built-in self_improve.yml."""

    def test_builtin_config_is_valid(self):
        result = validate_self_improve_config()
        assert result["valid"], f"Errors: {result['errors']}"

    def test_builtin_config_info(self):
        result = validate_self_improve_config()
        info = result["info"]
        assert info["name"] == "self-improve"
        assert info["state_count"] >= 5
        assert info["agent_count"] >= 1

    def test_builtin_config_has_profiles(self):
        result = validate_self_improve_config()
        assert result["info"]["has_profiles"] is True

    def test_builtin_config_no_errors(self):
        result = validate_self_improve_config()
        assert len(result["errors"]) == 0

    def test_explicit_path_same_result(self):
        config_path = str(CONFIG_DIR / "self_improve.yml")
        r1 = validate_self_improve_config()
        r2 = validate_self_improve_config(config_path)
        assert r1["valid"] == r2["valid"]
        assert r1["errors"] == r2["errors"]


class TestValidateInvalidConfigs:
    """Test validation catches errors in bad configs."""

    def test_missing_file(self, tmp_path):
        result = validate_self_improve_config(str(tmp_path / "nonexistent.yml"))
        assert result["valid"] is False
        assert any("not found" in e for e in result["errors"])

    def test_invalid_yaml(self, tmp_path):
        bad = tmp_path / "bad.yml"
        bad.write_text(": : invalid yaml [[")
        result = validate_self_improve_config(str(bad))
        assert result["valid"] is False
        assert any("YAML" in e or "yaml" in e.lower() for e in result["errors"])

    def test_wrong_spec(self, tmp_path):
        config = tmp_path / "wrong.yml"
        config.write_text(yaml.dump({
            "spec": "flatagent",  # wrong!
            "data": {"states": {"start": {"type": "initial"}}}
        }))
        result = validate_self_improve_config(str(config))
        assert result["valid"] is False
        assert any("flatmachine" in e for e in result["errors"])

    def test_no_initial_state(self, tmp_path):
        config = tmp_path / "no_initial.yml"
        config.write_text(yaml.dump({
            "spec": "flatmachine",
            "data": {
                "states": {
                    "analyze": {},
                    "implement": {},
                    "evaluate": {},
                    "done": {"type": "final"},
                }
            }
        }))
        result = validate_self_improve_config(str(config))
        assert not result["valid"]
        assert any("initial" in e.lower() for e in result["errors"])

    def test_no_final_state(self, tmp_path):
        config = tmp_path / "no_final.yml"
        config.write_text(yaml.dump({
            "spec": "flatmachine",
            "data": {
                "states": {
                    "start": {"type": "initial"},
                    "analyze": {},
                    "implement": {},
                    "evaluate": {},
                }
            }
        }))
        result = validate_self_improve_config(str(config))
        assert not result["valid"]
        assert any("final" in e.lower() for e in result["errors"])

    def test_missing_required_states(self, tmp_path):
        config = tmp_path / "missing.yml"
        config.write_text(yaml.dump({
            "spec": "flatmachine",
            "data": {
                "states": {
                    "start": {"type": "initial"},
                    "done": {"type": "final"},
                }
            }
        }))
        result = validate_self_improve_config(str(config))
        assert not result["valid"]
        assert any("analyze" in e.lower() for e in result["errors"])
        assert any("implement" in e.lower() for e in result["errors"])
        assert any("evaluate" in e.lower() for e in result["errors"])

    def test_broken_transition(self, tmp_path):
        config = tmp_path / "broken_transition.yml"
        config.write_text(yaml.dump({
            "spec": "flatmachine",
            "data": {
                "states": {
                    "start": {"type": "initial", "transitions": [{"to": "nonexistent"}]},
                    "analyze": {},
                    "implement": {},
                    "evaluate": {},
                    "done": {"type": "final"},
                }
            }
        }))
        result = validate_self_improve_config(str(config))
        assert not result["valid"]
        assert any("nonexistent" in e for e in result["errors"])

    def test_undeclared_agent(self, tmp_path):
        config = tmp_path / "undeclared.yml"
        config.write_text(yaml.dump({
            "spec": "flatmachine",
            "data": {
                "agents": {},
                "states": {
                    "start": {"type": "initial"},
                    "analyze": {"agent": "missing_agent"},
                    "implement": {},
                    "evaluate": {},
                    "done": {"type": "final"},
                }
            }
        }))
        result = validate_self_improve_config(str(config))
        assert not result["valid"]
        assert any("undeclared" in e.lower() for e in result["errors"])

    def test_missing_agent_file(self, tmp_path):
        config = tmp_path / "missing_agent.yml"
        config.write_text(yaml.dump({
            "spec": "flatmachine",
            "data": {
                "agents": {"coder": "./agents/nonexistent.yml"},
                "states": {
                    "start": {"type": "initial"},
                    "analyze": {},
                    "implement": {},
                    "evaluate": {},
                    "done": {"type": "final"},
                }
            }
        }))
        result = validate_self_improve_config(str(config))
        assert not result["valid"]
        assert any("not found" in e for e in result["errors"])


class TestValidateWarnings:
    """Test that warnings are generated for non-critical issues."""

    def test_no_profiles_warning(self, tmp_path):
        # Create a valid config without profiles.yml nearby
        config = tmp_path / "config.yml"
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        (agents_dir / "a.yml").write_text(yaml.dump({
            "spec": "flatagent",
            "data": {"name": "a", "model": "default", "system": "test", "tools": []}
        }))
        config.write_text(yaml.dump({
            "spec": "flatmachine",
            "data": {
                "agents": {"a": "./agents/a.yml"},
                "states": {
                    "start": {"type": "initial"},
                    "analyze": {"agent": "a"},
                    "implement": {},
                    "evaluate": {},
                    "done": {"type": "final"},
                }
            }
        }))
        result = validate_self_improve_config(str(config))
        assert any("profiles" in w.lower() for w in result["warnings"])


class TestProfilesConfig:
    """Test the profiles.yml config file."""

    def test_profiles_exists(self):
        profiles_path = CONFIG_DIR / "profiles.yml"
        assert profiles_path.exists()

    def test_profiles_valid_yaml(self):
        profiles_path = CONFIG_DIR / "profiles.yml"
        with open(profiles_path) as f:
            config = yaml.safe_load(f)
        assert config["spec"] == "flatprofiles"

    def test_profiles_has_default(self):
        profiles_path = CONFIG_DIR / "profiles.yml"
        with open(profiles_path) as f:
            config = yaml.safe_load(f)
        profiles = config["data"]["model_profiles"]
        assert "default" in profiles
        # Default profile should have provider and name
        default = profiles["default"]
        assert "provider" in default
        assert "name" in default

    def test_profiles_has_at_least_one(self):
        """At least one profile configured."""
        profiles_path = CONFIG_DIR / "profiles.yml"
        with open(profiles_path) as f:
            config = yaml.safe_load(f)
        profiles = config["data"]["model_profiles"]
        assert len(profiles) >= 1, f"No profiles configured"

    def test_profiles_default_setting(self):
        profiles_path = CONFIG_DIR / "profiles.yml"
        with open(profiles_path) as f:
            config = yaml.safe_load(f)
        assert config["data"].get("default") == "default"


class TestStressPersistence:
    """Stress-test experiment persistence with many entries."""

    def test_100_entries_roundtrip(self, tmp_path):
        from flatmachines_cli.experiment import ExperimentTracker, ExperimentResult

        log_path = str(tmp_path / "log.jsonl")
        t = ExperimentTracker(
            name="stress-test",
            metric_name="score",
            direction="higher",
            log_path=log_path,
        )
        t.init()

        r = ExperimentResult(
            command="bench", exit_code=0, stdout="", stderr="",
            duration_s=0.1, success=True,
        )
        for i in range(100):
            status = "keep" if i % 3 == 0 else "discard"
            t.log(result=r, status=status, primary_metric=float(i),
                  description=f"run {i}", tags=[f"batch-{i // 10}"])

        assert len(t.history) == 100

        # Reload from file
        t2 = ExperimentTracker.from_file(log_path)
        assert len(t2.history) == 100
        assert t2.history[0].description == "run 0"
        assert t2.history[99].description == "run 99"
        assert t2.history[99].experiment_id == 100

        # Best metric should be 99 (last kept is 99)
        kept = [e for e in t2.history if e.status == "keep"]
        assert len(kept) == 34  # every 3rd: 0,3,6,...,99

    def test_persistence_file_size_reasonable(self, tmp_path):
        """100 entries should be < 100KB."""
        from flatmachines_cli.experiment import ExperimentTracker, ExperimentResult

        log_path = tmp_path / "log.jsonl"
        t = ExperimentTracker(log_path=str(log_path))
        t.init()

        r = ExperimentResult(
            command="bench", exit_code=0, stdout="", stderr="",
            duration_s=0.1, success=True,
        )
        for i in range(100):
            t.log(result=r, status="keep", primary_metric=float(i))

        size_kb = log_path.stat().st_size / 1024
        assert size_kb < 100, f"Log file too large: {size_kb:.1f}KB"

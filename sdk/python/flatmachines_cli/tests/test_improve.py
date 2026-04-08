"""Tests for the self-improvement orchestration module."""

import json
import os
import tempfile
from pathlib import Path

import pytest

from flatmachines_cli.improve import SelfImprover, SelfImproveHooks
from flatmachines_cli.experiment import ExperimentResult, ExperimentTracker


class TestSelfImprover:
    def test_basic_creation(self, tmp_path):
        improver = SelfImprover(
            target_dir=str(tmp_path),
            benchmark_command="echo 'METRIC score=42'",
            metric_name="score",
            direction="higher",
            log_path=str(tmp_path / "log.jsonl"),
        )
        assert improver.target_dir == str(tmp_path)
        assert improver.benchmark_command == "echo 'METRIC score=42'"

    def test_tracker_property(self, tmp_path):
        improver = SelfImprover(
            target_dir=str(tmp_path),
            benchmark_command="echo test",
            log_path=str(tmp_path / "log.jsonl"),
        )
        assert isinstance(improver.tracker, ExperimentTracker)

    def test_run_benchmark(self, tmp_path):
        improver = SelfImprover(
            target_dir=str(tmp_path),
            benchmark_command="echo 'METRIC score=42'",
            log_path=str(tmp_path / "log.jsonl"),
            working_dir=str(tmp_path),
        )
        result = improver.run_benchmark()
        assert result.success is True
        assert result.metrics.get("score") == 42.0

    def test_run_tests_no_command(self, tmp_path):
        improver = SelfImprover(
            target_dir=str(tmp_path),
            benchmark_command="echo test",
            test_command="",
            log_path=str(tmp_path / "log.jsonl"),
        )
        result = improver.run_tests()
        assert result.success is True

    def test_run_tests_with_command(self, tmp_path):
        improver = SelfImprover(
            target_dir=str(tmp_path),
            benchmark_command="echo test",
            test_command="echo 'tests passed'",
            log_path=str(tmp_path / "log.jsonl"),
            working_dir=str(tmp_path),
        )
        result = improver.run_tests()
        assert result.success is True

    def test_evaluate_first_result(self, tmp_path):
        improver = SelfImprover(
            target_dir=str(tmp_path),
            benchmark_command="echo test",
            metric_name="score",
            direction="higher",
            log_path=str(tmp_path / "log.jsonl"),
        )
        result = ExperimentResult(
            command="test", exit_code=0, stdout="", stderr="",
            duration_s=1.0, metrics={"score": 42.0}, success=True,
        )
        evaluation = improver.evaluate(result)
        assert evaluation["improved"] is True  # First result always improved
        assert evaluation["metric_value"] == 42.0
        assert evaluation["metric_name"] == "score"

    def test_evaluate_improvement(self, tmp_path):
        improver = SelfImprover(
            target_dir=str(tmp_path),
            benchmark_command="echo test",
            metric_name="score",
            direction="higher",
            log_path=str(tmp_path / "log.jsonl"),
        )
        # Log initial result
        r1 = ExperimentResult(
            command="test", exit_code=0, stdout="", stderr="",
            duration_s=1.0, metrics={"score": 10.0}, success=True,
        )
        improver.log_improvement(r1, "keep", "baseline")

        # Evaluate better result
        r2 = ExperimentResult(
            command="test", exit_code=0, stdout="", stderr="",
            duration_s=1.0, metrics={"score": 20.0}, success=True,
        )
        evaluation = improver.evaluate(r2)
        assert evaluation["improved"] is True
        assert evaluation["delta"] == 10.0

    def test_evaluate_regression(self, tmp_path):
        improver = SelfImprover(
            target_dir=str(tmp_path),
            benchmark_command="echo test",
            metric_name="score",
            direction="higher",
            log_path=str(tmp_path / "log.jsonl"),
        )
        r1 = ExperimentResult(
            command="test", exit_code=0, stdout="", stderr="",
            duration_s=1.0, metrics={"score": 20.0}, success=True,
        )
        improver.log_improvement(r1, "keep", "baseline")

        r2 = ExperimentResult(
            command="test", exit_code=0, stdout="", stderr="",
            duration_s=1.0, metrics={"score": 10.0}, success=True,
        )
        evaluation = improver.evaluate(r2)
        assert evaluation["improved"] is False

    def test_log_improvement(self, tmp_path):
        improver = SelfImprover(
            target_dir=str(tmp_path),
            benchmark_command="echo test",
            log_path=str(tmp_path / "log.jsonl"),
        )
        result = ExperimentResult(
            command="test", exit_code=0, stdout="", stderr="",
            duration_s=1.0, metrics={"score": 42.0}, success=True,
        )
        improver.log_improvement(result, "keep", "test improvement")
        assert len(improver.tracker.history) == 1

    def test_summary(self, tmp_path):
        improver = SelfImprover(
            target_dir=str(tmp_path),
            benchmark_command="echo test",
            metric_name="score",
            log_path=str(tmp_path / "log.jsonl"),
        )
        summary = improver.summary()
        assert "name" in summary
        assert "metric_name" in summary
        assert summary["total_experiments"] == 0


class TestSelfImproveHooks:
    def _make_improver(self, tmp_path, benchmark="echo 'METRIC score=42'"):
        return SelfImprover(
            target_dir=str(tmp_path),
            benchmark_command=benchmark,
            metric_name="score",
            direction="higher",
            log_path=str(tmp_path / "log.jsonl"),
            working_dir=str(tmp_path),
        )

    def test_evaluate_action(self, tmp_path):
        improver = self._make_improver(tmp_path)
        hooks = SelfImproveHooks(improver)

        context = {
            "iteration": 0,
            "consecutive_failures": 0,
            "best_score": None,
        }
        result = hooks.on_action("evaluate_improvement", context)
        assert result["current_score"] == 42.0
        assert result["last_status"] == "improved"
        assert result["iteration"] == 1

    def test_evaluate_crash(self, tmp_path):
        improver = self._make_improver(tmp_path, benchmark="exit 1")
        hooks = SelfImproveHooks(improver)

        context = {
            "iteration": 0,
            "consecutive_failures": 0,
        }
        result = hooks.on_action("evaluate_improvement", context)
        assert result["last_status"] == "crash"
        assert result["consecutive_failures"] == 1

    def test_archive_action(self, tmp_path):
        improver = self._make_improver(tmp_path)
        hooks = SelfImproveHooks(improver)

        # First evaluate to set _last_result
        context = {"iteration": 0, "consecutive_failures": 0, "best_score": None, "improvement_history": []}
        hooks.on_action("evaluate_improvement", context)

        # Then archive
        context["last_status"] = "improved"
        context["last_hypothesis"] = "test change"
        result = hooks.on_action("archive_result", context)
        assert len(result["improvement_history"]) == 1
        assert result["improvement_history"][0]["status"] == "keep"

    def test_revert_action(self, tmp_path):
        improver = self._make_improver(tmp_path)
        hooks = SelfImproveHooks(improver)

        # First evaluate
        context = {"iteration": 0, "consecutive_failures": 0, "best_score": None, "improvement_history": []}
        hooks.on_action("evaluate_improvement", context)

        # Then revert
        context["last_hypothesis"] = "failed idea"
        result = hooks.on_action("revert_changes", context)
        assert len(result["improvement_history"]) == 1
        assert result["improvement_history"][0]["status"] == "discard"

    def test_unknown_action_passthrough(self, tmp_path):
        improver = self._make_improver(tmp_path)
        hooks = SelfImproveHooks(improver)
        context = {"test": "value"}
        result = hooks.on_action("unknown_action", context)
        assert result == context

    def test_evaluate_sets_best_score(self, tmp_path):
        improver = self._make_improver(tmp_path)
        hooks = SelfImproveHooks(improver)

        context = {
            "iteration": 0,
            "consecutive_failures": 0,
            "best_score": None,
        }
        result = hooks.on_action("evaluate_improvement", context)
        assert result["best_score"] == 42.0

    def test_consecutive_failures_increment(self, tmp_path):
        improver = self._make_improver(tmp_path, benchmark="exit 1")
        hooks = SelfImproveHooks(improver)

        context = {"iteration": 0, "consecutive_failures": 0}
        result = hooks.on_action("evaluate_improvement", context)
        assert result["consecutive_failures"] == 1

        result = hooks.on_action("evaluate_improvement", result)
        assert result["consecutive_failures"] == 2


class TestSelfImproveConfig:
    """Test the self_improve.yml machine config is valid."""

    def test_config_exists(self):
        config_dir = Path(__file__).parent.parent / "config"
        config_path = config_dir / "self_improve.yml"
        assert config_path.exists(), f"Config not found at {config_path}"

    def test_config_is_valid_yaml(self):
        import yaml
        config_dir = Path(__file__).parent.parent / "config"
        config_path = config_dir / "self_improve.yml"
        with open(config_path) as f:
            config = yaml.safe_load(f)
        assert config["spec"] == "flatmachine"
        assert "data" in config
        assert "states" in config["data"]

    def test_config_has_required_states(self):
        import yaml
        config_dir = Path(__file__).parent.parent / "config"
        config_path = config_dir / "self_improve.yml"
        with open(config_path) as f:
            config = yaml.safe_load(f)
        states = set(config["data"]["states"].keys())
        # Must have agent state (unified "improve" or split "analyze"+"implement")
        # No evaluate state needed — agent owns the full experiment lifecycle
        has_unified = any("improv" in s for s in states)
        has_split = any("analy" in s for s in states) and any("implement" in s for s in states)
        assert has_unified or has_split, f"No agent state in {states}"

    def test_config_has_loop(self):
        import yaml
        config_dir = Path(__file__).parent.parent / "config"
        config_path = config_dir / "self_improve.yml"
        with open(config_path) as f:
            config = yaml.safe_load(f)
        # Should have max_steps (indicating iteration support)
        assert config["data"].get("max_steps"), "No max_steps in config"

    def test_config_has_initial_and_final(self):
        import yaml
        config_dir = Path(__file__).parent.parent / "config"
        config_path = config_dir / "self_improve.yml"
        with open(config_path) as f:
            config = yaml.safe_load(f)
        states = config["data"]["states"]
        has_initial = any(s.get("type") == "initial" for s in states.values())
        has_final = any(s.get("type") == "final" for s in states.values())
        assert has_initial, "No initial state"
        assert has_final, "No final state"

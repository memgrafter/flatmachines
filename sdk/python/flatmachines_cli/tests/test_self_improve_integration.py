"""
Integration tests for the self-improvement system.

Tests the full pipeline: experiment tracking + improve orchestration +
machine config + agent configs, all working together.
"""

import json
import os
import tempfile
from pathlib import Path

import pytest
import yaml

from flatmachines_cli.experiment import (
    ExperimentTracker,
    ExperimentResult,
    ExperimentEntry,
    parse_metrics,
)
from flatmachines_cli.improve import SelfImprover, SelfImproveHooks


# --- Config paths ---

CONFIG_DIR = Path(__file__).parent.parent / "config"
SELF_IMPROVE_CONFIG = CONFIG_DIR / "self_improve.yml"
ANALYZER_CONFIG = CONFIG_DIR / "agents" / "analyzer.yml"
IMPLEMENTER_CONFIG = CONFIG_DIR / "agents" / "implementer.yml"


class TestConfigsExist:
    """Verify all required config files are present and valid."""

    def test_self_improve_config_exists(self):
        assert SELF_IMPROVE_CONFIG.exists(), f"Missing: {SELF_IMPROVE_CONFIG}"

    def test_analyzer_agent_exists(self):
        assert ANALYZER_CONFIG.exists(), f"Missing: {ANALYZER_CONFIG}"

    def test_implementer_agent_exists(self):
        assert IMPLEMENTER_CONFIG.exists(), f"Missing: {IMPLEMENTER_CONFIG}"

    def test_self_improve_config_valid(self):
        with open(SELF_IMPROVE_CONFIG) as f:
            config = yaml.safe_load(f)
        assert config["spec"] == "flatmachine"
        assert "states" in config["data"]
        assert "agents" in config["data"]

    def test_analyzer_config_valid(self):
        with open(ANALYZER_CONFIG) as f:
            config = yaml.safe_load(f)
        assert config["spec"] == "flatagent"
        assert config["data"]["name"]
        assert config["data"]["system"]
        assert config["data"]["tools"]

    def test_implementer_config_valid(self):
        with open(IMPLEMENTER_CONFIG) as f:
            config = yaml.safe_load(f)
        assert config["spec"] == "flatagent"
        assert config["data"]["name"]
        assert config["data"]["tools"]
        # Implementer must have all 4 tools
        tool_names = {
            t["function"]["name"] for t in config["data"]["tools"]
        }
        assert tool_names >= {"read", "bash", "write", "edit"}

    def test_agent_refs_in_machine_resolve(self):
        """Agent references in self_improve.yml should point to existing files."""
        with open(SELF_IMPROVE_CONFIG) as f:
            config = yaml.safe_load(f)
        agents = config["data"]["agents"]
        for name, ref in agents.items():
            if isinstance(ref, str):
                # Resolve relative to config dir
                agent_path = CONFIG_DIR / ref
                assert agent_path.exists(), (
                    f"Agent '{name}' references '{ref}' but "
                    f"{agent_path} doesn't exist"
                )


class TestAgentAdapterCompatibility:
    """Verify agent configs work with any adapter (profile-based model)."""

    def test_agents_use_profile_model(self):
        """All agents should use profile-based model (e.g., 'default')
        rather than hardcoded provider/name, enabling adapter swapping."""
        for config_path in [ANALYZER_CONFIG, IMPLEMENTER_CONFIG]:
            with open(config_path) as f:
                config = yaml.safe_load(f)
            model = config["data"]["model"]
            # Should be a profile name (string) not a hardcoded dict
            assert isinstance(model, str), (
                f"{config_path.name}: model should be a profile string "
                f"(e.g., 'default'), got {type(model).__name__}: {model}"
            )

    def test_analyzer_has_read_and_bash(self):
        """Analyzer needs read + bash for analysis."""
        with open(ANALYZER_CONFIG) as f:
            config = yaml.safe_load(f)
        tool_names = {t["function"]["name"] for t in config["data"]["tools"]}
        assert "read" in tool_names, "Analyzer needs read tool"
        assert "bash" in tool_names, "Analyzer needs bash tool"

    def test_implementer_has_all_coding_tools(self):
        """Implementer needs all coding tools."""
        with open(IMPLEMENTER_CONFIG) as f:
            config = yaml.safe_load(f)
        tool_names = {t["function"]["name"] for t in config["data"]["tools"]}
        required = {"read", "bash", "write", "edit"}
        missing = required - tool_names
        assert not missing, f"Implementer missing tools: {missing}"


class TestSelfImproveLoopIntegration:
    """Test the full improvement loop logic (without LLM calls)."""

    def test_full_improve_cycle(self, tmp_path):
        """Run analyze → evaluate → archive cycle programmatically."""
        # Set up a benchmark that outputs metrics
        benchmark = tmp_path / "bench.sh"
        benchmark.write_text("#!/bin/bash\necho 'METRIC score=42'\n")
        benchmark.chmod(0o755)

        improver = SelfImprover(
            target_dir=str(tmp_path),
            benchmark_command=f"bash {benchmark}",
            metric_name="score",
            direction="higher",
            log_path=str(tmp_path / "log.jsonl"),
            working_dir=str(tmp_path),
        )

        # Step 1: Run benchmark (analysis phase)
        result = improver.run_benchmark()
        assert result.success
        assert result.metrics["score"] == 42.0

        # Step 2: Evaluate
        evaluation = improver.evaluate(result)
        assert evaluation["improved"] is True
        assert evaluation["metric_value"] == 42.0

        # Step 3: Archive as baseline
        improver.log_improvement(result, "keep", "Baseline")
        assert improver.tracker.best_metric() == 42.0

        # Step 4: Simulate improvement (change benchmark output)
        benchmark.write_text("#!/bin/bash\necho 'METRIC score=55'\n")

        # Step 5: Re-benchmark
        result2 = improver.run_benchmark()
        assert result2.metrics["score"] == 55.0

        # Step 6: Evaluate improvement
        eval2 = improver.evaluate(result2)
        assert eval2["improved"] is True
        assert eval2["delta"] == 13.0

        # Step 7: Archive improvement
        improver.log_improvement(result2, "keep", "Improved score")
        assert improver.tracker.best_metric() == 55.0
        assert len(improver.tracker.history) == 2

        # Step 8: Simulate regression
        benchmark.write_text("#!/bin/bash\necho 'METRIC score=30'\n")
        result3 = improver.run_benchmark()
        eval3 = improver.evaluate(result3)
        assert eval3["improved"] is False
        improver.log_improvement(result3, "discard", "Regression")

        # Best should still be 55
        assert improver.tracker.best_metric() == 55.0

        # Summary should show 3 experiments
        summary = improver.summary()
        assert summary["total_experiments"] == 3
        assert summary["kept"] == 2
        assert summary["discarded"] == 1

    def test_hooks_drive_full_cycle(self, tmp_path):
        """Test SelfImproveHooks driving the full analyze→evaluate→archive cycle."""
        benchmark = tmp_path / "bench.sh"
        benchmark.write_text("#!/bin/bash\necho 'METRIC score=42'\n")
        benchmark.chmod(0o755)

        improver = SelfImprover(
            target_dir=str(tmp_path),
            benchmark_command=f"bash {benchmark}",
            metric_name="score",
            direction="higher",
            log_path=str(tmp_path / "log.jsonl"),
            working_dir=str(tmp_path),
        )
        hooks = SelfImproveHooks(improver)

        # Simulate machine context
        context = {
            "iteration": 0,
            "consecutive_failures": 0,
            "best_score": None,
            "improvement_history": [],
            "last_hypothesis": "Initial benchmark",
        }

        # evaluate_improvement action
        context = hooks.on_action("evaluate_improvement", context)
        assert context["last_status"] == "improved"
        assert context["best_score"] == 42.0
        assert context["iteration"] == 1

        # archive_result action (keep)
        context = hooks.on_action("archive_result", context)
        assert len(context["improvement_history"]) == 1
        assert context["improvement_history"][0]["status"] == "keep"

        # Simulate worse result
        benchmark.write_text("#!/bin/bash\necho 'METRIC score=30'\n")
        context["last_hypothesis"] = "Bad change"
        context = hooks.on_action("evaluate_improvement", context)
        assert context["last_status"] == "no_improvement"
        assert context["consecutive_failures"] == 1

        # revert_changes action (discard)
        context = hooks.on_action("revert_changes", context)
        assert len(context["improvement_history"]) == 2
        assert context["improvement_history"][1]["status"] == "discard"

    def test_persistence_survives_restart(self, tmp_path):
        """Test that experiment history persists across SelfImprover instances."""
        log_path = str(tmp_path / "log.jsonl")

        # First session
        imp1 = SelfImprover(
            target_dir=str(tmp_path),
            benchmark_command="echo 'METRIC score=42'",
            metric_name="score",
            direction="higher",
            log_path=log_path,
            working_dir=str(tmp_path),
        )
        result = imp1.run_benchmark()
        imp1.log_improvement(result, "keep", "Run 1")

        # Second session (new instance, same log file)
        tracker = ExperimentTracker.from_file(log_path)
        assert len(tracker.history) == 1
        assert tracker.best_metric() == 42.0

        # Continue from where we left off
        entry = tracker.log(
            result=ExperimentResult(
                command="test", exit_code=0, stdout="", stderr="",
                duration_s=1.0, metrics={"score": 55.0}, success=True,
            ),
            status="keep",
            description="Run 2",
        )
        assert entry.experiment_id == 2
        assert tracker.best_metric() == 55.0

    def test_lower_is_better_direction(self, tmp_path):
        """Test improvement loop with 'lower is better' metric (e.g., latency)."""
        improver = SelfImprover(
            target_dir=str(tmp_path),
            benchmark_command="echo 'METRIC latency_ms=100'",
            metric_name="latency_ms",
            direction="lower",
            log_path=str(tmp_path / "log.jsonl"),
            working_dir=str(tmp_path),
        )

        r1 = improver.run_benchmark()
        ev1 = improver.evaluate(r1)
        assert ev1["improved"] is True  # First result
        improver.log_improvement(r1, "keep", "Baseline 100ms")

        # Better (lower) latency
        r2 = ExperimentResult(
            command="test", exit_code=0, stdout="", stderr="",
            duration_s=1.0, metrics={"latency_ms": 50.0}, success=True,
        )
        ev2 = improver.evaluate(r2)
        assert ev2["improved"] is True
        assert ev2["delta"] == 50.0  # Positive = improvement

        # Worse (higher) latency
        r3 = ExperimentResult(
            command="test", exit_code=0, stdout="", stderr="",
            duration_s=1.0, metrics={"latency_ms": 200.0}, success=True,
        )
        ev3 = improver.evaluate(r3)
        assert ev3["improved"] is False

    def test_crash_recovery(self, tmp_path):
        """Test that crashed benchmarks are handled gracefully."""
        improver = SelfImprover(
            target_dir=str(tmp_path),
            benchmark_command="exit 1",
            metric_name="score",
            direction="higher",
            log_path=str(tmp_path / "log.jsonl"),
            working_dir=str(tmp_path),
        )
        hooks = SelfImproveHooks(improver)

        context = {
            "iteration": 0,
            "consecutive_failures": 0,
        }
        context = hooks.on_action("evaluate_improvement", context)
        assert context["last_status"] == "crash"
        assert context["consecutive_failures"] == 1

    def test_multiple_metrics_parsed(self, tmp_path):
        """Test parsing multiple METRIC lines from benchmark output."""
        benchmark = tmp_path / "bench.sh"
        benchmark.write_text(
            "#!/bin/bash\n"
            "echo 'Running...'\n"
            "echo 'METRIC score=85'\n"
            "echo 'METRIC test_count=120'\n"
            "echo 'METRIC coverage=92.5'\n"
            "echo 'METRIC build_time=3.2'\n"
        )
        benchmark.chmod(0o755)

        improver = SelfImprover(
            target_dir=str(tmp_path),
            benchmark_command=f"bash {benchmark}",
            metric_name="score",
            log_path=str(tmp_path / "log.jsonl"),
            working_dir=str(tmp_path),
        )
        result = improver.run_benchmark()
        assert result.metrics == {
            "score": 85.0,
            "test_count": 120.0,
            "coverage": 92.5,
            "build_time": 3.2,
        }


class TestMachineConfigStructure:
    """Deep validation of self_improve.yml structure."""

    @pytest.fixture
    def config(self):
        with open(SELF_IMPROVE_CONFIG) as f:
            return yaml.safe_load(f)

    def test_has_initial_state(self, config):
        states = config["data"]["states"]
        initial = [s for s, d in states.items() if d.get("type") == "initial"]
        assert len(initial) == 1, f"Expected 1 initial state, got {len(initial)}"

    def test_has_final_state(self, config):
        states = config["data"]["states"]
        final = [s for s, d in states.items() if d.get("type") == "final"]
        assert len(final) == 1, f"Expected 1 final state, got {len(final)}"

    def test_all_transitions_target_existing_states(self, config):
        states = config["data"]["states"]
        state_names = set(states.keys())
        for sname, sdata in states.items():
            for t in sdata.get("transitions", []):
                target = t.get("to")
                assert target in state_names, (
                    f"State '{sname}' transitions to '{target}' "
                    f"which doesn't exist. States: {state_names}"
                )

    def test_has_tool_loop_states(self, config):
        """At least one state should use tool_loop for agent interaction."""
        states = config["data"]["states"]
        tool_loop_states = [
            s for s, d in states.items()
            if d.get("tool_loop")
        ]
        assert len(tool_loop_states) >= 1, "No tool_loop states found"

    def test_context_has_required_fields(self, config):
        context = config["data"]["context"]
        # Must have working_dir — agent discovers everything else
        assert "working_dir" in context, "Missing context field: working_dir"

    def test_loop_has_budget_control(self, config):
        """Loop should have max_steps or max_iterations to prevent runaway."""
        has_max_steps = config["data"].get("max_steps") is not None
        context = config["data"].get("context", {})
        has_max_iter = "max_iterations" in context
        states = config["data"]["states"]
        has_budget_check = any(
            "budget" in s.lower() or "check" in s.lower()
            for s in states.keys()
        )
        assert has_max_steps or has_max_iter or has_budget_check, (
            "No budget control found (max_steps, max_iterations, or check_budget state)"
        )

    def test_agent_owns_lifecycle(self, config):
        """Agent state should own the full experiment lifecycle (no separate evaluate state)."""
        states = config["data"]["states"]
        # improve state exists and uses an agent
        assert "improve" in states, "No improve state found"
        assert states["improve"].get("agent"), "improve state should use an agent"
        # No evaluate state — agent owns evaluation
        eval_states = [s for s in states if "eval" in s.lower()]
        assert not eval_states, (
            f"Found evaluate state(s) {eval_states} — agent should own the lifecycle"
            )

    def test_final_state_has_output(self, config):
        states = config["data"]["states"]
        for sname, sdata in states.items():
            if sdata.get("type") == "final":
                assert sdata.get("output"), (
                    f"Final state '{sname}' must have output"
                )

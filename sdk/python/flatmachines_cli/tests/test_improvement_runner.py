"""Tests for ImprovementRunner — programmatic evaluate→archive loop."""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from flatmachines_cli.improve import SelfImprover, SelfImproveHooks, ImprovementRunner
from flatmachines_cli.experiment import ExperimentTracker, ExperimentResult


def _make_improver(tmp_path, benchmark_cmd="echo 'METRIC score=100'", **kwargs):
    """Create a SelfImprover for testing."""
    return SelfImprover(
        target_dir=str(tmp_path),
        benchmark_command=benchmark_cmd,
        metric_name="score",
        direction="higher",
        log_path=str(tmp_path / "log.jsonl"),
        working_dir=str(tmp_path),
        **kwargs,
    )


class TestImprovementRunnerInit:
    """Test ImprovementRunner construction."""

    def test_create_runner(self, tmp_path):
        imp = _make_improver(tmp_path)
        runner = ImprovementRunner(imp, max_iterations=5)
        assert runner.improver is imp
        assert runner.hooks is not None

    def test_hooks_type(self, tmp_path):
        imp = _make_improver(tmp_path)
        runner = ImprovementRunner(imp)
        assert isinstance(runner.hooks, SelfImproveHooks)


class TestRunBaseline:
    """Test baseline measurement."""

    def test_baseline_success(self, tmp_path):
        imp = _make_improver(tmp_path)
        runner = ImprovementRunner(imp)
        ctx = runner.run_baseline()
        assert ctx["last_status"] == "baseline"
        assert ctx["baseline_score"] == 100.0
        assert ctx["best_score"] == 100.0
        assert ctx["current_score"] == 100.0
        assert ctx["iteration"] == 0

    def test_baseline_crash(self, tmp_path):
        imp = _make_improver(tmp_path, benchmark_cmd="exit 1")
        runner = ImprovementRunner(imp)
        ctx = runner.run_baseline()
        assert ctx["last_status"] == "crash"

    def test_baseline_logs_experiment(self, tmp_path):
        imp = _make_improver(tmp_path)
        runner = ImprovementRunner(imp)
        runner.run_baseline()
        assert len(imp.tracker.history) == 1
        assert imp.tracker.history[0].status == "keep"
        assert imp.tracker.history[0].description == "Baseline measurement"


class TestRunEvaluation:
    """Test single evaluation cycle."""

    def test_evaluation_no_improvement(self, tmp_path):
        # Same score as baseline → no improvement
        imp = _make_improver(tmp_path, benchmark_cmd="echo 'METRIC score=100'")
        runner = ImprovementRunner(imp)
        ctx = runner.run_baseline()
        ctx["iteration"] = 1
        ctx = runner.run_evaluation(ctx)
        assert ctx["last_status"] in ("no_improvement", "discard")
        # Should have logged a discard
        assert len(imp.tracker.history) >= 2

    def test_evaluation_with_callback(self, tmp_path):
        callback_calls = []

        def cb(iteration, ctx):
            callback_calls.append((iteration, ctx.get("last_status")))

        imp = _make_improver(tmp_path)
        runner = ImprovementRunner(imp, on_iteration=cb)
        ctx = runner.run_baseline()
        # iteration starts at 0 from baseline, _evaluate increments it
        runner.run_evaluation(ctx)
        assert len(callback_calls) == 1
        assert callback_calls[0][0] == 1  # _evaluate increments 0→1

    def test_evaluation_crash(self, tmp_path):
        imp = _make_improver(tmp_path, benchmark_cmd="echo 'METRIC score=100'")
        runner = ImprovementRunner(imp)
        ctx = runner.run_baseline()

        # Now switch benchmark to crash
        imp._benchmark_command = "exit 1"
        ctx["iteration"] = 1
        ctx = runner.run_evaluation(ctx)
        assert ctx["last_status"] in ("crash", "discard")


class TestRunLoop:
    """Test the full evaluation loop."""

    def test_run_with_stable_benchmark(self, tmp_path):
        imp = _make_improver(tmp_path, benchmark_cmd="echo 'METRIC score=100'")
        runner = ImprovementRunner(imp, max_iterations=3)
        ctx = runner.run()

        # Should have baseline + 3 evaluations, iteration incremented by _evaluate
        assert ctx["completed_iterations"] == 3
        assert "final_summary" in ctx
        assert ctx["final_summary"]["total_experiments"] >= 1
        # 3 consecutive failures of no_improvement stops via budget_exhausted
        # or runs all 3 iterations

    def test_run_stops_on_crash(self, tmp_path):
        # Start with working benchmark
        script = tmp_path / "bench.sh"
        script.write_text("#!/bin/bash\necho 'METRIC score=100'\nexit 0\n")
        script.chmod(0o755)

        imp = _make_improver(tmp_path, benchmark_cmd=f"bash {script}")
        runner = ImprovementRunner(imp, max_iterations=5)

        # Run baseline first
        ctx = runner.run_baseline()
        assert ctx["last_status"] == "baseline"

        # Now break the benchmark
        script.write_text("#!/bin/bash\nexit 1\n")
        ctx["iteration"] = 1
        ctx = runner.run_evaluation(ctx)
        assert ctx.get("consecutive_failures", 0) >= 1

    def test_run_max_iterations_respected(self, tmp_path):
        imp = _make_improver(tmp_path)
        runner = ImprovementRunner(imp, max_iterations=2)
        ctx = runner.run()
        assert ctx["completed_iterations"] <= 2

    def test_run_baseline_crash_aborts(self, tmp_path):
        imp = _make_improver(tmp_path, benchmark_cmd="exit 1")
        runner = ImprovementRunner(imp, max_iterations=5)
        ctx = runner.run()
        assert ctx["last_status"] == "crash"
        assert "completed_iterations" not in ctx or ctx.get("completed_iterations", 0) == 0


class TestFormatOutput:
    """Test format_status and format_history."""

    def test_format_status(self, tmp_path):
        imp = _make_improver(tmp_path)
        runner = ImprovementRunner(imp, max_iterations=2)
        ctx = runner.run()
        status = runner.format_status(ctx)
        assert "Session" in status
        assert "Metric" in status
        assert "Experiments" in status

    def test_format_history_empty(self, tmp_path):
        imp = _make_improver(tmp_path)
        runner = ImprovementRunner(imp)
        text = runner.format_history()
        assert "No experiments" in text

    def test_format_history_with_data(self, tmp_path):
        imp = _make_improver(tmp_path)
        runner = ImprovementRunner(imp, max_iterations=2)
        ctx = runner.run()
        text = runner.format_history(ctx)
        assert "#" in text or "Status" in text
        assert "Baseline" in text or "keep" in text

    def test_format_status_with_stop_reason(self, tmp_path):
        imp = _make_improver(tmp_path, benchmark_cmd="exit 1")
        runner = ImprovementRunner(imp)
        ctx = runner.run()
        status = runner.format_status(ctx)
        # Crash context
        assert "Session" in status


class TestImprovementRunnerExport:
    """Test ImprovementRunner is properly exported."""

    def test_importable_from_package(self):
        from flatmachines_cli import ImprovementRunner as IR
        assert IR is ImprovementRunner

    def test_importable_from_improve(self):
        from flatmachines_cli.improve import ImprovementRunner as IR
        assert IR is ImprovementRunner

    def test_has_docstring(self):
        assert ImprovementRunner.__doc__
        assert "evaluate" in ImprovementRunner.__doc__.lower()


class TestREPLImproveSubcommands:
    """Test REPL improve subcommand integration."""

    def test_improve_status_calls_validate(self):
        """improve status should validate the built-in config."""
        from flatmachines_cli.improve import validate_self_improve_config
        result = validate_self_improve_config()
        assert result["valid"]

    def test_improve_validate_no_args(self):
        """improve validate with no args validates built-in."""
        from flatmachines_cli.improve import validate_self_improve_config
        result = validate_self_improve_config(None)
        assert result["valid"]

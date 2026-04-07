"""
Self-improvement orchestration for flatmachines_cli.

Provides the SelfImprover class that coordinates the self-improvement loop,
and action handlers for the self_improve.yml FlatMachine config.

The self-improvement pattern:
1. Analyze: Run benchmarks, identify improvement opportunities
2. Implement: Make changes using a coding agent (any adapter)
3. Evaluate: Run benchmarks again, compare to baseline
4. Archive: Keep improvements, revert regressions

This module is the "brain" that connects experiment tracking
(experiment.py) with the FlatMachine execution engine.

Usage:
    improver = SelfImprover(
        target_dir="./my_project",
        benchmark_command="pytest tests/ -q",
        metric_name="test_count",
        direction="higher",
    )

    # Run a single improvement iteration
    result = await improver.run_iteration()

    # Run the full improvement loop via FlatMachine
    await improver.run_loop(max_iterations=10)
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .experiment import ExperimentTracker, ExperimentResult, parse_metrics

logger = logging.getLogger(__name__)


class SelfImprover:
    """
    Coordinates self-improvement using experiment tracking.

    Designed to be used standalone or as the backing logic for
    the self_improve.yml FlatMachine states.
    """

    def __init__(
        self,
        target_dir: str = ".",
        benchmark_command: str = "echo 'METRIC score=0'",
        test_command: str = "",
        metric_name: str = "score",
        direction: str = "higher",
        log_path: Optional[str] = None,
        working_dir: Optional[str] = None,
        git_enabled: bool = False,
    ):
        self._target_dir = os.path.abspath(target_dir)
        self._benchmark_command = benchmark_command
        self._test_command = test_command
        self._working_dir = working_dir or os.getcwd()
        self._git_enabled = git_enabled

        self._tracker = ExperimentTracker(
            name=f"self-improve-{Path(target_dir).name}",
            metric_name=metric_name,
            direction=direction,
            log_path=log_path or str(
                Path(self._target_dir) / ".self_improve" / "experiments.jsonl"
            ),
            working_dir=self._working_dir,
            git_enabled=git_enabled,
        )
        self._tracker.initialize()

    @property
    def tracker(self) -> ExperimentTracker:
        """Access the underlying experiment tracker."""
        return self._tracker

    @property
    def target_dir(self) -> str:
        return self._target_dir

    @property
    def benchmark_command(self) -> str:
        return self._benchmark_command

    def run_benchmark(self) -> ExperimentResult:
        """Run the benchmark command and return results with parsed metrics."""
        return self._tracker.run_command(
            self._benchmark_command,
            timeout=300.0,
        )

    def run_tests(self) -> ExperimentResult:
        """Run the test command (if configured) and return results."""
        if not self._test_command:
            return ExperimentResult(
                command="(no test command)",
                exit_code=0,
                stdout="",
                stderr="",
                duration_s=0.0,
                success=True,
            )
        return self._tracker.run_command(
            self._test_command,
            timeout=300.0,
        )

    def evaluate(self, result: ExperimentResult) -> Dict[str, Any]:
        """Evaluate a benchmark result against the current best.

        Returns:
            Dict with:
                improved: bool — whether the metric improved
                metric_value: float — the primary metric value
                metric_name: str — the metric name
                best_value: float|None — current best
                delta: float|None — improvement amount
        """
        metric_name = self._tracker.metric_name
        metric_value = result.metrics.get(metric_name, 0.0)
        improved = self._tracker.is_improved(metric_value)
        best = self._tracker.best_metric()

        delta = None
        if best is not None:
            delta = metric_value - best
            if self._tracker.direction == "lower":
                delta = -delta  # Positive delta = improvement for both directions

        return {
            "improved": improved,
            "metric_value": metric_value,
            "metric_name": metric_name,
            "best_value": best,
            "delta": delta,
        }

    def log_improvement(
        self,
        result: ExperimentResult,
        status: str,
        description: str = "",
        notes: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Log an improvement attempt."""
        self._tracker.log_result(
            result=result,
            status=status,
            description=description,
            notes=notes,
        )

    def summary(self) -> Dict[str, Any]:
        """Get a summary of the improvement session."""
        return self._tracker.summary()


class SelfImproveHooks:
    """
    Action handlers for the self_improve.yml FlatMachine config.

    Wire these into the machine's hooks to handle:
    - evaluate_improvement: run benchmark, compare to best
    - archive_result: log the experiment result
    - revert_changes: undo failed changes

    Usage:
        hooks = SelfImproveHooks(improver)
        # Register with CLIHooks or MachineHooks
    """

    def __init__(self, improver: SelfImprover):
        self._improver = improver
        self._last_result: Optional[ExperimentResult] = None

    def on_action(self, action_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Handle self-improvement actions."""
        handlers = {
            "evaluate_improvement": self._evaluate,
            "archive_result": self._archive,
            "revert_changes": self._revert,
        }

        handler = handlers.get(action_name)
        if handler:
            return handler(context)
        return context

    def _evaluate(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Run benchmark and evaluate improvement."""
        # Run tests first (if configured)
        test_result = self._improver.run_tests()
        if not test_result.success and self._improver._test_command:
            context["last_status"] = "failed_tests"
            context["consecutive_failures"] = context.get("consecutive_failures", 0) + 1
            return context

        # Run benchmark
        result = self._improver.run_benchmark()
        self._last_result = result

        if not result.success:
            context["last_status"] = "crash"
            context["consecutive_failures"] = context.get("consecutive_failures", 0) + 1
            return context

        # Evaluate
        evaluation = self._improver.evaluate(result)
        context["current_score"] = evaluation["metric_value"]
        context["iteration"] = context.get("iteration", 0) + 1

        if evaluation["improved"]:
            context["last_status"] = "improved"
            context["best_score"] = evaluation["metric_value"]
            context["consecutive_failures"] = 0
        else:
            context["last_status"] = "no_improvement"
            context["consecutive_failures"] = context.get("consecutive_failures", 0) + 1

        return context

    def _archive(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Archive the experiment result."""
        if self._last_result:
            status = "keep" if context.get("last_status") == "improved" else "discard"
            hypothesis = context.get("last_hypothesis", "")
            self._improver.log_improvement(
                result=self._last_result,
                status=status,
                description=hypothesis,
                notes={
                    "iteration": context.get("iteration", 0),
                    "score": context.get("current_score"),
                    "best_score": context.get("best_score"),
                },
            )

            # Update history in context
            history = context.get("improvement_history", [])
            history.append({
                "iteration": context.get("iteration", 0),
                "status": status,
                "score": context.get("current_score"),
                "hypothesis": hypothesis[:200],
            })
            context["improvement_history"] = history

        return context

    def _revert(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Revert failed changes (log as discard)."""
        if self._last_result:
            self._improver.log_improvement(
                result=self._last_result,
                status="discard",
                description=f"Reverted: {context.get('last_hypothesis', 'no improvement')}",
                notes={
                    "iteration": context.get("iteration", 0),
                    "reverted": True,
                },
            )

        # Update history
        history = context.get("improvement_history", [])
        history.append({
            "iteration": context.get("iteration", 0),
            "status": "discard",
            "score": context.get("current_score"),
            "hypothesis": context.get("last_hypothesis", "")[:200],
        })
        context["improvement_history"] = history

        return context

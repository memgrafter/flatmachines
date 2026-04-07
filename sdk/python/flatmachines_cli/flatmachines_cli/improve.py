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


def validate_self_improve_config(
    config_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Validate a self-improvement machine config and its agent references.

    Checks:
    - Machine config is valid flatmachine YAML
    - Has required states (analyze, implement, evaluate)
    - Has initial and final states
    - All transitions target existing states
    - Agent references resolve to existing files
    - Agent configs are valid flatagent YAML
    - Agents use profile-based model (adapter-agnostic)
    - Profiles.yml exists (optional warning)

    Args:
        config_path: Path to the machine YAML. If None, uses the
                     built-in self_improve.yml.

    Returns:
        Dict with:
            valid: bool
            errors: list of error strings
            warnings: list of warning strings
            info: dict of parsed config summary
    """
    import yaml

    errors: List[str] = []
    warnings: List[str] = []
    info: Dict[str, Any] = {}

    # Resolve config path
    if config_path is None:
        config_path = str(
            Path(__file__).parent.parent / "config" / "self_improve.yml"
        )

    config_dir = Path(config_path).parent

    # Load machine config
    try:
        with open(config_path) as f:
            config = yaml.safe_load(f)
    except FileNotFoundError:
        errors.append(f"Config file not found: {config_path}")
        return {"valid": False, "errors": errors, "warnings": warnings, "info": info}
    except yaml.YAMLError as e:
        errors.append(f"Invalid YAML: {e}")
        return {"valid": False, "errors": errors, "warnings": warnings, "info": info}

    # Check spec
    if config.get("spec") != "flatmachine":
        errors.append(f"Expected spec: flatmachine, got: {config.get('spec')}")

    data = config.get("data", {})
    info["name"] = data.get("name", "unnamed")
    info["spec_version"] = config.get("spec_version", "?")

    # Check states
    states = data.get("states", {})
    info["state_count"] = len(states)
    state_names = set(states.keys())

    # Required state types
    initial_states = [s for s, d in states.items() if d.get("type") == "initial"]
    final_states = [s for s, d in states.items() if d.get("type") == "final"]
    if not initial_states:
        errors.append("No initial state found")
    if not final_states:
        errors.append("No final state found")
    if len(initial_states) > 1:
        warnings.append(f"Multiple initial states: {initial_states}")

    # Required state patterns
    has_analyze = any(
        "analy" in s.lower() or "assess" in s.lower() or "benchmark" in s.lower()
        for s in state_names
    )
    has_implement = any(
        "implement" in s.lower() or "work" in s.lower() or "code" in s.lower()
        for s in state_names
    )
    has_evaluate = any(
        "eval" in s.lower() or "check" in s.lower() or "test" in s.lower()
        for s in state_names
    )

    if not has_analyze:
        errors.append("No analyze/benchmark state found")
    if not has_implement:
        errors.append("No implement/work state found")
    if not has_evaluate:
        errors.append("No evaluate/check state found")

    # Transition validation
    for sname, sdata in states.items():
        for t in sdata.get("transitions", []):
            target = t.get("to", "")
            if target and target not in state_names:
                errors.append(
                    f"State '{sname}' transitions to '{target}' which doesn't exist"
                )

    # Agent references
    agents = data.get("agents", {})
    info["agent_count"] = len(agents)

    for aname, aref in agents.items():
        if isinstance(aref, str):
            agent_path = config_dir / aref
            if not agent_path.exists():
                errors.append(f"Agent '{aname}' references '{aref}' — file not found")
            else:
                # Validate agent config
                try:
                    with open(agent_path) as f:
                        agent_config = yaml.safe_load(f)
                    if agent_config.get("spec") != "flatagent":
                        errors.append(
                            f"Agent '{aname}' has spec={agent_config.get('spec')}, expected flatagent"
                        )
                    # Check model is profile-based
                    model = agent_config.get("data", {}).get("model")
                    if isinstance(model, dict):
                        warnings.append(
                            f"Agent '{aname}' uses hardcoded model config — "
                            "consider using a profile name for adapter flexibility"
                        )
                except Exception as e:
                    errors.append(f"Agent '{aname}' config error: {e}")

    # Used agents are declared
    used_agents = set()
    for sdata in states.values():
        a = sdata.get("agent")
        if a:
            used_agents.add(a)
    undeclared = used_agents - set(agents.keys())
    if undeclared:
        errors.append(f"States reference undeclared agents: {undeclared}")

    # Profiles.yml check (optional)
    profiles_path = config_dir / "profiles.yml"
    if profiles_path.exists():
        info["has_profiles"] = True
    else:
        warnings.append("No profiles.yml found — agents will use litellm defaults")
        info["has_profiles"] = False

    # Budget control
    has_budget = (
        data.get("max_steps") is not None
        or "max_iterations" in data.get("context", {})
        or any("budget" in s.lower() for s in state_names)
    )
    if not has_budget:
        warnings.append("No budget control (max_steps, max_iterations, or check_budget state)")

    info["errors"] = len(errors)
    info["warnings"] = len(warnings)

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "info": info,
    }

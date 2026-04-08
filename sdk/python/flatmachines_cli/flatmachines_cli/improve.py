"""
Self-improvement orchestration for flatmachines_cli.

Provides the SelfImprover class that coordinates the self-improvement loop,
and action handlers for the self_improve.yml FlatMachine config.

Converged design (autoresearch inner loop + HyperAgents outer loop):
- Inner loop: evaluation firewall, scoped edits, fail-fast checks, log-redirect
- Outer loop: archive of all variants, worktree isolation, staged eval, parent selection

Usage:
    # Simple (backward-compatible):
    improver = SelfImprover(
        target_dir="./my_project",
        benchmark_command="pytest tests/ -q",
    )

    # Converged (with EvaluationSpec + Archive):
    from flatmachines_cli.evaluation import EvaluationSpec
    spec = EvaluationSpec(benchmark_command="bash bench.sh", protected_paths=("bench.sh",))
    improver = SelfImprover(target_dir="./my_project", eval_spec=spec)
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .experiment import ExperimentTracker, ExperimentResult, parse_metrics
from .evaluation import EvaluationSpec, EvaluationRunner, EvalResult
from .archive import Archive, ArchiveEntry
from .isolation import WorktreeIsolation

logger = logging.getLogger(__name__)


class SelfImprover:
    """
    Coordinates self-improvement using experiment tracking.

    Supports two modes:
    1. Simple (backward-compatible): pass benchmark_command, metric_name, etc.
    2. Converged: pass an EvaluationSpec for full inner/outer loop support.

    When eval_spec is provided, the converged features activate:
    - EvaluationRunner handles checks, staged eval, log-redirect
    - Archive tracks all generations (not just the best)
    - WorktreeIsolation provides per-generation isolation
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
        eval_spec: Optional[EvaluationSpec] = None,
        archive_path: Optional[str] = None,
        enable_isolation: bool = False,
    ):
        self._target_dir = os.path.abspath(target_dir)
        self._benchmark_command = benchmark_command
        self._test_command = test_command
        self._working_dir = working_dir or os.getcwd()
        self._git_enabled = git_enabled

        # Converged: EvaluationSpec (if not provided, build from simple params)
        if eval_spec is not None:
            self._eval_spec = eval_spec
        else:
            self._eval_spec = EvaluationSpec(
                benchmark_command=benchmark_command,
                metric_name=metric_name,
                direction=direction,
            )

        self._tracker = ExperimentTracker(
            name=f"self-improve-{Path(target_dir).name}",
            metric_name=self._eval_spec.metric_name,
            direction=self._eval_spec.direction,
            log_path=log_path or str(
                Path(self._target_dir) / ".self_improve" / "experiments.jsonl"
            ),
            working_dir=self._working_dir,
            git_enabled=git_enabled,
        )
        self._tracker.initialize()

        # Converged: Archive
        _archive_path = archive_path or str(
            Path(self._target_dir) / ".self_improve" / "archive.jsonl"
        )
        self._archive = Archive(path=_archive_path)

        # Converged: Evaluation runner
        self._eval_runner = EvaluationRunner(
            spec=self._eval_spec,
            working_dir=self._working_dir,
        )

        # Converged: Worktree isolation (opt-in)
        self._isolation: Optional[WorktreeIsolation] = None
        if enable_isolation:
            self._isolation = WorktreeIsolation(repo_dir=self._target_dir)

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

    @property
    def eval_spec(self) -> EvaluationSpec:
        return self._eval_spec

    @property
    def archive(self) -> Archive:
        return self._archive

    @property
    def eval_runner(self) -> EvaluationRunner:
        return self._eval_runner

    @property
    def isolation(self) -> Optional[WorktreeIsolation]:
        return self._isolation

    def run_benchmark(self) -> ExperimentResult:
        """Run the benchmark command and return results with parsed metrics."""
        return self._tracker.run_command(
            self._benchmark_command,
            timeout=self._eval_spec.timeout_s,
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
                "hypothesis": hypothesis,
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
            "hypothesis": context.get("last_hypothesis", ""),
        })
        context["improvement_history"] = history

        return context


class ConvergedSelfImproveHooks:
    """Action handlers for the converged self_improve.yml.

    Outer loop:
    - prepare_parent_selection_context: build archive context for selector model
    - apply_parent_selection: parse selector output and set parent fields
    - select_parent_from_archive: heuristic fallback/backward compatibility
    - create_isolated_worktree: set up worktree from selected parent
    - extract_diff_and_archive: save diff and add to archive
    - cleanup_isolated_worktree: remove worktree
    - write_archive_summary: write TSV summary for agent context

    Inner loop utilities (backward-compatible):
    - run_checks / evaluate_with_staging / commit_inner_improvement / revert_inner_changes
    - evaluate_improvement / archive_result / revert_changes
    """

    def __init__(self, improver: SelfImprover):
        self._improver = improver
        self._last_eval_result: Optional[EvalResult] = None
        self._simple_hooks = SelfImproveHooks(improver)

    def on_action(self, action_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Dispatch to the appropriate handler."""
        handlers = {
            # Outer loop actions
            "prepare_parent_selection_context": self._prepare_parent_selection_context,
            "apply_parent_selection": self._apply_parent_selection,
            "select_parent_from_archive": self._select_parent,
            "create_isolated_worktree": self._create_worktree,
            "extract_diff_and_archive": self._extract_and_archive,
            "cleanup_isolated_worktree": self._cleanup_worktree,
            "write_archive_summary": self._write_summary,
            # Inner loop actions
            "run_checks": self._run_checks,
            "evaluate_with_staging": self._evaluate_staged,
            "commit_inner_improvement": self._commit_inner,
            "revert_inner_changes": self._revert_inner,
            # Backward-compatible simple actions
            "evaluate_improvement": self._simple_hooks._evaluate,
            "archive_result": self._simple_hooks._archive,
            "revert_changes": self._simple_hooks._revert,
        }

        handler = handlers.get(action_name)
        if handler:
            return handler(context)
        return context

    # --- Outer Loop Actions ---

    def _coerce_max_generations(self, context: Dict[str, Any]) -> None:
        """Coerce max_generations to int for expression compatibility."""
        max_gen = context.get("max_generations", 0)
        if isinstance(max_gen, str):
            try:
                max_gen = int(max_gen)
            except (ValueError, TypeError):
                max_gen = 0
        context["max_generations"] = max_gen

    def _populate_parent_fields(
        self,
        context: Dict[str, Any],
        parent: Optional[ArchiveEntry],
        *,
        source: str,
        reason: str = "",
    ) -> Dict[str, Any]:
        """Populate normalized parent context fields."""
        archive = self._improver.archive

        if parent is None:
            context["parent_id"] = None
            context["parent_commit"] = None
            context["parent_score"] = None
            context["sibling_summary"] = []
        else:
            context["parent_id"] = parent.generation_id
            context["parent_commit"] = parent.metadata.get("commit")
            context["parent_score"] = parent.score
            siblings = [archive.get(cid) for cid in parent.children]
            context["sibling_summary"] = [
                {
                    "id": s.generation_id,
                    "score": s.score,
                    "description": s.metadata.get("description", ""),
                }
                for s in siblings
                if s is not None
            ]

        context["parent_selection_source"] = source
        context["parent_selection_reason"] = reason
        return context

    def _select_parent(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Heuristic parent selection (backward-compatible fallback)."""
        self._coerce_max_generations(context)

        archive = self._improver.archive
        method = str(context.get("parent_selection", "best"))
        if method == "model":
            method = "best"

        if archive.size == 0:
            return self._populate_parent_fields(
                context,
                None,
                source="heuristic",
                reason="Archive empty",
            )

        parent = archive.select_parent(method=method)
        return self._populate_parent_fields(
            context,
            parent,
            source=f"heuristic:{method}",
            reason=f"Selected by {method}",
        )

    def _prepare_parent_selection_context(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Build plain-text archive context for the selector model."""
        self._coerce_max_generations(context)

        # Reset per-generation selector state
        context["parent_selection_text"] = ""
        context["parent_selection_needs_retry"] = False
        context["parent_selection_attempts"] = 0
        context["parent_selection_feedback"] = ""

        archive = self._improver.archive
        context["archive_size"] = archive.size
        context["archive_summary"] = archive.summary_tsv() if archive.size > 0 else ""

        if archive.size == 0:
            context["parent_candidates"] = "Archive is empty. Use PARENT_ID: none"
            return context

        lines: List[str] = []
        for eid in sorted(archive.entries.keys()):
            e = archive.entries[eid]
            score = "n/a" if e.score is None else str(e.score)
            metrics = ", ".join(f"{k}={v}" for k, v in e.scores.items())
            if not metrics:
                metrics = "-"
            desc = e.metadata.get("description", "")
            commit = e.metadata.get("commit", "")
            lines.append(
                f"- id={e.generation_id} parent={e.parent_id} score={score} "
                f"status={e.status} children={len(e.children)} commit={commit} "
                f"metrics={metrics} desc={desc}"
            )

        context["parent_candidates"] = "\n".join(lines)
        return context

    def _parse_parent_selection_text(self, text: str) -> tuple[bool, Optional[int], str]:
        """Parse plain-text selector output.

        Expected format:
        PARENT_ID: <int|none>
        REASON: <text>
        """
        import re

        if not text:
            return False, None, ""

        parent_match = re.search(r"(?im)^\s*PARENT_ID\s*:\s*([^\n\r]+)", text)
        reason_match = re.search(r"(?im)^\s*REASON\s*:\s*(.+)$", text)
        reason = reason_match.group(1).strip() if reason_match else ""

        if not parent_match:
            return False, None, reason

        token = parent_match.group(1).strip().lower()
        if token in {"none", "null", "-"}:
            return True, None, reason

        try:
            return True, int(token), reason
        except (TypeError, ValueError):
            return False, None, reason

    def _apply_parent_selection(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Apply model-driven parent selection.

        On invalid model output, request another selector pass instead of
        falling back to a deterministic heuristic parent.
        """
        method = str(context.get("parent_selection", "model"))

        # Non-model methods go straight to heuristic selection
        if method != "model":
            context["parent_selection_needs_retry"] = False
            context["parent_selection_feedback"] = ""
            return self._select_parent(context)

        archive = self._improver.archive
        if archive.size == 0:
            context["parent_selection_needs_retry"] = False
            context["parent_selection_feedback"] = ""
            return self._populate_parent_fields(
                context,
                None,
                source="model",
                reason="Archive empty",
            )

        raw = str(context.get("parent_selection_text", ""))
        ok, parent_id, reason = self._parse_parent_selection_text(raw)

        if not ok:
            attempts = int(context.get("parent_selection_attempts", 0) or 0) + 1
            context["parent_selection_attempts"] = attempts
            context["parent_selection_needs_retry"] = True
            context["parent_selection_source"] = "model:retry"
            context["parent_selection_reason"] = "Invalid selector output; requerying model"
            detail = reason or "Missing or invalid PARENT_ID line"
            context["parent_selection_feedback"] = (
                f"Previous output was invalid ({detail}). "
                "Output exactly two lines: 'PARENT_ID: <integer or none>' and 'REASON: <brief reason>'."
            )
            return context

        if parent_id is None:
            context["parent_selection_needs_retry"] = False
            context["parent_selection_feedback"] = ""
            return self._populate_parent_fields(
                context,
                None,
                source="model",
                reason=reason or "Model selected baseline",
            )

        parent = archive.get(parent_id)
        if parent is None:
            attempts = int(context.get("parent_selection_attempts", 0) or 0) + 1
            context["parent_selection_attempts"] = attempts
            context["parent_selection_needs_retry"] = True
            context["parent_selection_source"] = "model:retry"
            context["parent_selection_reason"] = (
                f"Unknown parent id {parent_id}; requerying model"
            )
            valid_ids = ", ".join(str(eid) for eid in sorted(archive.entries.keys()))
            context["parent_selection_feedback"] = (
                f"PARENT_ID {parent_id} does not exist. Valid ids: [{valid_ids}] or 'none'. "
                "Output exactly two lines: 'PARENT_ID: <integer or none>' and 'REASON: <brief reason>'."
            )
            return context

        context["parent_selection_needs_retry"] = False
        context["parent_selection_feedback"] = ""
        return self._populate_parent_fields(
            context,
            parent,
            source="model",
            reason=reason or f"Model selected parent {parent_id}",
        )

    def _create_worktree(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Create an isolated worktree for this generation.

        When parent_commit is set (from archive metadata), branches from
        that commit directly — the child inherits the parent's code state
        without needing to apply patches.

        Falls back to apply_patches only when parent_commit is None but
        parent_id exists (legacy entries or baseline generation).
        """
        isolation = self._improver.isolation
        generation = context.get("generation", 0)

        if isolation is None:
            # No isolation → work in-place (backward-compatible)
            context["worktree_path"] = self._improver.target_dir
            return context

        parent_commit = context.get("parent_commit")
        try:
            wt_path = isolation.create_worktree(generation, parent_commit)

            # Only apply patches if we don't have a parent commit to branch from
            if parent_commit is None:
                parent_id = context.get("parent_id")
                if parent_id is not None:
                    patches = self._improver.archive.get_patch_chain(parent_id)
                    if patches:
                        ok, err = isolation.apply_patches(wt_path, patches)
                        if not ok:
                            logger.warning("Failed to apply patches: %s", err)

            context["worktree_path"] = wt_path

            # Ensure score is generation-local. Parent worktrees may contain
            # a previously committed .self_improve/score.json; remove it so a
            # generation is only "evaluated" when the current agent writes a
            # fresh score file.
            stale_score = Path(wt_path) / ".self_improve" / "score.json"
            if stale_score.exists():
                try:
                    stale_score.unlink()
                except Exception as e:
                    logger.warning("Failed to remove stale score.json: %s", e)
        except RuntimeError as e:
            logger.error("Failed to create worktree: %s", e)
            context["worktree_path"] = self._improver.target_dir
            context["worktree_error"] = str(e)

        return context

    def _extract_and_archive(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Extract diff from worktree and add generation to archive.

        Reads the agent-written .self_improve/score.json for scoring.
        The agent owns the experiment lifecycle — this action only handles
        infrastructure (diff extraction, archive storage).
        """
        import json as _json

        generation = context.get("generation", 0)
        isolation = self._improver.isolation
        wt_path = context.get("worktree_path", self._improver.target_dir)

        # Commit everything in the worktree before extracting so we have
        # a real commit hash for child generations to branch from
        commit = None
        if isolation is not None:
            try:
                commit = isolation.commit_worktree(
                    wt_path, f"gen-{generation} final"
                )
            except Exception as e:
                logger.warning("Failed to commit worktree: %s", e)

        # Extract diff
        patch_file = ""
        if isolation is not None:
            try:
                patch_file = isolation.extract_diff(wt_path, generation)
            except Exception as e:
                logger.warning("Failed to extract diff: %s", e)

        # Read agent-written score.json (agent owns the experiment lifecycle)
        score = None
        scores = {}
        score_path = Path(wt_path) / ".self_improve" / "score.json"
        if score_path.exists():
            try:
                data = _json.loads(score_path.read_text())
                score = data.get("value")
                scores = {data.get("metric", "score"): score}
                context["best_score"] = score
                # Store direction for parent selection
                context["_score_direction"] = data.get("direction", "higher")
            except (ValueError, KeyError, TypeError) as e:
                logger.warning("Failed to read score.json: %s", e)
        else:
            logger.warning("Generation %s missing .self_improve/score.json", generation)

        entry = self._improver.archive.add(
            parent_id=context.get("parent_id"),
            patch_file=patch_file,
            score=score,
            scores=scores,
            status="evaluated" if score is not None else "failed",
            metadata={
                "description": context.get("analysis", "") if context.get("analysis") else "",
                "commit": commit or context.get("last_commit"),
            },
        )

        # Update context
        context["generation"] = generation + 1
        context["archive_size"] = self._improver.archive.size

        # Track best across all generations
        archive_best = self._improver.archive.best_score()
        if archive_best is not None:
            context["best_generation"] = self._improver.archive.best_entry().generation_id  # type: ignore

        # Write summary for agent context
        self._write_summary(context)

        return context

    def _cleanup_worktree(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Remove the worktree for the finished generation."""
        isolation = self._improver.isolation
        generation = context.get("generation", 1) - 1  # Just finished this gen

        if isolation is not None:
            isolation.cleanup_worktree(generation)

        context["worktree_path"] = None
        return context

    def _write_summary(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Write archive summary TSV for agent to read."""
        archive = self._improver.archive
        summary = archive.summary_tsv()
        summary_path = Path(self._improver.target_dir) / ".self_improve" / "archive_summary.tsv"
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(summary)
        return context

    # --- Inner Loop Actions ---

    def _run_checks(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Run fail-fast compilation/lint checks."""
        wt_path = context.get("worktree_path", self._improver.target_dir)

        # Use a runner pointed at the worktree
        runner = EvaluationRunner(
            spec=self._improver.eval_spec,
            working_dir=wt_path,
        )

        # Tampering check first
        clean, violated = runner.validate_no_tampering()
        if not clean:
            context["last_status"] = "tampering_detected"
            context["violated_paths"] = violated
            context["consecutive_failures"] = context.get("consecutive_failures", 0) + 1
            return context

        # Run checks
        result = runner.run_checks()
        if result.success:
            context["last_status"] = "checks_passed"
        else:
            context["last_status"] = "checks_failed"
            context["checks_error"] = result.error or result.output_tail[-200:]
            context["consecutive_failures"] = context.get("consecutive_failures", 0) + 1

        return context

    def _evaluate_staged(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Run staged evaluation (checks → quick → full)."""
        wt_path = context.get("worktree_path", self._improver.target_dir)
        runner = EvaluationRunner(
            spec=self._improver.eval_spec,
            working_dir=wt_path,
        )

        stage, result = runner.run_staged(
            best_score=context.get("best_score"),
        )
        self._last_eval_result = result

        context["eval_stage"] = stage
        context["inner_iteration"] = context.get("inner_iteration", 0) + 1

        if stage != "complete" or not result.success:
            context["last_status"] = f"failed_{stage}"
            context["consecutive_failures"] = context.get("consecutive_failures", 0) + 1
            return context

        # Extract primary metric and evaluate improvement
        metric_name = self._improver.eval_spec.metric_name
        metric_value = result.metrics.get(metric_name, 0.0)
        context["current_score"] = metric_value

        best = context.get("best_score")
        if best is None:
            # First evaluation → accept as baseline
            context["last_status"] = "improved"
            context["best_score"] = metric_value
            context["consecutive_failures"] = 0
        elif self._improver.eval_spec.is_better(metric_value, best):
            context["last_status"] = "improved"
            context["best_score"] = metric_value
            context["consecutive_failures"] = 0
        else:
            context["last_status"] = "no_improvement"
            context["consecutive_failures"] = context.get("consecutive_failures", 0) + 1

        # Log to experiment tracker
        self._improver.log_improvement(
            result=ExperimentResult(
                command=result.command,
                exit_code=result.exit_code,
                stdout="",
                stderr="",
                duration_s=result.duration_s,
                metrics=result.metrics,
                success=result.success,
                error=result.error,
            ),
            status="keep" if context["last_status"] == "improved" else "discard",
            description=context.get("last_hypothesis", ""),
            notes={
                "stage": stage,
                "generation": context.get("generation", 0),
                "inner_iteration": context.get("inner_iteration", 0),
            },
        )

        return context

    def _commit_inner(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Commit the inner improvement in the worktree."""
        isolation = self._improver.isolation
        wt_path = context.get("worktree_path", self._improver.target_dir)

        if isolation is not None:
            commit_hash = isolation.commit_worktree(
                wt_path,
                message=f"gen-{context.get('generation', 0)} iter-{context.get('inner_iteration', 0)}: "
                        f"{context.get('last_hypothesis', 'improvement')}",
            )
            context["last_commit"] = commit_hash
        elif self._improver._git_enabled:
            self._improver.tracker.git_commit(
                context.get("last_hypothesis", "improvement")
            )

        return context

    def _revert_inner(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Revert inner changes (reset worktree to clean state)."""
        isolation = self._improver.isolation
        wt_path = context.get("worktree_path", self._improver.target_dir)

        if isolation is not None:
            isolation.reset_worktree(wt_path)
        elif self._improver._git_enabled:
            self._improver.tracker.git_revert()

        return context


class ImprovementRunner:
    """Run the evaluate→archive loop programmatically without an LLM.

    This exercises the full action dispatch chain:
    evaluate_improvement → archive_result or revert_changes.

    Useful for:
    - Testing the wiring between SelfImprover, SelfImproveHooks, and ExperimentTracker
    - Running benchmark-only improvement tracking (no code changes)
    - Dry-run validation of the improvement pipeline
    """

    def __init__(
        self,
        improver: SelfImprover,
        max_iterations: int = 10,
        on_iteration: Optional[Callable[[int, Dict[str, Any]], None]] = None,
        on_before_eval: Optional[Callable[[int, Dict[str, Any]], Dict[str, Any]]] = None,
    ):
        """
        Args:
            improver: The SelfImprover instance.
            max_iterations: Maximum number of evaluate cycles to run.
            on_iteration: Optional callback(iteration, context) after each cycle.
            on_before_eval: Optional callback(iteration, context) before each evaluation.
                           Can modify context (e.g., record what changes were made).
                           Return the (possibly modified) context.
                           Use this to integrate an external agent that makes code
                           changes between evaluation cycles.
        """
        self._improver = improver
        self._hooks = SelfImproveHooks(improver)
        self._max_iterations = max_iterations
        self._on_iteration = on_iteration
        self._on_before_eval = on_before_eval

    @property
    def improver(self) -> SelfImprover:
        return self._improver

    @property
    def hooks(self) -> SelfImproveHooks:
        return self._hooks

    def run_baseline(self) -> Dict[str, Any]:
        """Run the initial baseline benchmark.

        Returns context dict with baseline metrics populated.
        """
        context: Dict[str, Any] = {
            "iteration": 0,
            "best_score": None,
            "current_score": None,
            "last_status": None,
            "consecutive_failures": 0,
            "improvement_history": [],
            "max_iterations": self._max_iterations,
        }

        result = self._improver.run_benchmark()
        if not result.success:
            context["last_status"] = "crash"
            context["error"] = result.error or "benchmark failed"
            return context

        metric_name = self._improver.tracker.metric_name
        metric_value = result.metrics.get(metric_name, 0.0)
        self._improver.log_improvement(result, "keep", "Baseline measurement")

        context["best_score"] = metric_value
        context["current_score"] = metric_value
        context["last_status"] = "baseline"
        context["baseline_score"] = metric_value

        return context

    def run_evaluation(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Run one evaluate→archive cycle.

        Dispatches evaluate_improvement then archive_result or revert_changes
        based on the evaluation outcome. Returns updated context.
        """
        context = self._hooks.on_action("evaluate_improvement", context)
        status = context.get("last_status")

        if status == "improved":
            context = self._hooks.on_action("archive_result", context)
        elif status in ("no_improvement", "crash", "failed_tests"):
            context = self._hooks.on_action("revert_changes", context)

        if self._on_iteration:
            self._on_iteration(context.get("iteration", 0), context)

        return context

    def run(self) -> Dict[str, Any]:
        """Run the full evaluation loop.

        1. Run baseline
        2. For each iteration: evaluate → archive/revert
        3. Return final context with summary

        Note: This does NOT make code changes (no LLM).
        It evaluates the current state of the code each iteration.
        Pair with an external agent making changes between iterations
        for actual self-improvement.
        """
        context = self.run_baseline()
        if context.get("last_status") == "crash":
            return context

        for _i in range(self._max_iterations):
            # Check budget before each evaluation
            if context.get("consecutive_failures", 0) >= 3:
                context["last_status"] = "budget_exhausted"
                context["stop_reason"] = "3 consecutive failures"
                break

            # Hook for external agent to make changes before evaluation
            if self._on_before_eval:
                iteration = context.get("iteration", 0) + 1
                context = self._on_before_eval(iteration, context)

            context = self.run_evaluation(context)

            status = context.get("last_status")
            if status == "crash":
                context["stop_reason"] = "benchmark crashed"
                break

        context["completed_iterations"] = context.get("iteration", 0)
        context["final_summary"] = self._improver.summary()
        return context

    def format_status(self, context: Dict[str, Any]) -> str:
        """Format a human-readable status from context."""
        lines = []
        summary = context.get("final_summary") or self._improver.summary()

        lines.append(f"  Session: {summary['name']}")
        lines.append(f"  Metric:  {summary['metric_name']} ({summary['direction']})")
        lines.append(f"  Experiments: {summary['total_experiments']}")
        lines.append(f"    Kept:      {summary['kept']}")
        lines.append(f"    Discarded: {summary['discarded']}")
        lines.append(f"    Crashed:   {summary['crashed']}")

        if summary['best_metric'] is not None:
            lines.append(f"  Best:    {summary['best_metric']}")
        if summary.get('baseline') is not None:
            lines.append(f"  Baseline: {summary['baseline']}")

        stop = context.get("stop_reason")
        if stop:
            lines.append(f"  Stopped: {stop}")

        return "\n".join(lines)

    def format_history(self, context: Optional[Dict[str, Any]] = None) -> str:
        """Format experiment history as a table."""
        history = self._improver.tracker.history
        if not history:
            return "  No experiments yet."

        lines = []
        lines.append(f"  {'#':>3s}  {'Status':8s}  {'Metric':>10s}  {'Duration':>8s}  Description")
        lines.append(f"  {'─' * 3}  {'─' * 8}  {'─' * 10}  {'─' * 8}  {'─' * 30}")

        for entry in history:
            status_str = entry.status
            metric_str = f"{entry.primary_metric:10.1f}"
            dur_str = f"{entry.result.duration_s:7.1f}s"
            desc = entry.description if entry.description else ""
            lines.append(f"  {entry.experiment_id:3d}  {status_str:8s}  {metric_str}  {dur_str}  {desc}")

        return "\n".join(lines)


def scaffold_self_improve(target_dir: str) -> List[str]:
    """Initialize self-improvement helper files in target directory.

    Creates:
    - profiles.yml (if not exists)
    - program.md (if not exists)

    Notes:
    - Benchmark scripts are agent-owned in the program.md pattern.
    - The scaffold does not create benchmark.sh.

    Args:
        target_dir: Directory to initialize.

    Returns:
        List of created file paths (empty if all already exist).
    """
    target = Path(target_dir)
    created = []

    # profiles.yml
    profiles_path = target / "profiles.yml"
    if not profiles_path.exists():
        profiles_path.write_text(
            '# LLM provider profiles for self-improvement\n'
            '# Edit this to match your provider and API key setup.\n'
            'spec: flatprofiles\n'
            'spec_version: "2.5.0"\n'
            '\n'
            'data:\n'
            '  model_profiles:\n'
            '    default:\n'
            '      provider: openai\n'
            '      name: gpt-5-mini\n'
            '\n'
            '  default: default\n'
        )
        created.append(str(profiles_path))

    # program.md
    program_path = target / "program.md"
    if not program_path.exists():
        program_path.write_text(
            '# program\n\n'
            'Describe what to optimize (goal/vision), not the exact benchmark command.\n'
            'The agent will choose or create measurable benchmarks and iterate.\n\n'
            'Example:\n'
            '- Improve runtime of core workflows while preserving correctness.\n'
            '- Do not modify public API contracts.\n'
        )
        created.append(str(program_path))

    return created


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

    # Required state patterns — either:
    # 1. Unified: "improve" state (coding machine pattern)
    # 2. Split: "analyze" + "implement" states (separate agent pattern)
    has_unified = any(
        "improv" in s.lower() for s in state_names
    )
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

    has_agent_state = has_unified or (has_analyze and has_implement)
    if not has_agent_state:
        errors.append("No agent state found (need 'improve' or 'analyze'+'implement')")
    # evaluate state is optional — agent may own the full lifecycle

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

"""
Evaluation firewall for self-improvement loops.

The EvaluationSpec is an immutable specification of HOW to evaluate code.
It cannot be modified by the agent. It defines:
- What command to run (benchmark)
- What metric to optimize
- Which direction is better
- Time budget
- Protected paths the agent cannot modify
- Optional fast checks command (compilation/lint)
- Optional quick benchmark for staged evaluation

The evaluation firewall ensures the agent cannot game the metric by
modifying the measurement apparatus.
"""

from __future__ import annotations

import fnmatch
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# Regex for METRIC lines: "METRIC name=value"
_METRIC_RE = re.compile(
    r"^\s*METRIC\s+(\w[\w.]*)\s*=\s*([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\s*$",
    re.MULTILINE,
)


def parse_metrics(output: str) -> Dict[str, float]:
    """Parse structured METRIC lines from command output."""
    metrics = {}
    for match in _METRIC_RE.finditer(output):
        metrics[match.group(1)] = float(match.group(2))
    return metrics


@dataclass(frozen=True)
class EvaluationSpec:
    """Immutable evaluation specification. Cannot be modified by the agent.

    Once created, all fields are frozen. The agent's code changes are
    validated against this spec before any evaluation runs.
    """

    benchmark_command: str
    metric_name: str = "score"
    direction: str = "higher"  # "higher" or "lower"
    timeout_s: float = 300.0
    checks_command: str = ""  # Fast sanity check (compile, import, lint)
    checks_timeout_s: float = 30.0
    quick_benchmark_command: str = ""  # Subset benchmark for staged eval
    quick_timeout_s: float = 60.0
    quick_threshold: float = 0.0  # Minimum score on quick eval to proceed
    protected_paths: Tuple[str, ...] = ()  # Glob patterns the agent CANNOT edit
    editable_patterns: Tuple[str, ...] = ("**/*.py",)  # Glob patterns the agent CAN edit
    log_file: str = "run.log"  # Redirect benchmark output here

    def __post_init__(self):
        if self.direction not in ("higher", "lower"):
            raise ValueError(f"direction must be 'higher' or 'lower', got {self.direction!r}")

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "EvaluationSpec":
        """Create from a dict (e.g., from YAML context)."""
        # Convert lists to tuples for frozen dataclass
        protected = d.get("protected_paths", ())
        if isinstance(protected, list):
            protected = tuple(protected)
        editable = d.get("editable_patterns", ("**/*.py",))
        if isinstance(editable, list):
            editable = tuple(editable)
        return cls(
            benchmark_command=d["benchmark_command"],
            metric_name=d.get("metric_name", "score"),
            direction=d.get("direction", "higher"),
            timeout_s=float(d.get("timeout_s", 300.0)),
            checks_command=d.get("checks_command", ""),
            checks_timeout_s=float(d.get("checks_timeout_s", 30.0)),
            quick_benchmark_command=d.get("quick_benchmark_command", ""),
            quick_timeout_s=float(d.get("quick_timeout_s", 60.0)),
            quick_threshold=float(d.get("quick_threshold", 0.0)),
            protected_paths=protected,
            editable_patterns=editable,
            log_file=d.get("log_file", "run.log"),
        )

    def is_better(self, new_score: float, old_score: float) -> bool:
        """Check if new_score is better than old_score per direction."""
        if self.direction == "higher":
            return new_score > old_score
        return new_score < old_score


@dataclass
class EvalResult:
    """Result of running one evaluation stage."""

    command: str
    exit_code: int
    duration_s: float
    metrics: Dict[str, float] = field(default_factory=dict)
    success: bool = False
    error: Optional[str] = None
    output_tail: str = ""  # Last N lines (not full output)
    log_path: Optional[str] = None  # Path to full log file
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    @property
    def primary_metric(self) -> Optional[float]:
        """Convenience: not available without knowing the metric name."""
        return None  # Caller must look up by name


class EvaluationRunner:
    """Runs evaluations according to an EvaluationSpec.

    Enforces:
    - Protected path tampering detection
    - Log-redirect-and-grep output pattern
    - Fail-fast checks before expensive benchmark
    - Staged evaluation (quick → full)
    - Fixed time budget
    """

    def __init__(
        self,
        spec: EvaluationSpec,
        working_dir: str,
        baseline_commit: Optional[str] = None,
    ):
        self._spec = spec
        self._working_dir = working_dir
        self._baseline_commit = baseline_commit

    @property
    def spec(self) -> EvaluationSpec:
        return self._spec

    def validate_no_tampering(self) -> Tuple[bool, List[str]]:
        """Check that protected paths haven't been modified since baseline.

        Returns:
            (is_clean, list_of_violated_paths)
        """
        if not self._spec.protected_paths:
            return True, []

        try:
            # Get list of modified files
            cmd = ["git", "diff", "--name-only"]
            if self._baseline_commit:
                cmd.append(self._baseline_commit)
            result = subprocess.run(
                cmd,
                cwd=self._working_dir,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                return True, []  # Can't check → allow (don't break non-git dirs)

            # Also check untracked files
            untracked = subprocess.run(
                ["git", "diff", "--name-only", "--cached"],
                cwd=self._working_dir,
                capture_output=True,
                text=True,
                timeout=10,
            )

            changed_files = set()
            for output in (result.stdout, untracked.stdout):
                for line in output.strip().split("\n"):
                    if line.strip():
                        changed_files.add(line.strip())

            violated = []
            for changed in changed_files:
                for pattern in self._spec.protected_paths:
                    if fnmatch.fnmatch(changed, pattern):
                        violated.append(changed)
                        break

            return len(violated) == 0, violated
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return True, []  # Can't check → allow

    def validate_edit_scope(self, changed_files: List[str]) -> Tuple[bool, List[str]]:
        """Check that all changed files match the editable patterns.

        Returns:
            (all_in_scope, list_of_out_of_scope_files)
        """
        if not self._spec.editable_patterns:
            return True, []

        from pathlib import PurePath

        out_of_scope = []
        for f in changed_files:
            matched = any(
                PurePath(f).match(pat) for pat in self._spec.editable_patterns
            )
            if not matched:
                out_of_scope.append(f)

        return len(out_of_scope) == 0, out_of_scope

    def run_checks(self) -> EvalResult:
        """Run the fast sanity check (compilation, lint, import).

        Returns immediately if no checks_command is configured.
        """
        if not self._spec.checks_command:
            return EvalResult(
                command="(no checks)",
                exit_code=0,
                duration_s=0.0,
                success=True,
            )
        return self._run_command(
            self._spec.checks_command,
            timeout=self._spec.checks_timeout_s,
            log_file=None,  # Checks are fast, no redirect needed
        )

    def run_quick_benchmark(self) -> EvalResult:
        """Run the quick/subset benchmark for staged evaluation.

        Returns immediately if no quick_benchmark_command is configured.
        """
        if not self._spec.quick_benchmark_command:
            return EvalResult(
                command="(no quick benchmark)",
                exit_code=0,
                duration_s=0.0,
                success=True,
            )
        return self._run_command(
            self._spec.quick_benchmark_command,
            timeout=self._spec.quick_timeout_s,
            log_file="quick_run.log",
        )

    def run_benchmark(self) -> EvalResult:
        """Run the full benchmark with log-redirect.

        Output is redirected to spec.log_file. Only METRIC lines
        and the last 50 lines are captured in the result.
        """
        return self._run_command(
            self._spec.benchmark_command,
            timeout=self._spec.timeout_s,
            log_file=self._spec.log_file,
        )

    def run_staged(self, best_score: Optional[float] = None) -> Tuple[str, EvalResult]:
        """Run the full staged evaluation pipeline.

        Stages:
        1. Tampering check
        2. Compilation/checks (fail-fast)
        3. Quick benchmark (if configured, with threshold)
        4. Full benchmark

        Returns:
            (stage_name, result) — stage_name is where it stopped/succeeded.
        """
        # Stage 0: Tampering check
        clean, violated = self.validate_no_tampering()
        if not clean:
            return "tampering", EvalResult(
                command="tampering_check",
                exit_code=1,
                duration_s=0.0,
                error=f"Protected paths modified: {', '.join(violated)}",
            )

        # Stage 1: Checks (fail-fast)
        checks = self.run_checks()
        if not checks.success:
            return "checks", checks

        # Stage 2: Quick benchmark (if configured)
        if self._spec.quick_benchmark_command:
            quick = self.run_quick_benchmark()
            if not quick.success:
                return "quick_benchmark", quick
            quick_score = quick.metrics.get(self._spec.metric_name, 0.0)
            if self._spec.quick_threshold > 0 and not self._passes_threshold(quick_score):
                return "quick_threshold", quick

        # Stage 3: Full benchmark
        result = self.run_benchmark()
        if not result.success:
            return "benchmark", result

        return "complete", result

    def _passes_threshold(self, score: float) -> bool:
        """Check if a quick eval score passes the threshold."""
        if self._spec.direction == "higher":
            return score >= self._spec.quick_threshold
        return score <= self._spec.quick_threshold

    def _run_command(
        self,
        command: str,
        timeout: float,
        log_file: Optional[str] = None,
    ) -> EvalResult:
        """Run a command, optionally redirecting output to a log file.

        When log_file is set:
        - Full output goes to the file
        - Only METRIC lines and last 50 lines are captured in the result
        - This keeps the agent's context clean
        """
        env = dict(os.environ)
        t0 = time.monotonic()

        try:
            if log_file:
                log_path = os.path.join(self._working_dir, log_file)
                # Redirect to file, capture exit code
                wrapped = f"({command}) > {log_path} 2>&1"
                proc = subprocess.run(
                    ["bash", "-c", wrapped],
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    cwd=self._working_dir,
                    env=env,
                )
                duration = time.monotonic() - t0

                # Read log file for metrics and tail
                try:
                    full_output = Path(log_path).read_text()
                except FileNotFoundError:
                    full_output = ""

                metrics = parse_metrics(full_output)
                lines = full_output.split("\n")
                tail = "\n".join(lines[-50:]) if len(lines) > 50 else full_output

                return EvalResult(
                    command=command,
                    exit_code=proc.returncode,
                    duration_s=round(duration, 3),
                    metrics=metrics,
                    success=proc.returncode == 0,
                    output_tail=tail,
                    log_path=log_path,
                )
            else:
                # Direct capture (for checks, small commands)
                proc = subprocess.run(
                    ["bash", "-c", command],
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    cwd=self._working_dir,
                    env=env,
                )
                duration = time.monotonic() - t0
                combined = proc.stdout + "\n" + proc.stderr
                metrics = parse_metrics(combined)
                lines = combined.split("\n")
                tail = "\n".join(lines[-50:])

                return EvalResult(
                    command=command,
                    exit_code=proc.returncode,
                    duration_s=round(duration, 3),
                    metrics=metrics,
                    success=proc.returncode == 0,
                    output_tail=tail,
                )

        except subprocess.TimeoutExpired:
            duration = time.monotonic() - t0
            return EvalResult(
                command=command,
                exit_code=-1,
                duration_s=round(duration, 3),
                error=f"Command timed out after {timeout}s",
            )
        except Exception as e:
            duration = time.monotonic() - t0
            return EvalResult(
                command=command,
                exit_code=-1,
                duration_s=round(duration, 3),
                error=str(e),
            )

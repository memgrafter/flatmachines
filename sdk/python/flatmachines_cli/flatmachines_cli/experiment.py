"""
Experiment tracking for self-improvement loops.

Standalone experiment tracker inspired by experiment-loop patterns but
fully self-contained — no external dependencies required.
Designed to be used by the self-improvement FlatMachine config or
programmatically.

Core concepts:
- ExperimentTracker: manages experiment lifecycle (init → run → log → archive)
- ExperimentResult: immutable record of a single experiment run
- Metrics: structured METRIC line parsing from command output
- Archive: append-only JSONL file for experiment history

Usage:
    tracker = ExperimentTracker(
        name="optimize-something",
        metric_name="score",
        direction="higher",  # or "lower"
        log_path="experiments.jsonl",
    )

    # Run an experiment
    result = tracker.run_command("pytest tests/ -q")

    # Log the result
    tracker.log_result(
        result=result,
        status="keep",  # or "discard", "crash"
        description="Added caching to hot path",
        tags=["performance"],
    )

    # Query history
    best = tracker.best_result()
    history = tracker.history
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence


@dataclass
class ExperimentResult:
    """Immutable record of a single experiment run."""

    command: str
    exit_code: int
    stdout: str
    stderr: str
    duration_s: float
    metrics: Dict[str, float] = field(default_factory=dict)
    success: bool = False
    error: Optional[str] = None
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@dataclass
class ExperimentEntry:
    """A logged experiment with result + metadata."""

    experiment_id: int
    description: str
    status: str  # "keep" | "discard" | "crash"
    result: ExperimentResult
    primary_metric: float
    tags: List[str] = field(default_factory=list)
    notes: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# Regex for METRIC lines: "METRIC name=value" or "METRIC name = value"
_METRIC_RE = re.compile(
    r"^\s*METRIC\s+(\w[\w.]*)\s*=\s*([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\s*$",
    re.MULTILINE,
)


def parse_metrics(output: str) -> Dict[str, float]:
    """Parse structured METRIC lines from command output.

    Expected format (one per line):
        METRIC name=value
        METRIC name = value

    Returns dict of {name: float_value}.
    """
    metrics = {}
    for match in _METRIC_RE.finditer(output):
        name = match.group(1)
        value = float(match.group(2))
        metrics[name] = value
    return metrics


class ExperimentTracker:
    """
    Manages the experiment lifecycle: initialize, run, log, archive.

    Thread-safe for single-threaded use. Not designed for concurrent
    writers — use one tracker per improvement loop.
    """

    def __init__(
        self,
        name: str = "experiment",
        metric_name: str = "score",
        direction: str = "higher",
        log_path: Optional[str] = None,
        working_dir: Optional[str] = None,
        git_enabled: bool = False,
    ):
        """
        Args:
            name: Human-readable session name.
            metric_name: Primary metric to optimize.
            direction: "higher" or "lower" — which direction is better.
            log_path: Path to JSONL log file. Default: experiments.jsonl
            working_dir: Directory for running commands. Default: cwd.
            git_enabled: If True, auto-commit on keep and auto-revert on discard.
        """
        self._name = name
        self._metric_name = metric_name
        self._direction = direction
        self._log_path = Path(log_path or "experiments.jsonl")
        self._working_dir = working_dir or os.getcwd()
        self._history: List[ExperimentEntry] = []
        self._next_id = 1
        self._initialized = False
        self._baseline: Optional[float] = None
        self._git_enabled = git_enabled
        self._load_errors: int = 0

    def initialize(self) -> None:
        """Initialize the experiment session.

        Writes a config header to the log file and loads any existing
        history from a previous session.
        """
        # Load existing history if log file exists
        if self._log_path.exists():
            self._load_history()

        # Write config header
        config = {
            "type": "config",
            "name": self._name,
            "metric_name": self._metric_name,
            "direction": self._direction,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        self._append_log(config)
        self._initialized = True

    # Alias for convenience
    init = initialize

    @property
    def name(self) -> str:
        return self._name

    @property
    def metric_name(self) -> str:
        return self._metric_name

    @property
    def direction(self) -> str:
        return self._direction

    @property
    def history(self) -> List[ExperimentEntry]:
        """All logged experiments (read-only copy)."""
        return list(self._history)

    @property
    def experiments(self) -> List[ExperimentEntry]:
        """Alias for history."""
        return self.history

    @property
    def results(self) -> List[ExperimentResult]:
        """Just the results from all experiments."""
        return [e.result for e in self._history]

    def run_command(
        self,
        command: str,
        timeout: float = 600.0,
        env: Optional[Dict[str, str]] = None,
    ) -> ExperimentResult:
        """Run a command and capture its output, timing, and metrics.

        Args:
            command: Shell command to run.
            timeout: Maximum execution time in seconds.
            env: Additional environment variables (merged with os.environ).

        Returns:
            ExperimentResult with parsed metrics, timing, exit code.
        """
        run_env = dict(os.environ)
        if env:
            run_env.update(env)

        t0 = time.monotonic()
        try:
            proc = subprocess.run(
                ["bash", "-c", command],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=self._working_dir,
                env=run_env,
            )
            duration = time.monotonic() - t0
            combined_output = proc.stdout + "\n" + proc.stderr
            metrics = parse_metrics(combined_output)

            return ExperimentResult(
                command=command,
                exit_code=proc.returncode,
                stdout=proc.stdout,
                stderr=proc.stderr,
                duration_s=round(duration, 3),
                metrics=metrics,
                success=proc.returncode == 0,
            )
        except subprocess.TimeoutExpired:
            duration = time.monotonic() - t0
            return ExperimentResult(
                command=command,
                exit_code=-1,
                stdout="",
                stderr="",
                duration_s=round(duration, 3),
                success=False,
                error=f"Command timed out after {timeout}s",
            )
        except Exception as e:
            duration = time.monotonic() - t0
            return ExperimentResult(
                command=command,
                exit_code=-1,
                stdout="",
                stderr="",
                duration_s=round(duration, 3),
                success=False,
                error=str(e),
            )

    # Alias for convenience
    run = run_command

    def log_result(
        self,
        result: ExperimentResult,
        status: str = "discard",
        description: str = "",
        tags: Optional[List[str]] = None,
        notes: Optional[Dict[str, Any]] = None,
        primary_metric: Optional[float] = None,
    ) -> ExperimentEntry:
        """Log an experiment result.

        Args:
            result: The ExperimentResult from run_command().
            status: "keep" (improved), "discard" (no improvement), "crash" (failed).
            description: What this experiment tried.
            tags: Optional categorization tags.
            notes: Optional structured notes (like ASI in autoresearch).
            primary_metric: Override the primary metric value. If None,
                           looks for metric_name in result.metrics.

        Returns:
            The logged ExperimentEntry.
        """
        # Determine primary metric value
        if primary_metric is not None:
            metric_val = primary_metric
        elif self._metric_name in result.metrics:
            metric_val = result.metrics[self._metric_name]
        else:
            metric_val = 0.0

        entry = ExperimentEntry(
            experiment_id=self._next_id,
            description=description,
            status=status,
            result=result,
            primary_metric=metric_val,
            tags=tags or [],
            notes=notes or {},
        )

        self._history.append(entry)
        self._next_id += 1

        # Set baseline from first kept result
        if self._baseline is None and status == "keep":
            self._baseline = metric_val

        # Persist to JSONL
        self._append_log({
            "type": "experiment",
            **self._entry_to_dict(entry),
        })

        # Git integration: auto-commit on keep, auto-revert on discard
        if self._git_enabled:
            if status == "keep":
                self.git_commit(description or f"Experiment #{entry.experiment_id}")
            elif status in ("discard", "crash"):
                self.git_revert()

        return entry

    # Alias for convenience
    log = log_result

    def is_improved(self, metric_value: float) -> bool:
        """Check if a metric value represents an improvement over best.

        Uses the configured direction (higher/lower is better).
        """
        best = self.best_metric()
        if best is None:
            return True  # First result is always an improvement

        if self._direction == "higher":
            return metric_value > best
        else:
            return metric_value < best

    def best_result(self) -> Optional[ExperimentEntry]:
        """Return the best experiment entry (by primary metric)."""
        kept = [e for e in self._history if e.status == "keep"]
        if not kept:
            return None

        if self._direction == "higher":
            return max(kept, key=lambda e: e.primary_metric)
        else:
            return min(kept, key=lambda e: e.primary_metric)

    def best_metric(self) -> Optional[float]:
        """Return the best primary metric value, or None if no kept results."""
        best = self.best_result()
        return best.primary_metric if best else None

    def summary(self) -> Dict[str, Any]:
        """Return a summary of the experiment session."""
        kept = [e for e in self._history if e.status == "keep"]
        discarded = [e for e in self._history if e.status == "discard"]
        crashed = [e for e in self._history if e.status == "crash"]

        return {
            "name": self._name,
            "metric_name": self._metric_name,
            "direction": self._direction,
            "total_experiments": len(self._history),
            "kept": len(kept),
            "discarded": len(discarded),
            "crashed": len(crashed),
            "best_metric": self.best_metric(),
            "baseline": self._baseline,
        }

    def noise_floor(self, window: int = 5) -> Optional[float]:
        """Estimate the noise floor from recent kept results.

        Returns the standard deviation of the last `window` kept
        metric values, or None if not enough data.
        """
        kept = [e.primary_metric for e in self._history if e.status == "keep"]
        if len(kept) < 3:
            return None

        recent = kept[-window:]
        mean = sum(recent) / len(recent)
        variance = sum((x - mean) ** 2 for x in recent) / len(recent)
        return variance ** 0.5

    def confidence_score(self) -> Optional[float]:
        """Calculate confidence that the best improvement is real.

        Returns the best improvement as a multiple of the noise floor.
        - >= 2.0: improvement is likely real
        - 1.0 - 2.0: borderline, consider re-running
        - < 1.0: within noise, likely not a real improvement
        - None: not enough data (need >= 3 kept results)

        Compares the best kept result against the baseline (first kept).
        """
        kept = [e.primary_metric for e in self._history if e.status == "keep"]
        if len(kept) < 3:
            return None

        nf = self.noise_floor()
        if nf is None or nf == 0:
            # No noise → if there's any improvement, it's infinite confidence
            if len(kept) >= 2 and kept[-1] != kept[0]:
                return float("inf")
            return None

        best = self.best_metric()
        baseline = self._baseline
        if best is None or baseline is None:
            return None

        if self._direction == "higher":
            improvement = best - baseline
        else:
            improvement = baseline - best

        if improvement <= 0:
            return 0.0

        return improvement / nf

    # Alias
    confidence = confidence_score

    # --- Convenience accessors ---

    def best(self) -> Optional[ExperimentEntry]:
        """Convenience alias for best_result()."""
        return self.best_result()

    def worst_result(self) -> Optional[ExperimentEntry]:
        """Return the worst kept experiment entry (by primary metric)."""
        kept = [e for e in self._history if e.status == "keep"]
        if not kept:
            return None
        if self._direction == "higher":
            return min(kept, key=lambda e: e.primary_metric)
        else:
            return max(kept, key=lambda e: e.primary_metric)

    def diff(
        self,
        entry1: ExperimentEntry,
        entry2: ExperimentEntry,
    ) -> Dict[str, Any]:
        """Compare two experiment entries and return differences.

        Returns dict with:
            metric_delta: change in primary metric
            metric_pct: percentage change
            duration_delta: change in duration
            status_change: (status1, status2)
            improved: bool — whether entry2 is better than entry1
        """
        delta = entry2.primary_metric - entry1.primary_metric
        if entry1.primary_metric != 0:
            pct = (delta / abs(entry1.primary_metric)) * 100
        else:
            pct = float("inf") if delta != 0 else 0.0

        dur_delta = entry2.result.duration_s - entry1.result.duration_s

        if self._direction == "higher":
            improved = entry2.primary_metric > entry1.primary_metric
        else:
            improved = entry2.primary_metric < entry1.primary_metric

        # Compare all metrics
        all_metrics_1 = entry1.result.metrics
        all_metrics_2 = entry2.result.metrics
        metric_diffs = {}
        for key in set(all_metrics_1) | set(all_metrics_2):
            v1 = all_metrics_1.get(key, 0)
            v2 = all_metrics_2.get(key, 0)
            if v1 != v2:
                metric_diffs[key] = {"from": v1, "to": v2, "delta": v2 - v1}

        return {
            "metric_delta": delta,
            "metric_pct": round(pct, 2),
            "duration_delta": round(dur_delta, 3),
            "status_change": (entry1.status, entry2.status),
            "improved": improved,
            "metric_diffs": metric_diffs,
            "entry1_id": entry1.experiment_id,
            "entry2_id": entry2.experiment_id,
        }

    def export_csv(self, path: Optional[str] = None) -> str:
        """Export experiment history to CSV format.

        Args:
            path: If provided, write CSV to this file.

        Returns:
            CSV string.
        """
        import csv
        import io

        buf = io.StringIO()
        writer = csv.writer(buf)

        # Header
        writer.writerow([
            "id", "description", "status", "primary_metric",
            "duration_s", "success", "tags", "timestamp",
        ])

        for entry in self._history:
            writer.writerow([
                entry.experiment_id,
                entry.description,
                entry.status,
                entry.primary_metric,
                entry.result.duration_s,
                entry.result.success,
                ";".join(entry.tags),
                entry.timestamp,
            ])

        csv_str = buf.getvalue()

        if path:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text(csv_str)

        return csv_str

    def export_markdown(self, path: Optional[str] = None) -> str:
        """Export experiment history as a Markdown summary.

        Args:
            path: If provided, write markdown to this file.

        Returns:
            Markdown string.
        """
        s = self.summary()
        lines = []
        lines.append(f"# {s['name']}")
        lines.append("")
        lines.append(f"**Metric**: {s['metric_name']} ({s['direction']} is better)")
        lines.append(f"**Total experiments**: {s['total_experiments']}")
        lines.append(f"**Kept**: {s['kept']} | **Discarded**: {s['discarded']} | **Crashed**: {s['crashed']}")
        if s['best_metric'] is not None:
            lines.append(f"**Best**: {s['best_metric']}")
        if s.get('baseline') is not None:
            lines.append(f"**Baseline**: {s['baseline']}")
        lines.append("")

        # Confidence
        conf = self.confidence_score()
        if conf is not None:
            lines.append(f"**Confidence**: {conf:.1f}× noise floor")
            lines.append("")

        # History table
        if self._history:
            lines.append("## Experiment History")
            lines.append("")
            lines.append("| # | Status | Metric | Duration | Description |")
            lines.append("|---|--------|--------|----------|-------------|")
            for entry in self._history:
                desc = entry.description[:50] if entry.description else ""
                lines.append(
                    f"| {entry.experiment_id} "
                    f"| {entry.status} "
                    f"| {entry.primary_metric:.1f} "
                    f"| {entry.result.duration_s:.1f}s "
                    f"| {desc} |"
                )
            lines.append("")

        md = "\n".join(lines)

        if path:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text(md)

        return md

    def rollback_to(self, experiment_id: int) -> bool:
        """Attempt to rollback to the state after a specific experiment.

        Uses git log to find the commit for the given experiment_id,
        then resets to that commit.

        Args:
            experiment_id: The experiment ID to rollback to.

        Returns:
            True if rollback succeeded, False otherwise.
        """
        # Find the entry
        target = None
        for e in self._history:
            if e.experiment_id == experiment_id:
                target = e
                break

        if target is None:
            return False

        if not self._git_enabled:
            return False

        # Find the commit for this experiment by searching git log
        # Convention: commit message contains "Experiment #N" or the description
        try:
            result = subprocess.run(
                ["git", "log", "--oneline", "--all"],
                cwd=self._working_dir,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                return False

            # Look for a commit mentioning this experiment
            target_hash = None
            for line in result.stdout.strip().split("\n"):
                if f"#{experiment_id}" in line or (
                    target.description and target.description[:40] in line
                ):
                    target_hash = line.split()[0]
                    break

            if target_hash is None:
                return False

            # Hard reset to that commit
            reset = subprocess.run(
                ["git", "reset", "--hard", target_hash],
                cwd=self._working_dir,
                capture_output=True,
            )
            return reset.returncode == 0
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False

    def get_entry(self, experiment_id: int) -> Optional[ExperimentEntry]:
        """Get an experiment entry by ID."""
        for e in self._history:
            if e.experiment_id == experiment_id:
                return e
        return None

    def kept_entries(self) -> List[ExperimentEntry]:
        """Return all kept experiments."""
        return [e for e in self._history if e.status == "keep"]

    def discarded_entries(self) -> List[ExperimentEntry]:
        """Return all discarded experiments."""
        return [e for e in self._history if e.status == "discard"]

    # --- Git operations ---

    def git_commit(self, message: str = "experiment") -> bool:
        """Stage all changes and commit.

        Args:
            message: Commit message.

        Returns:
            True if commit succeeded, False otherwise.
        """
        try:
            # Stage all changes
            subprocess.run(
                ["git", "add", "-A"],
                cwd=self._working_dir,
                capture_output=True,
                check=True,
            )
            # Commit
            result = subprocess.run(
                ["git", "commit", "-m", message, "--allow-empty"],
                cwd=self._working_dir,
                capture_output=True,
                text=True,
            )
            return result.returncode == 0
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False

    def git_revert(self) -> bool:
        """Revert all uncommitted changes (git checkout + clean).

        Returns:
            True if revert succeeded, False otherwise.
        """
        try:
            # Reset staged changes
            subprocess.run(
                ["git", "reset", "HEAD", "--"],
                cwd=self._working_dir,
                capture_output=True,
            )
            # Discard unstaged changes
            subprocess.run(
                ["git", "checkout", "--", "."],
                cwd=self._working_dir,
                capture_output=True,
                check=True,
            )
            # Clean untracked files
            subprocess.run(
                ["git", "clean", "-fd"],
                cwd=self._working_dir,
                capture_output=True,
            )
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False

    # Alias
    commit_changes = git_commit
    revert_changes = git_revert
    git_reset = git_revert

    # --- Persistence ---

    def _append_log(self, data: Dict[str, Any]) -> None:
        """Append a JSON line to the log file."""
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._log_path, "a") as f:
            f.write(json.dumps(data, default=str) + "\n")

    @property
    def load_errors(self) -> int:
        """Number of corrupted/skipped lines during last load."""
        return self._load_errors

    @property
    def git_enabled(self) -> bool:
        """Whether git integration is active."""
        return self._git_enabled

    def _load_history(self) -> None:
        """Load experiment history from the JSONL log file.

        Gracefully handles corrupted lines — they are skipped and
        counted in load_errors for diagnostics.
        """
        if not self._log_path.exists():
            return

        self._load_errors = 0
        max_id = 0
        for line in self._log_path.read_text().strip().split("\n"):
            if not line.strip():
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                self._load_errors += 1
                continue

            if data.get("type") == "config":
                continue  # Skip config headers

            if data.get("type") == "experiment":
                entry = self._dict_to_entry(data)
                if entry:
                    self._history.append(entry)
                    max_id = max(max_id, entry.experiment_id)
                else:
                    self._load_errors += 1

        self._next_id = max_id + 1

        # Restore baseline from first kept result
        for e in self._history:
            if e.status == "keep":
                self._baseline = e.primary_metric
                break

    def load(self) -> None:
        """Load history from the log file (alias for resume)."""
        self._load_history()

    def load_history(self) -> None:
        """Load history from the log file (alias)."""
        self._load_history()

    @classmethod
    def from_file(cls, path: str) -> "ExperimentTracker":
        """Create a tracker by loading from an existing log file.

        Reads the config header to restore name/metric/direction,
        then loads all experiment entries.
        """
        log_path = Path(path)
        if not log_path.exists():
            raise FileNotFoundError(f"Log file not found: {path}")

        # Read config from first config line
        name = "experiment"
        metric_name = "score"
        direction = "higher"

        for line in log_path.read_text().strip().split("\n"):
            if not line.strip():
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if data.get("type") == "config":
                name = data.get("name", name)
                metric_name = data.get("metric_name", metric_name)
                direction = data.get("direction", direction)
                break

        tracker = cls(
            name=name,
            metric_name=metric_name,
            direction=direction,
            log_path=path,
        )
        tracker._load_history()
        return tracker

    # --- Serialization helpers ---

    @staticmethod
    def _entry_to_dict(entry: ExperimentEntry) -> Dict[str, Any]:
        """Convert an ExperimentEntry to a serializable dict."""
        return {
            "experiment_id": entry.experiment_id,
            "description": entry.description,
            "status": entry.status,
            "primary_metric": entry.primary_metric,
            "tags": entry.tags,
            "notes": entry.notes,
            "timestamp": entry.timestamp,
            "result": {
                "command": entry.result.command,
                "exit_code": entry.result.exit_code,
                "duration_s": entry.result.duration_s,
                "metrics": entry.result.metrics,
                "success": entry.result.success,
                "error": entry.result.error,
                "timestamp": entry.result.timestamp,
                # stdout/stderr omitted for log size — too large
            },
        }

    @staticmethod
    def _dict_to_entry(data: Dict[str, Any]) -> Optional[ExperimentEntry]:
        """Convert a dict back to an ExperimentEntry."""
        try:
            result_data = data.get("result", {})
            result = ExperimentResult(
                command=result_data.get("command", ""),
                exit_code=result_data.get("exit_code", -1),
                stdout="",  # Not stored in log
                stderr="",  # Not stored in log
                duration_s=result_data.get("duration_s", 0.0),
                metrics=result_data.get("metrics", {}),
                success=result_data.get("success", False),
                error=result_data.get("error"),
                timestamp=result_data.get("timestamp", ""),
            )
            return ExperimentEntry(
                experiment_id=data.get("experiment_id", 0),
                description=data.get("description", ""),
                status=data.get("status", "discard"),
                result=result,
                primary_metric=data.get("primary_metric", 0.0),
                tags=data.get("tags", []),
                notes=data.get("notes", {}),
                timestamp=data.get("timestamp", ""),
            )
        except Exception:
            return None

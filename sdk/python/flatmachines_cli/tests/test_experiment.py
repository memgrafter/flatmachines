"""Tests for the experiment tracking module."""

import json
import os
import tempfile
from pathlib import Path

import pytest

from flatmachines_cli.experiment import (
    ExperimentTracker,
    ExperimentResult,
    ExperimentEntry,
    parse_metrics,
)


# --- parse_metrics ---

class TestParseMetrics:
    def test_basic_metric(self):
        output = "METRIC score=42"
        assert parse_metrics(output) == {"score": 42.0}

    def test_multiple_metrics(self):
        output = "METRIC score=42\nMETRIC duration=1.5\nMETRIC errors=0"
        result = parse_metrics(output)
        assert result == {"score": 42.0, "duration": 1.5, "errors": 0.0}

    def test_metric_with_spaces(self):
        output = "METRIC score = 42"
        assert parse_metrics(output) == {"score": 42.0}

    def test_metric_with_float(self):
        output = "METRIC accuracy=0.95"
        assert parse_metrics(output) == {"accuracy": 0.95}

    def test_metric_with_scientific_notation(self):
        output = "METRIC loss=1.5e-3"
        assert parse_metrics(output) == {"loss": 0.0015}

    def test_metric_negative(self):
        output = "METRIC delta=-5.2"
        assert parse_metrics(output) == {"delta": -5.2}

    def test_metric_in_noisy_output(self):
        output = "Running tests...\nAll passed!\nMETRIC score=95\nDone."
        assert parse_metrics(output) == {"score": 95.0}

    def test_no_metrics(self):
        output = "Hello world\nNo metrics here"
        assert parse_metrics(output) == {}

    def test_metric_dotted_name(self):
        output = "METRIC eval.accuracy=0.87"
        assert parse_metrics(output) == {"eval.accuracy": 0.87}

    def test_empty_output(self):
        assert parse_metrics("") == {}

    def test_metric_with_leading_whitespace(self):
        output = "  METRIC score=42"
        assert parse_metrics(output) == {"score": 42.0}


# --- ExperimentResult ---

class TestExperimentResult:
    def test_basic_creation(self):
        r = ExperimentResult(
            command="echo test",
            exit_code=0,
            stdout="test\n",
            stderr="",
            duration_s=0.1,
            success=True,
        )
        assert r.command == "echo test"
        assert r.success is True
        assert r.timestamp  # auto-generated

    def test_with_metrics(self):
        r = ExperimentResult(
            command="test",
            exit_code=0,
            stdout="",
            stderr="",
            duration_s=1.0,
            metrics={"score": 42.0},
        )
        assert r.metrics["score"] == 42.0

    def test_error_result(self):
        r = ExperimentResult(
            command="fail",
            exit_code=1,
            stdout="",
            stderr="error!",
            duration_s=0.5,
            error="command failed",
        )
        assert r.success is False
        assert r.error == "command failed"


# --- ExperimentEntry ---

class TestExperimentEntry:
    def test_basic_creation(self):
        result = ExperimentResult(
            command="test", exit_code=0, stdout="", stderr="",
            duration_s=1.0, success=True,
        )
        entry = ExperimentEntry(
            experiment_id=1,
            description="test run",
            status="keep",
            result=result,
            primary_metric=42.0,
        )
        assert entry.experiment_id == 1
        assert entry.status == "keep"
        assert entry.primary_metric == 42.0
        assert entry.timestamp  # auto-generated


# --- ExperimentTracker ---

class TestExperimentTracker:
    def test_init(self, tmp_path):
        tracker = ExperimentTracker(
            name="test",
            metric_name="score",
            direction="higher",
            log_path=str(tmp_path / "log.jsonl"),
        )
        assert tracker.name == "test"
        assert tracker.metric_name == "score"
        assert tracker.direction == "higher"

    def test_initialize_creates_log(self, tmp_path):
        log_path = tmp_path / "log.jsonl"
        tracker = ExperimentTracker(
            name="test",
            log_path=str(log_path),
        )
        tracker.initialize()
        assert log_path.exists()
        data = json.loads(log_path.read_text().strip())
        assert data["type"] == "config"
        assert data["name"] == "test"

    def test_init_alias(self, tmp_path):
        tracker = ExperimentTracker(log_path=str(tmp_path / "log.jsonl"))
        tracker.init()  # alias
        assert (tmp_path / "log.jsonl").exists()

    def test_run_command_echo(self, tmp_path):
        tracker = ExperimentTracker(
            log_path=str(tmp_path / "log.jsonl"),
            working_dir=str(tmp_path),
        )
        result = tracker.run_command("echo 'METRIC score=42'")
        assert result.success is True
        assert result.exit_code == 0
        assert result.metrics == {"score": 42.0}
        assert result.duration_s > 0

    def test_run_alias(self, tmp_path):
        tracker = ExperimentTracker(
            log_path=str(tmp_path / "log.jsonl"),
            working_dir=str(tmp_path),
        )
        result = tracker.run("echo hello")
        assert result.success is True

    def test_run_command_failure(self, tmp_path):
        tracker = ExperimentTracker(
            log_path=str(tmp_path / "log.jsonl"),
            working_dir=str(tmp_path),
        )
        result = tracker.run_command("exit 1")
        assert result.success is False
        assert result.exit_code == 1

    def test_run_command_timeout(self, tmp_path):
        tracker = ExperimentTracker(
            log_path=str(tmp_path / "log.jsonl"),
            working_dir=str(tmp_path),
        )
        result = tracker.run_command("sleep 10", timeout=0.5)
        assert result.success is False
        assert "timed out" in result.error

    def test_log_result(self, tmp_path):
        log_path = tmp_path / "log.jsonl"
        tracker = ExperimentTracker(
            log_path=str(log_path),
        )
        tracker.initialize()

        result = ExperimentResult(
            command="test", exit_code=0, stdout="", stderr="",
            duration_s=1.0, metrics={"score": 42.0}, success=True,
        )
        entry = tracker.log_result(
            result=result,
            status="keep",
            description="first run",
        )

        assert entry.experiment_id == 1
        assert entry.status == "keep"
        assert entry.primary_metric == 42.0
        assert len(tracker.history) == 1

    def test_log_alias(self, tmp_path):
        tracker = ExperimentTracker(log_path=str(tmp_path / "log.jsonl"))
        tracker.init()
        result = ExperimentResult(
            command="test", exit_code=0, stdout="", stderr="",
            duration_s=1.0, success=True,
        )
        entry = tracker.log(result=result, status="discard", description="test")
        assert entry.status == "discard"

    def test_is_improved_higher(self, tmp_path):
        tracker = ExperimentTracker(
            direction="higher",
            log_path=str(tmp_path / "log.jsonl"),
        )
        tracker.init()

        result = ExperimentResult(
            command="test", exit_code=0, stdout="", stderr="",
            duration_s=1.0, metrics={"score": 10.0}, success=True,
        )
        tracker.log(result=result, status="keep", primary_metric=10.0)

        assert tracker.is_improved(15.0) is True
        assert tracker.is_improved(5.0) is False
        assert tracker.is_improved(10.0) is False

    def test_is_improved_lower(self, tmp_path):
        tracker = ExperimentTracker(
            direction="lower",
            log_path=str(tmp_path / "log.jsonl"),
        )
        tracker.init()

        result = ExperimentResult(
            command="test", exit_code=0, stdout="", stderr="",
            duration_s=1.0, metrics={"score": 10.0}, success=True,
        )
        tracker.log(result=result, status="keep", primary_metric=10.0)

        assert tracker.is_improved(5.0) is True
        assert tracker.is_improved(15.0) is False

    def test_best_result(self, tmp_path):
        tracker = ExperimentTracker(
            direction="higher",
            log_path=str(tmp_path / "log.jsonl"),
        )
        tracker.init()

        for score in [10.0, 20.0, 15.0]:
            result = ExperimentResult(
                command="test", exit_code=0, stdout="", stderr="",
                duration_s=1.0, success=True,
            )
            tracker.log(result=result, status="keep", primary_metric=score)

        best = tracker.best_result()
        assert best is not None
        assert best.primary_metric == 20.0

    def test_best_result_lower(self, tmp_path):
        tracker = ExperimentTracker(
            direction="lower",
            log_path=str(tmp_path / "log.jsonl"),
        )
        tracker.init()

        for score in [10.0, 5.0, 15.0]:
            result = ExperimentResult(
                command="test", exit_code=0, stdout="", stderr="",
                duration_s=1.0, success=True,
            )
            tracker.log(result=result, status="keep", primary_metric=score)

        assert tracker.best_metric() == 5.0

    def test_summary(self, tmp_path):
        tracker = ExperimentTracker(
            name="test-session",
            metric_name="accuracy",
            direction="higher",
            log_path=str(tmp_path / "log.jsonl"),
        )
        tracker.init()

        result = ExperimentResult(
            command="test", exit_code=0, stdout="", stderr="",
            duration_s=1.0, success=True,
        )
        tracker.log(result=result, status="keep", primary_metric=0.8)
        tracker.log(result=result, status="discard", primary_metric=0.7)
        tracker.log(result=result, status="crash", primary_metric=0.0)

        summary = tracker.summary()
        assert summary["name"] == "test-session"
        assert summary["total_experiments"] == 3
        assert summary["kept"] == 1
        assert summary["discarded"] == 1
        assert summary["crashed"] == 1
        assert summary["best_metric"] == 0.8

    def test_history_property(self, tmp_path):
        tracker = ExperimentTracker(log_path=str(tmp_path / "log.jsonl"))
        tracker.init()
        assert tracker.history == []
        assert tracker.experiments == []
        assert tracker.results == []

    def test_noise_floor_insufficient_data(self, tmp_path):
        tracker = ExperimentTracker(log_path=str(tmp_path / "log.jsonl"))
        tracker.init()
        assert tracker.noise_floor() is None

    def test_noise_floor(self, tmp_path):
        tracker = ExperimentTracker(
            direction="higher",
            log_path=str(tmp_path / "log.jsonl"),
        )
        tracker.init()

        for score in [10.0, 10.0, 10.0, 10.0, 10.0]:
            result = ExperimentResult(
                command="test", exit_code=0, stdout="", stderr="",
                duration_s=1.0, success=True,
            )
            tracker.log(result=result, status="keep", primary_metric=score)

        # All same → noise floor = 0
        assert tracker.noise_floor() == 0.0


# --- Persistence ---

class TestExperimentPersistence:
    def test_save_and_load(self, tmp_path):
        log_path = str(tmp_path / "log.jsonl")

        # Create and populate tracker
        t1 = ExperimentTracker(
            name="persist-test",
            metric_name="score",
            direction="higher",
            log_path=log_path,
        )
        t1.init()

        result = ExperimentResult(
            command="test", exit_code=0, stdout="", stderr="",
            duration_s=1.0, metrics={"score": 42.0}, success=True,
        )
        t1.log(result=result, status="keep", description="first")
        t1.log(result=result, status="discard", description="second")

        # Load from file
        t2 = ExperimentTracker.from_file(log_path)
        assert t2.name == "persist-test"
        assert t2.metric_name == "score"
        assert t2.direction == "higher"
        assert len(t2.history) == 2
        assert t2.history[0].description == "first"
        assert t2.history[0].status == "keep"
        assert t2.history[1].description == "second"

    def test_from_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            ExperimentTracker.from_file("/nonexistent/path.jsonl")

    def test_load_aliases(self, tmp_path):
        log_path = str(tmp_path / "log.jsonl")
        tracker = ExperimentTracker(log_path=log_path)
        tracker.init()
        # Both load methods should work without error
        tracker.load()
        tracker.load_history()

    def test_resume_id_counter(self, tmp_path):
        log_path = str(tmp_path / "log.jsonl")

        t1 = ExperimentTracker(log_path=log_path)
        t1.init()
        result = ExperimentResult(
            command="test", exit_code=0, stdout="", stderr="",
            duration_s=1.0, success=True,
        )
        t1.log(result=result, status="keep", description="run 1")
        t1.log(result=result, status="keep", description="run 2")

        # Resume — next ID should be 3
        t2 = ExperimentTracker.from_file(log_path)
        entry = t2.log(result=result, status="keep", description="run 3")
        assert entry.experiment_id == 3

    def test_tags_and_notes_persist(self, tmp_path):
        log_path = str(tmp_path / "log.jsonl")
        t1 = ExperimentTracker(log_path=log_path)
        t1.init()

        result = ExperimentResult(
            command="test", exit_code=0, stdout="", stderr="",
            duration_s=1.0, success=True,
        )
        t1.log(
            result=result,
            status="keep",
            tags=["perf", "cache"],
            notes={"hypothesis": "caching helps"},
        )

        t2 = ExperimentTracker.from_file(log_path)
        assert t2.history[0].tags == ["perf", "cache"]
        assert t2.history[0].notes == {"hypothesis": "caching helps"}

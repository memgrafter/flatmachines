"""Tests for ExperimentTracker enhancements: best(), diff(), export_csv(), etc."""

import os
import tempfile
from pathlib import Path

import pytest

from flatmachines_cli.experiment import ExperimentTracker, ExperimentResult


def _make_result(metrics=None, duration=1.0, success=True):
    """Create a test ExperimentResult."""
    return ExperimentResult(
        command="test",
        exit_code=0 if success else 1,
        stdout="",
        stderr="",
        duration_s=duration,
        metrics=metrics or {},
        success=success,
    )


class TestBestAndWorst:
    """Test best() and worst_result()."""

    def test_best_alias(self, tmp_path):
        t = ExperimentTracker(direction="higher", log_path=str(tmp_path / "log.jsonl"))
        t.init()
        r = _make_result()
        t.log(result=r, status="keep", primary_metric=50.0)
        t.log(result=r, status="keep", primary_metric=100.0)
        t.log(result=r, status="keep", primary_metric=75.0)
        assert t.best().primary_metric == 100.0

    def test_best_lower_direction(self, tmp_path):
        t = ExperimentTracker(direction="lower", log_path=str(tmp_path / "log.jsonl"))
        t.init()
        r = _make_result()
        t.log(result=r, status="keep", primary_metric=50.0)
        t.log(result=r, status="keep", primary_metric=100.0)
        t.log(result=r, status="keep", primary_metric=75.0)
        assert t.best().primary_metric == 50.0

    def test_worst_result_higher(self, tmp_path):
        t = ExperimentTracker(direction="higher", log_path=str(tmp_path / "log.jsonl"))
        t.init()
        r = _make_result()
        t.log(result=r, status="keep", primary_metric=50.0)
        t.log(result=r, status="keep", primary_metric=100.0)
        t.log(result=r, status="keep", primary_metric=75.0)
        assert t.worst_result().primary_metric == 50.0

    def test_worst_result_lower(self, tmp_path):
        t = ExperimentTracker(direction="lower", log_path=str(tmp_path / "log.jsonl"))
        t.init()
        r = _make_result()
        t.log(result=r, status="keep", primary_metric=50.0)
        t.log(result=r, status="keep", primary_metric=100.0)
        assert t.worst_result().primary_metric == 100.0

    def test_best_empty(self, tmp_path):
        t = ExperimentTracker(log_path=str(tmp_path / "log.jsonl"))
        t.init()
        assert t.best() is None

    def test_worst_empty(self, tmp_path):
        t = ExperimentTracker(log_path=str(tmp_path / "log.jsonl"))
        t.init()
        assert t.worst_result() is None

    def test_best_ignores_discarded(self, tmp_path):
        t = ExperimentTracker(direction="higher", log_path=str(tmp_path / "log.jsonl"))
        t.init()
        r = _make_result()
        t.log(result=r, status="discard", primary_metric=999.0)
        t.log(result=r, status="keep", primary_metric=50.0)
        assert t.best().primary_metric == 50.0


class TestDiff:
    """Test diff() comparison."""

    def test_basic_diff(self, tmp_path):
        t = ExperimentTracker(direction="higher", log_path=str(tmp_path / "log.jsonl"))
        t.init()
        r1 = _make_result(duration=1.0)
        r2 = _make_result(duration=2.0)
        e1 = t.log(result=r1, status="keep", primary_metric=100.0)
        e2 = t.log(result=r2, status="keep", primary_metric=150.0)

        d = t.diff(e1, e2)
        assert d["metric_delta"] == 50.0
        assert d["metric_pct"] == 50.0
        assert d["duration_delta"] == 1.0
        assert d["improved"] is True
        assert d["entry1_id"] == 1
        assert d["entry2_id"] == 2

    def test_diff_regression(self, tmp_path):
        t = ExperimentTracker(direction="higher", log_path=str(tmp_path / "log.jsonl"))
        t.init()
        r = _make_result()
        e1 = t.log(result=r, status="keep", primary_metric=100.0)
        e2 = t.log(result=r, status="keep", primary_metric=80.0)

        d = t.diff(e1, e2)
        assert d["metric_delta"] == -20.0
        assert d["improved"] is False

    def test_diff_lower_is_better(self, tmp_path):
        t = ExperimentTracker(direction="lower", log_path=str(tmp_path / "log.jsonl"))
        t.init()
        r = _make_result()
        e1 = t.log(result=r, status="keep", primary_metric=100.0)
        e2 = t.log(result=r, status="keep", primary_metric=80.0)

        d = t.diff(e1, e2)
        assert d["improved"] is True  # Lower is better

    def test_diff_metric_diffs(self, tmp_path):
        t = ExperimentTracker(direction="higher", log_path=str(tmp_path / "log.jsonl"))
        t.init()
        r1 = _make_result(metrics={"speed": 10.0, "memory": 200.0})
        r2 = _make_result(metrics={"speed": 15.0, "memory": 200.0})
        e1 = t.log(result=r1, status="keep", primary_metric=100.0)
        e2 = t.log(result=r2, status="keep", primary_metric=110.0)

        d = t.diff(e1, e2)
        assert "speed" in d["metric_diffs"]
        assert d["metric_diffs"]["speed"]["delta"] == 5.0
        assert "memory" not in d["metric_diffs"]  # Unchanged

    def test_diff_from_zero(self, tmp_path):
        t = ExperimentTracker(direction="higher", log_path=str(tmp_path / "log.jsonl"))
        t.init()
        r = _make_result()
        e1 = t.log(result=r, status="keep", primary_metric=0.0)
        e2 = t.log(result=r, status="keep", primary_metric=50.0)

        d = t.diff(e1, e2)
        assert d["metric_delta"] == 50.0
        assert d["metric_pct"] == float("inf")


class TestExportCSV:
    """Test export_csv()."""

    def test_export_csv_string(self, tmp_path):
        t = ExperimentTracker(log_path=str(tmp_path / "log.jsonl"))
        t.init()
        r = _make_result()
        t.log(result=r, status="keep", primary_metric=100.0, description="first")
        t.log(result=r, status="discard", primary_metric=90.0, description="second")

        csv = t.export_csv()
        lines = csv.strip().split("\n")
        assert len(lines) == 3  # header + 2 rows
        assert "id,description,status" in lines[0]
        assert "first" in lines[1]
        assert "second" in lines[2]

    def test_export_csv_to_file(self, tmp_path):
        t = ExperimentTracker(log_path=str(tmp_path / "log.jsonl"))
        t.init()
        r = _make_result()
        t.log(result=r, status="keep", primary_metric=100.0)

        csv_path = str(tmp_path / "export.csv")
        t.export_csv(path=csv_path)
        assert Path(csv_path).exists()
        content = Path(csv_path).read_text()
        assert "id,description,status" in content

    def test_export_csv_empty(self, tmp_path):
        t = ExperimentTracker(log_path=str(tmp_path / "log.jsonl"))
        t.init()
        csv = t.export_csv()
        lines = csv.strip().split("\n")
        assert len(lines) == 1  # header only

    def test_export_csv_tags(self, tmp_path):
        t = ExperimentTracker(log_path=str(tmp_path / "log.jsonl"))
        t.init()
        r = _make_result()
        t.log(result=r, status="keep", primary_metric=100.0, tags=["perf", "v2"])
        csv = t.export_csv()
        assert "perf;v2" in csv


class TestGetEntry:
    """Test get_entry() and filtering helpers."""

    def test_get_entry_by_id(self, tmp_path):
        t = ExperimentTracker(log_path=str(tmp_path / "log.jsonl"))
        t.init()
        r = _make_result()
        t.log(result=r, status="keep", primary_metric=100.0, description="first")
        t.log(result=r, status="discard", primary_metric=90.0, description="second")

        e = t.get_entry(1)
        assert e is not None
        assert e.description == "first"

        e = t.get_entry(2)
        assert e.description == "second"

    def test_get_entry_missing(self, tmp_path):
        t = ExperimentTracker(log_path=str(tmp_path / "log.jsonl"))
        t.init()
        assert t.get_entry(999) is None

    def test_kept_entries(self, tmp_path):
        t = ExperimentTracker(log_path=str(tmp_path / "log.jsonl"))
        t.init()
        r = _make_result()
        t.log(result=r, status="keep", primary_metric=100.0)
        t.log(result=r, status="discard", primary_metric=90.0)
        t.log(result=r, status="keep", primary_metric=110.0)
        t.log(result=r, status="crash", primary_metric=0.0)

        kept = t.kept_entries()
        assert len(kept) == 2
        assert all(e.status == "keep" for e in kept)

    def test_discarded_entries(self, tmp_path):
        t = ExperimentTracker(log_path=str(tmp_path / "log.jsonl"))
        t.init()
        r = _make_result()
        t.log(result=r, status="keep", primary_metric=100.0)
        t.log(result=r, status="discard", primary_metric=90.0)
        t.log(result=r, status="discard", primary_metric=80.0)

        discarded = t.discarded_entries()
        assert len(discarded) == 2
        assert all(e.status == "discard" for e in discarded)


class TestRollbackTo:
    """Test rollback_to() method."""

    def test_rollback_without_git_returns_false(self, tmp_path):
        t = ExperimentTracker(
            log_path=str(tmp_path / "log.jsonl"),
            git_enabled=False,
        )
        t.init()
        r = _make_result()
        t.log(result=r, status="keep", primary_metric=100.0)
        assert t.rollback_to(1) is False

    def test_rollback_missing_entry(self, tmp_path):
        t = ExperimentTracker(
            log_path=str(tmp_path / "log.jsonl"),
            git_enabled=True,
        )
        t.init()
        assert t.rollback_to(999) is False

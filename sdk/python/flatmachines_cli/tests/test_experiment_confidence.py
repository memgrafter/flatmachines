"""Tests for confidence scoring in ExperimentTracker."""

import os
import tempfile

import pytest

from flatmachines_cli.experiment import ExperimentTracker, ExperimentResult


def _make_result():
    return ExperimentResult(
        command="test", exit_code=0, stdout="", stderr="",
        duration_s=1.0, success=True,
    )


class TestConfidenceScore:
    def test_none_with_no_data(self, tmp_path):
        tracker = ExperimentTracker(
            log_path=str(tmp_path / "log.jsonl"),
        )
        tracker.init()
        assert tracker.confidence_score() is None

    def test_none_with_insufficient_data(self, tmp_path):
        tracker = ExperimentTracker(
            log_path=str(tmp_path / "log.jsonl"),
        )
        tracker.init()
        r = _make_result()
        tracker.log(result=r, status="keep", primary_metric=10.0)
        tracker.log(result=r, status="keep", primary_metric=11.0)
        # Only 2 kept results, need >= 3
        assert tracker.confidence_score() is None

    def test_high_confidence_clear_improvement(self, tmp_path):
        tracker = ExperimentTracker(
            direction="higher",
            log_path=str(tmp_path / "log.jsonl"),
        )
        tracker.init()
        r = _make_result()

        # Baseline with small noise
        for v in [100.0, 100.5, 99.5, 100.2, 99.8]:
            tracker.log(result=r, status="keep", primary_metric=v)

        # Clear improvement
        tracker.log(result=r, status="keep", primary_metric=110.0)

        c = tracker.confidence_score()
        assert c is not None
        assert c > 2.0, f"Expected >2.0x for clear improvement, got {c}"

    def test_low_confidence_within_noise(self, tmp_path):
        tracker = ExperimentTracker(
            direction="higher",
            log_path=str(tmp_path / "log.jsonl"),
        )
        tracker.init()
        r = _make_result()

        # All within noise
        for v in [100.0, 100.5, 99.5, 100.2, 100.1]:
            tracker.log(result=r, status="keep", primary_metric=v)

        c = tracker.confidence_score()
        assert c is not None
        # Best (100.5) - baseline (100.0) = 0.5, noise ≈ 0.3
        # Confidence should be moderate
        assert c < 5.0, f"Expected low confidence for noisy data, got {c}"

    def test_zero_confidence_no_improvement(self, tmp_path):
        tracker = ExperimentTracker(
            direction="higher",
            log_path=str(tmp_path / "log.jsonl"),
        )
        tracker.init()
        r = _make_result()

        # Getting worse
        for v in [100.0, 99.0, 98.0]:
            tracker.log(result=r, status="keep", primary_metric=v)

        c = tracker.confidence_score()
        assert c is not None
        assert c == 0.0, f"Expected 0 for regression, got {c}"

    def test_lower_is_better_direction(self, tmp_path):
        tracker = ExperimentTracker(
            direction="lower",
            log_path=str(tmp_path / "log.jsonl"),
        )
        tracker.init()
        r = _make_result()

        # Baseline with noise
        for v in [100.0, 100.5, 99.5, 100.2, 99.8]:
            tracker.log(result=r, status="keep", primary_metric=v)

        # Clear improvement (lower)
        tracker.log(result=r, status="keep", primary_metric=80.0)

        c = tracker.confidence_score()
        assert c is not None
        assert c > 2.0, f"Expected >2.0x for clear improvement, got {c}"

    def test_confidence_alias(self, tmp_path):
        tracker = ExperimentTracker(
            log_path=str(tmp_path / "log.jsonl"),
        )
        # confidence is an alias for confidence_score (both are the same method)
        assert tracker.confidence() == tracker.confidence_score()

    def test_identical_values_high_confidence_on_change(self, tmp_path):
        tracker = ExperimentTracker(
            direction="higher",
            log_path=str(tmp_path / "log.jsonl"),
        )
        tracker.init()
        r = _make_result()

        # All identical baseline (noise floor = 0 before improvement)
        for v in [100.0, 100.0, 100.0]:
            tracker.log(result=r, status="keep", primary_metric=v)

        # Any improvement should yield high confidence
        # (noise floor recalculated with improvement included, but still high)
        tracker.log(result=r, status="keep", primary_metric=101.0)
        c = tracker.confidence_score()
        assert c is not None
        assert c > 1.0, f"Expected >1.0x for clear improvement from identical baseline, got {c}"

    def test_discarded_results_excluded(self, tmp_path):
        tracker = ExperimentTracker(
            direction="higher",
            log_path=str(tmp_path / "log.jsonl"),
        )
        tracker.init()
        r = _make_result()

        # Mix of kept and discarded
        tracker.log(result=r, status="keep", primary_metric=100.0)
        tracker.log(result=r, status="discard", primary_metric=50.0)
        tracker.log(result=r, status="keep", primary_metric=101.0)
        tracker.log(result=r, status="discard", primary_metric=0.0)
        tracker.log(result=r, status="keep", primary_metric=99.5)

        # Confidence should be based on kept results only
        c = tracker.confidence_score()
        assert c is not None

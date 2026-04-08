"""Tests for error recovery, resilience, and robustness features."""

import json
import os
import tempfile
from pathlib import Path

import pytest

from flatmachines_cli.experiment import ExperimentTracker, ExperimentResult
from flatmachines_cli.improve import (
    SelfImprover,
    ImprovementRunner,
    scaffold_self_improve,
)


def _make_result(success=True, metrics=None, duration=1.0):
    return ExperimentResult(
        command="test",
        exit_code=0 if success else 1,
        stdout="",
        stderr="",
        duration_s=duration,
        metrics=metrics or {},
        success=success,
    )


class TestCorruptedJSONL:
    """Test graceful handling of corrupted log files."""

    def test_skip_corrupted_lines(self, tmp_path):
        log = tmp_path / "log.jsonl"
        lines = [
            json.dumps({"type": "config", "name": "test", "metric_name": "s", "direction": "higher"}),
            json.dumps({"type": "experiment", "experiment_id": 1, "description": "ok",
                        "status": "keep", "primary_metric": 100.0, "tags": [], "notes": {},
                        "timestamp": "t", "result": {"command": "c", "exit_code": 0,
                        "duration_s": 1.0, "metrics": {}, "success": True, "error": None,
                        "timestamp": "t"}}),
            "THIS IS NOT JSON {{{",
            json.dumps({"type": "experiment", "experiment_id": 2, "description": "ok2",
                        "status": "keep", "primary_metric": 200.0, "tags": [], "notes": {},
                        "timestamp": "t", "result": {"command": "c", "exit_code": 0,
                        "duration_s": 1.0, "metrics": {}, "success": True, "error": None,
                        "timestamp": "t"}}),
        ]
        log.write_text("\n".join(lines))

        t = ExperimentTracker.from_file(str(log))
        assert len(t.history) == 2
        assert t.load_errors == 1
        assert t.history[0].primary_metric == 100.0
        assert t.history[1].primary_metric == 200.0

    def test_all_corrupted(self, tmp_path):
        log = tmp_path / "log.jsonl"
        log.write_text("not json\nalso not json\n")
        t = ExperimentTracker.from_file(str(log))
        assert len(t.history) == 0
        assert t.load_errors == 2

    def test_empty_file(self, tmp_path):
        log = tmp_path / "log.jsonl"
        log.write_text("")
        t = ExperimentTracker.from_file(str(log))
        assert len(t.history) == 0
        assert t.load_errors == 0

    def test_mixed_valid_invalid(self, tmp_path):
        log = tmp_path / "log.jsonl"
        lines = [
            json.dumps({"type": "config", "name": "x"}),
            "",  # empty line
            "broken",
            json.dumps({"type": "experiment", "experiment_id": 1, "description": "a",
                        "status": "keep", "primary_metric": 50.0, "tags": [], "notes": {},
                        "timestamp": "t", "result": {"command": "c", "exit_code": 0,
                        "duration_s": 1.0, "metrics": {}, "success": True, "error": None,
                        "timestamp": "t"}}),
        ]
        log.write_text("\n".join(lines))
        t = ExperimentTracker.from_file(str(log))
        assert len(t.history) == 1
        assert t.load_errors == 1  # "broken" line


class TestExportMarkdown:
    """Test export_markdown() method."""

    def test_basic_markdown(self, tmp_path):
        t = ExperimentTracker(
            name="test-session",
            metric_name="score",
            direction="higher",
            log_path=str(tmp_path / "log.jsonl"),
        )
        t.init()
        r = _make_result()
        t.log(result=r, status="keep", primary_metric=100.0, description="first")
        t.log(result=r, status="discard", primary_metric=90.0, description="second")

        md = t.export_markdown()
        assert "# test-session" in md
        assert "**Metric**: score" in md
        assert "**Total experiments**: 2" in md
        assert "**Kept**: 1" in md
        assert "first" in md
        assert "second" in md

    def test_markdown_to_file(self, tmp_path):
        t = ExperimentTracker(log_path=str(tmp_path / "log.jsonl"))
        t.init()
        r = _make_result()
        t.log(result=r, status="keep", primary_metric=100.0)

        md_path = str(tmp_path / "report.md")
        t.export_markdown(path=md_path)
        assert Path(md_path).exists()
        content = Path(md_path).read_text()
        assert "# " in content

    def test_markdown_empty_history(self, tmp_path):
        t = ExperimentTracker(log_path=str(tmp_path / "log.jsonl"))
        t.init()
        md = t.export_markdown()
        assert "# " in md
        assert "**Total experiments**: 0" in md

    def test_markdown_has_table(self, tmp_path):
        t = ExperimentTracker(log_path=str(tmp_path / "log.jsonl"))
        t.init()
        r = _make_result()
        t.log(result=r, status="keep", primary_metric=100.0, description="test")
        md = t.export_markdown()
        assert "| # | Status |" in md
        assert "|---|" in md


class TestOnBeforeEval:
    """Test ImprovementRunner on_before_eval callback."""

    def test_before_eval_called(self, tmp_path):
        calls = []

        def before_eval(iteration, ctx):
            calls.append(iteration)
            return ctx

        imp = SelfImprover(
            target_dir=str(tmp_path),
            benchmark_command="echo 'METRIC score=100'",
            metric_name="score",
            direction="higher",
            log_path=str(tmp_path / "log.jsonl"),
            working_dir=str(tmp_path),
        )
        runner = ImprovementRunner(imp, max_iterations=2, on_before_eval=before_eval)
        runner.run()
        assert len(calls) == 2

    def test_before_eval_can_modify_context(self, tmp_path):
        def before_eval(iteration, ctx):
            ctx["agent_hypothesis"] = f"try approach {iteration}"
            return ctx

        imp = SelfImprover(
            target_dir=str(tmp_path),
            benchmark_command="echo 'METRIC score=100'",
            metric_name="score",
            direction="higher",
            log_path=str(tmp_path / "log.jsonl"),
            working_dir=str(tmp_path),
        )
        runner = ImprovementRunner(imp, max_iterations=1, on_before_eval=before_eval)
        ctx = runner.run()
        assert "agent_hypothesis" in ctx

    def test_without_before_eval(self, tmp_path):
        imp = SelfImprover(
            target_dir=str(tmp_path),
            benchmark_command="echo 'METRIC score=100'",
            metric_name="score",
            direction="higher",
            log_path=str(tmp_path / "log.jsonl"),
            working_dir=str(tmp_path),
        )
        # No on_before_eval → should still work
        runner = ImprovementRunner(imp, max_iterations=1)
        ctx = runner.run()
        assert "final_summary" in ctx


class TestScaffold:
    """Test scaffold_self_improve()."""

    def test_creates_files(self, tmp_path):
        created = scaffold_self_improve(str(tmp_path))
        assert len(created) == 2
        assert (tmp_path / "profiles.yml").exists()
        assert (tmp_path / "program.md").exists()

    def test_profiles_valid_yaml(self, tmp_path):
        import yaml
        scaffold_self_improve(str(tmp_path))
        with open(tmp_path / "profiles.yml") as f:
            config = yaml.safe_load(f)
        assert config["spec"] == "flatprofiles"

    def test_program_template_created(self, tmp_path):
        scaffold_self_improve(str(tmp_path))
        program = tmp_path / "program.md"
        assert program.exists()
        assert "Describe what to optimize" in program.read_text()

    def test_no_overwrite(self, tmp_path):
        (tmp_path / "profiles.yml").write_text("existing")
        (tmp_path / "program.md").write_text("existing")
        created = scaffold_self_improve(str(tmp_path))
        assert len(created) == 0
        assert (tmp_path / "profiles.yml").read_text() == "existing"
        assert (tmp_path / "program.md").read_text() == "existing"

    def test_partial_creation(self, tmp_path):
        (tmp_path / "profiles.yml").write_text("existing")
        created = scaffold_self_improve(str(tmp_path))
        assert len(created) == 1
        assert "program.md" in created[0]

    def test_importable_from_package(self):
        from flatmachines_cli import scaffold_self_improve as s
        assert callable(s)


class TestTrackerProperties:
    """Test new tracker properties."""

    def test_load_errors_property(self, tmp_path):
        t = ExperimentTracker(log_path=str(tmp_path / "log.jsonl"))
        t.init()
        assert t.load_errors == 0

    def test_git_enabled_property(self, tmp_path):
        t = ExperimentTracker(
            log_path=str(tmp_path / "log.jsonl"),
            git_enabled=True,
        )
        assert t.git_enabled is True

    def test_git_disabled_by_default(self, tmp_path):
        t = ExperimentTracker(log_path=str(tmp_path / "log.jsonl"))
        assert t.git_enabled is False

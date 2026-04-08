"""
Tests for the converged self-improvement system.

Covers: EvaluationSpec, EvaluationRunner, Archive, WorktreeIsolation,
ConvergedSelfImproveHooks — the full two-loop architecture.

Happy path, core loop focus. No rabbit holes.
"""

import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest
import yaml

from flatmachines_cli.evaluation import EvaluationSpec, EvaluationRunner, EvalResult
from flatmachines_cli.archive import Archive, ArchiveEntry
from flatmachines_cli.isolation import WorktreeIsolation
from flatmachines_cli.improve import (
    SelfImprover,
    ConvergedSelfImproveHooks,
)


# ── Helpers ──

def _init_git_repo(path: Path) -> None:
    """Initialize a git repo with an initial commit."""
    subprocess.run(["git", "init"], cwd=str(path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(path), capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(path), capture_output=True)
    (path / "README.md").write_text("# test\n")
    subprocess.run(["git", "add", "-A"], cwd=str(path), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=str(path), capture_output=True, check=True)


def _make_benchmark(path: Path, score: float = 42.0, metric: str = "score") -> Path:
    """Create a benchmark script that outputs a METRIC line."""
    bench = path / "bench.sh"
    bench.write_text(f"#!/bin/bash\necho 'METRIC {metric}={score}'\n")
    bench.chmod(0o755)
    return bench


# ── EvaluationSpec ──

class TestEvaluationSpec:

    def test_create_from_dict(self):
        spec = EvaluationSpec.from_dict({
            "benchmark_command": "bash bench.sh",
            "metric_name": "val_bpb",
            "direction": "lower",
            "protected_paths": ["bench.sh", "tests/"],
            "editable_patterns": ["src/**/*.py"],
        })
        assert spec.benchmark_command == "bash bench.sh"
        assert spec.metric_name == "val_bpb"
        assert spec.direction == "lower"
        assert spec.protected_paths == ("bench.sh", "tests/")
        assert spec.editable_patterns == ("src/**/*.py",)

    def test_frozen(self):
        spec = EvaluationSpec(benchmark_command="echo hi")
        with pytest.raises(AttributeError):
            spec.benchmark_command = "echo tampered"  # type: ignore

    def test_is_better_higher(self):
        spec = EvaluationSpec(benchmark_command="x", direction="higher")
        assert spec.is_better(10.0, 5.0)
        assert not spec.is_better(5.0, 10.0)

    def test_is_better_lower(self):
        spec = EvaluationSpec(benchmark_command="x", direction="lower")
        assert spec.is_better(5.0, 10.0)
        assert not spec.is_better(10.0, 5.0)

    def test_invalid_direction(self):
        with pytest.raises(ValueError):
            EvaluationSpec(benchmark_command="x", direction="sideways")

    def test_defaults(self):
        spec = EvaluationSpec(benchmark_command="echo hi")
        assert spec.metric_name == "score"
        assert spec.direction == "higher"
        assert spec.timeout_s == 300.0
        assert spec.checks_command == ""
        assert spec.protected_paths == ()
        assert spec.editable_patterns == ("**/*.py",)


# ── EvaluationRunner ──

class TestEvaluationRunner:

    def test_run_benchmark_with_log_redirect(self, tmp_path):
        _make_benchmark(tmp_path, score=85.0)
        spec = EvaluationSpec(
            benchmark_command=f"bash {tmp_path}/bench.sh",
            metric_name="score",
            log_file="run.log",
        )
        runner = EvaluationRunner(spec=spec, working_dir=str(tmp_path))
        result = runner.run_benchmark()
        assert result.success
        assert result.metrics["score"] == 85.0
        assert result.log_path is not None
        assert Path(result.log_path).exists()
        assert "METRIC score=85" in Path(result.log_path).read_text()

    def test_run_checks_pass(self, tmp_path):
        spec = EvaluationSpec(
            benchmark_command="echo hi",
            checks_command="echo 'checks ok'",
        )
        runner = EvaluationRunner(spec=spec, working_dir=str(tmp_path))
        result = runner.run_checks()
        assert result.success

    def test_run_checks_fail(self, tmp_path):
        spec = EvaluationSpec(
            benchmark_command="echo hi",
            checks_command="exit 1",
        )
        runner = EvaluationRunner(spec=spec, working_dir=str(tmp_path))
        result = runner.run_checks()
        assert not result.success

    def test_run_checks_skipped_when_empty(self, tmp_path):
        spec = EvaluationSpec(benchmark_command="echo hi", checks_command="")
        runner = EvaluationRunner(spec=spec, working_dir=str(tmp_path))
        result = runner.run_checks()
        assert result.success
        assert result.command == "(no checks)"

    def test_run_staged_full_pipeline(self, tmp_path):
        _make_benchmark(tmp_path, score=90.0)
        spec = EvaluationSpec(
            benchmark_command=f"bash {tmp_path}/bench.sh",
            checks_command="true",
            metric_name="score",
        )
        runner = EvaluationRunner(spec=spec, working_dir=str(tmp_path))
        stage, result = runner.run_staged()
        assert stage == "complete"
        assert result.success
        assert result.metrics["score"] == 90.0

    def test_run_staged_fails_at_checks(self, tmp_path):
        spec = EvaluationSpec(
            benchmark_command="echo 'METRIC score=100'",
            checks_command="exit 1",
        )
        runner = EvaluationRunner(spec=spec, working_dir=str(tmp_path))
        stage, result = runner.run_staged()
        assert stage == "checks"
        assert not result.success

    def test_timeout_returns_error(self, tmp_path):
        spec = EvaluationSpec(
            benchmark_command="sleep 10",
            timeout_s=0.1,
        )
        runner = EvaluationRunner(spec=spec, working_dir=str(tmp_path))
        result = runner.run_benchmark()
        assert not result.success
        assert "timed out" in result.error

    def test_validate_edit_scope(self, tmp_path):
        spec = EvaluationSpec(
            benchmark_command="echo hi",
            editable_patterns=("src/**/*.py", "lib/*.py"),
        )
        runner = EvaluationRunner(spec=spec, working_dir=str(tmp_path))

        ok, bad = runner.validate_edit_scope(["src/main.py", "src/utils/helper.py"])
        assert ok
        assert bad == []

        ok, bad = runner.validate_edit_scope(["src/main.py", "bench.sh"])
        assert not ok
        assert "bench.sh" in bad

    def test_validate_no_tampering_no_protected(self, tmp_path):
        spec = EvaluationSpec(benchmark_command="echo hi", protected_paths=())
        runner = EvaluationRunner(spec=spec, working_dir=str(tmp_path))
        clean, violated = runner.validate_no_tampering()
        assert clean
        assert violated == []


# ── Archive ──

class TestArchive:

    def test_add_and_retrieve(self, tmp_path):
        archive = Archive(path=str(tmp_path / "archive.jsonl"))
        e0 = archive.add(parent_id=None, patch_file="", score=10.0, status="baseline")
        assert e0.generation_id == 0
        assert archive.size == 1

        e1 = archive.add(parent_id=0, patch_file="p1.diff", score=15.0)
        assert e1.generation_id == 1
        assert e1.parent_id == 0
        assert archive.size == 2

        # Parent should have child linked
        parent = archive.get(0)
        assert 1 in parent.children

    def test_best_entry(self, tmp_path):
        archive = Archive(path=str(tmp_path / "archive.jsonl"))
        archive.add(parent_id=None, patch_file="", score=10.0)
        archive.add(parent_id=0, patch_file="p1.diff", score=25.0)
        archive.add(parent_id=0, patch_file="p2.diff", score=15.0)

        best = archive.best_entry()
        assert best.score == 25.0
        assert best.generation_id == 1

    def test_select_parent_best(self, tmp_path):
        archive = Archive(path=str(tmp_path / "archive.jsonl"))
        archive.add(parent_id=None, patch_file="", score=10.0)
        archive.add(parent_id=0, patch_file="p1.diff", score=25.0)

        parent = archive.select_parent(method="best")
        assert parent.score == 25.0

    def test_select_parent_score_child_prop(self, tmp_path):
        archive = Archive(path=str(tmp_path / "archive.jsonl"))
        archive.add(parent_id=None, patch_file="", score=10.0)
        archive.add(parent_id=0, patch_file="p1.diff", score=20.0)
        archive.add(parent_id=0, patch_file="p2.diff", score=15.0)

        # Just verify it returns a valid entry (stochastic)
        parent = archive.select_parent(method="score_child_prop")
        assert parent is not None
        assert parent.score is not None

    def test_select_parent_empty(self, tmp_path):
        archive = Archive(path=str(tmp_path / "archive.jsonl"))
        assert archive.select_parent() is None

    def test_get_lineage(self, tmp_path):
        archive = Archive(path=str(tmp_path / "archive.jsonl"))
        archive.add(parent_id=None, patch_file="base.diff", score=10.0)
        archive.add(parent_id=0, patch_file="gen1.diff", score=15.0)
        archive.add(parent_id=1, patch_file="gen2.diff", score=20.0)

        lineage = archive.get_lineage(2)
        assert len(lineage) == 3
        assert [e.generation_id for e in lineage] == [0, 1, 2]

    def test_get_patch_chain(self, tmp_path):
        archive = Archive(path=str(tmp_path / "archive.jsonl"))
        archive.add(parent_id=None, patch_file="base.diff", score=10.0)
        archive.add(parent_id=0, patch_file="gen1.diff", score=15.0)

        patches = archive.get_patch_chain(1)
        assert patches == ["base.diff", "gen1.diff"]

    def test_persistence(self, tmp_path):
        path = str(tmp_path / "archive.jsonl")

        # Session 1: add entries
        a1 = Archive(path=path)
        a1.add(parent_id=None, patch_file="", score=10.0, status="baseline")
        a1.add(parent_id=0, patch_file="p1.diff", score=20.0)

        # Session 2: reload
        a2 = Archive(path=path)
        assert a2.size == 2
        assert a2.best_score() == 20.0

        # Continue adding
        a2.add(parent_id=1, patch_file="p2.diff", score=30.0)
        assert a2.size == 3

    def test_summary_tsv(self, tmp_path):
        archive = Archive(path=str(tmp_path / "archive.jsonl"))
        archive.add(parent_id=None, patch_file="", score=10.0, status="baseline",
                     metadata={"description": "initial"})
        archive.add(parent_id=0, patch_file="p1.diff", score=20.0,
                     metadata={"description": "doubled LR"})

        tsv = archive.summary_tsv()
        lines = tsv.strip().split("\n")
        assert len(lines) == 3  # header + 2 entries
        assert "gen_id" in lines[0]
        assert "initial" in lines[1]
        assert "doubled LR" in lines[2]

    def test_failed_generation_preserved(self, tmp_path):
        archive = Archive(path=str(tmp_path / "archive.jsonl"))
        archive.add(parent_id=None, patch_file="", score=10.0)
        archive.add(parent_id=0, patch_file="bad.diff", score=None, status="failed")

        assert archive.size == 2
        failed = archive.get(1)
        assert failed.status == "failed"
        assert failed.score is None

        # best_entry should skip failures
        best = archive.best_entry()
        assert best.generation_id == 0


# ── WorktreeIsolation ──

class TestWorktreeIsolation:

    def test_create_and_cleanup_worktree(self, tmp_path):
        _init_git_repo(tmp_path)
        iso = WorktreeIsolation(repo_dir=str(tmp_path))

        # Create
        wt_path = iso.create_worktree(0)
        assert Path(wt_path).exists()
        assert (Path(wt_path) / "README.md").exists()

        # Cleanup
        assert iso.cleanup_worktree(0)
        assert not Path(wt_path).exists()

    def test_extract_diff(self, tmp_path):
        _init_git_repo(tmp_path)
        iso = WorktreeIsolation(repo_dir=str(tmp_path))
        wt_path = iso.create_worktree(0)

        # Make a change in the worktree
        (Path(wt_path) / "new_file.py").write_text("print('hello')\n")

        patch = iso.extract_diff(wt_path, 0)
        assert Path(patch).exists()
        content = Path(patch).read_text()
        assert "new_file.py" in content
        assert "hello" in content

        iso.cleanup_worktree(0)

    def test_commit_and_reset_worktree(self, tmp_path):
        _init_git_repo(tmp_path)
        iso = WorktreeIsolation(repo_dir=str(tmp_path))
        wt_path = iso.create_worktree(0)

        # Make a change and commit
        (Path(wt_path) / "change.py").write_text("x = 1\n")
        commit = iso.commit_worktree(wt_path, "test commit")
        assert commit is not None

        # Make another change and reset
        (Path(wt_path) / "bad.py").write_text("oops\n")
        assert (Path(wt_path) / "bad.py").exists()
        iso.reset_worktree(wt_path)
        assert not (Path(wt_path) / "bad.py").exists()
        # Committed change should survive
        assert (Path(wt_path) / "change.py").exists()

        iso.cleanup_worktree(0)

    def test_get_head_commit(self, tmp_path):
        _init_git_repo(tmp_path)
        iso = WorktreeIsolation(repo_dir=str(tmp_path))
        commit = iso.get_head_commit()
        assert commit is not None
        assert len(commit) == 40  # Full SHA


# ── ConvergedSelfImproveHooks ──

class TestConvergedHooks:

    def _make_improver(self, tmp_path, score=42.0):
        """Create a SelfImprover with a working benchmark."""
        _make_benchmark(tmp_path, score=score)
        spec = EvaluationSpec(
            benchmark_command=f"bash {tmp_path}/bench.sh",
            metric_name="score",
            direction="higher",
            checks_command="true",
        )
        return SelfImprover(
            target_dir=str(tmp_path),
            benchmark_command=f"bash {tmp_path}/bench.sh",
            metric_name="score",
            direction="higher",
            log_path=str(tmp_path / "log.jsonl"),
            working_dir=str(tmp_path),
            eval_spec=spec,
            archive_path=str(tmp_path / "archive.jsonl"),
        )

    def test_select_parent_empty_archive(self, tmp_path):
        improver = self._make_improver(tmp_path)
        hooks = ConvergedSelfImproveHooks(improver)
        ctx = {"parent_selection": "best"}
        ctx = hooks.on_action("select_parent_from_archive", ctx)
        assert ctx["parent_id"] is None

    def test_select_parent_with_archive(self, tmp_path):
        improver = self._make_improver(tmp_path)
        hooks = ConvergedSelfImproveHooks(improver)

        # Pre-populate archive
        improver.archive.add(parent_id=None, patch_file="", score=10.0, status="baseline")
        improver.archive.add(parent_id=0, patch_file="p.diff", score=20.0)

        ctx = {"parent_selection": "best"}
        ctx = hooks.on_action("select_parent_from_archive", ctx)
        assert ctx["parent_id"] == 1  # Best score = 20.0

    def test_run_checks_pass(self, tmp_path):
        improver = self._make_improver(tmp_path)
        hooks = ConvergedSelfImproveHooks(improver)
        ctx = {"consecutive_failures": 0}
        ctx = hooks.on_action("run_checks", ctx)
        assert ctx["last_status"] == "checks_passed"

    def test_run_checks_fail(self, tmp_path):
        spec = EvaluationSpec(
            benchmark_command="echo hi",
            checks_command="exit 1",
        )
        improver = SelfImprover(
            target_dir=str(tmp_path),
            log_path=str(tmp_path / "log.jsonl"),
            working_dir=str(tmp_path),
            eval_spec=spec,
            archive_path=str(tmp_path / "archive.jsonl"),
        )
        hooks = ConvergedSelfImproveHooks(improver)
        ctx = {"consecutive_failures": 0}
        ctx = hooks.on_action("run_checks", ctx)
        assert ctx["last_status"] == "checks_failed"
        assert ctx["consecutive_failures"] == 1

    def test_evaluate_staged_improve(self, tmp_path):
        improver = self._make_improver(tmp_path, score=42.0)
        hooks = ConvergedSelfImproveHooks(improver)
        ctx = {
            "best_score": None,
            "inner_iteration": 0,
            "consecutive_failures": 0,
            "generation": 0,
        }
        ctx = hooks.on_action("evaluate_with_staging", ctx)
        assert ctx["last_status"] == "improved"
        assert ctx["best_score"] == 42.0
        assert ctx["inner_iteration"] == 1

    def test_evaluate_staged_no_improvement(self, tmp_path):
        improver = self._make_improver(tmp_path, score=42.0)
        hooks = ConvergedSelfImproveHooks(improver)
        ctx = {
            "best_score": 100.0,  # Already better
            "inner_iteration": 0,
            "consecutive_failures": 0,
            "generation": 0,
        }
        ctx = hooks.on_action("evaluate_with_staging", ctx)
        assert ctx["last_status"] == "no_improvement"
        assert ctx["best_score"] == 100.0  # Unchanged
        assert ctx["consecutive_failures"] == 1

    def test_extract_and_archive(self, tmp_path):
        improver = self._make_improver(tmp_path)
        hooks = ConvergedSelfImproveHooks(improver)
        ctx = {
            "generation": 0,
            "parent_id": None,
            "best_score": 42.0,
            "analysis": "test improvement",
        }
        ctx = hooks.on_action("extract_diff_and_archive", ctx)
        assert ctx["generation"] == 1
        assert ctx["archive_size"] == 1

        # Summary file should exist
        summary_path = Path(tmp_path) / ".self_improve" / "archive_summary.tsv"
        assert summary_path.exists()

    def test_full_inner_loop_cycle(self, tmp_path):
        """Test the core inner loop: checks → evaluate → keep/discard."""
        improver = self._make_improver(tmp_path, score=50.0)
        hooks = ConvergedSelfImproveHooks(improver)

        ctx = {
            "best_score": None,
            "inner_iteration": 0,
            "consecutive_failures": 0,
            "generation": 0,
            "worktree_path": str(tmp_path),
            "last_hypothesis": "baseline",
        }

        # Step 1: Checks pass
        ctx = hooks.on_action("run_checks", ctx)
        assert ctx["last_status"] == "checks_passed"

        # Step 2: Evaluate → improved (first run, no baseline)
        ctx = hooks.on_action("evaluate_with_staging", ctx)
        assert ctx["last_status"] == "improved"
        assert ctx["best_score"] == 50.0

        # Step 3: Simulate second run with lower score
        _make_benchmark(tmp_path, score=30.0)
        ctx = hooks.on_action("run_checks", ctx)
        assert ctx["last_status"] == "checks_passed"
        ctx = hooks.on_action("evaluate_with_staging", ctx)
        assert ctx["last_status"] == "no_improvement"
        assert ctx["best_score"] == 50.0  # Still the old best

        # Step 4: Simulate third run with better score
        _make_benchmark(tmp_path, score=75.0)
        ctx = hooks.on_action("run_checks", ctx)
        ctx = hooks.on_action("evaluate_with_staging", ctx)
        assert ctx["last_status"] == "improved"
        assert ctx["best_score"] == 75.0

    def test_backward_compat_simple_actions(self, tmp_path):
        """ConvergedHooks should also handle the original simple actions."""
        _make_benchmark(tmp_path, score=42.0)
        improver = SelfImprover(
            target_dir=str(tmp_path),
            benchmark_command=f"bash {tmp_path}/bench.sh",
            metric_name="score",
            direction="higher",
            log_path=str(tmp_path / "log.jsonl"),
            working_dir=str(tmp_path),
            archive_path=str(tmp_path / "archive.jsonl"),
        )
        hooks = ConvergedSelfImproveHooks(improver)

        ctx = {
            "iteration": 0,
            "consecutive_failures": 0,
            "best_score": None,
            "improvement_history": [],
            "last_hypothesis": "test",
        }
        ctx = hooks.on_action("evaluate_improvement", ctx)
        assert ctx["last_status"] == "improved"
        assert ctx["best_score"] == 42.0


# ── SelfImprover with EvaluationSpec ──

class TestSelfImproverConverged:

    def test_eval_spec_from_simple_params(self, tmp_path):
        """When no eval_spec is passed, one is built from simple params."""
        imp = SelfImprover(
            target_dir=str(tmp_path),
            benchmark_command="echo 'METRIC score=10'",
            metric_name="score",
            direction="higher",
            log_path=str(tmp_path / "log.jsonl"),
            working_dir=str(tmp_path),
        )
        assert imp.eval_spec.benchmark_command == "echo 'METRIC score=10'"
        assert imp.eval_spec.metric_name == "score"
        assert imp.eval_spec.direction == "higher"

    def test_eval_spec_explicit(self, tmp_path):
        spec = EvaluationSpec(
            benchmark_command="bash bench.sh",
            metric_name="val_bpb",
            direction="lower",
            protected_paths=("bench.sh",),
        )
        imp = SelfImprover(
            target_dir=str(tmp_path),
            log_path=str(tmp_path / "log.jsonl"),
            working_dir=str(tmp_path),
            eval_spec=spec,
        )
        assert imp.eval_spec.metric_name == "val_bpb"
        assert imp.eval_spec.direction == "lower"
        assert imp.eval_spec.protected_paths == ("bench.sh",)

    def test_archive_created(self, tmp_path):
        imp = SelfImprover(
            target_dir=str(tmp_path),
            log_path=str(tmp_path / "log.jsonl"),
            working_dir=str(tmp_path),
            archive_path=str(tmp_path / "archive.jsonl"),
        )
        assert imp.archive is not None
        assert imp.archive.size == 0

    def test_isolation_opt_in(self, tmp_path):
        imp = SelfImprover(
            target_dir=str(tmp_path),
            log_path=str(tmp_path / "log.jsonl"),
            working_dir=str(tmp_path),
        )
        assert imp.isolation is None  # Not enabled by default

        _init_git_repo(tmp_path)
        imp2 = SelfImprover(
            target_dir=str(tmp_path),
            log_path=str(tmp_path / "log.jsonl"),
            working_dir=str(tmp_path),
            enable_isolation=True,
        )
        assert imp2.isolation is not None


# ── Machine Config Validation ──

class TestConvergedMachineConfig:

    @pytest.fixture
    def config(self):
        config_path = Path(__file__).parent.parent / "config" / "self_improve.yml"
        with open(config_path) as f:
            return yaml.safe_load(f)

    def test_has_required_states(self, config):
        states = config["data"]["states"]
        # Outer loop infrastructure
        assert "select_parent" in states
        assert "setup_worktree" in states
        assert "archive_generation" in states
        assert "cleanup_worktree" in states
        assert "outer_budget_check" in states
        # Agent does everything
        assert "improve" in states

    def test_eval_spec_in_context(self, config):
        context = config["data"]["context"]
        assert "eval_spec" in context
        spec = context["eval_spec"]
        assert "benchmark_command" in spec
        assert "protected_paths" in spec
        assert "editable_patterns" in spec

    def test_all_transitions_valid(self, config):
        states = config["data"]["states"]
        state_names = set(states.keys())
        for sname, sdata in states.items():
            for t in sdata.get("transitions", []):
                target = t.get("to")
                assert target in state_names, (
                    f"'{sname}' → '{target}' not found in states"
                )

    def test_has_initial_and_final(self, config):
        states = config["data"]["states"]
        initial = [s for s, d in states.items() if d.get("type") == "initial"]
        final = [s for s, d in states.items() if d.get("type") == "final"]
        assert len(initial) == 1
        assert len(final) == 1

    def test_final_has_output(self, config):
        states = config["data"]["states"]
        done = states["done"]
        assert done.get("output")
        assert "best_score" in done["output"]
        assert "archive_size" in done["output"]

    def test_outer_loop_context_fields(self, config):
        context = config["data"]["context"]
        assert "max_generations" in context
        assert "generation" in context
        assert "parent_selection" in context
        assert "archive_size" in context

    def test_agent_input_has_scope(self, config):
        improve = config["data"]["states"]["improve"]
        inp = improve["input"]
        assert "editable_patterns" in inp
        assert "protected_paths" in inp
        assert "benchmark_command" in inp

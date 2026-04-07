"""Tests for git integration in ExperimentTracker."""

import os
import subprocess
import tempfile
from pathlib import Path

import pytest

from flatmachines_cli.experiment import ExperimentTracker, ExperimentResult


def _init_git_repo(path: str) -> None:
    """Initialize a git repo with an initial commit."""
    subprocess.run(["git", "init"], cwd=path, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=path, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=path, capture_output=True,
    )
    # Create initial file and commit
    Path(path, "initial.txt").write_text("initial")
    subprocess.run(["git", "add", "."], cwd=path, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "initial commit"],
        cwd=path, capture_output=True,
    )


class TestGitCommit:
    def test_git_commit_basic(self, tmp_path):
        _init_git_repo(str(tmp_path))
        tracker = ExperimentTracker(
            log_path=str(tmp_path / "log.jsonl"),
            working_dir=str(tmp_path),
        )

        # Make a change
        (tmp_path / "new.txt").write_text("hello")

        # Commit
        result = tracker.git_commit("test commit message")
        assert result is True

        # Verify commit exists
        log = subprocess.run(
            ["git", "log", "--oneline", "-1"],
            cwd=str(tmp_path), capture_output=True, text=True,
        )
        assert "test commit message" in log.stdout

    def test_git_commit_no_repo(self, tmp_path):
        """Commit in a non-git directory should return False."""
        tracker = ExperimentTracker(
            log_path=str(tmp_path / "log.jsonl"),
            working_dir=str(tmp_path),
        )
        result = tracker.git_commit("test")
        assert result is False

    def test_git_commit_empty_allowed(self, tmp_path):
        """Commit with no changes should succeed (--allow-empty)."""
        _init_git_repo(str(tmp_path))
        tracker = ExperimentTracker(
            log_path=str(tmp_path / "log.jsonl"),
            working_dir=str(tmp_path),
        )
        result = tracker.git_commit("empty commit")
        assert result is True


class TestGitRevert:
    def test_git_revert_basic(self, tmp_path):
        _init_git_repo(str(tmp_path))
        tracker = ExperimentTracker(
            log_path=str(tmp_path / "log.jsonl"),
            working_dir=str(tmp_path),
        )

        # Make a change
        (tmp_path / "initial.txt").write_text("modified")

        # Revert
        result = tracker.git_revert()
        assert result is True

        # Verify reverted
        content = (tmp_path / "initial.txt").read_text()
        assert content == "initial"

    def test_git_revert_staged_changes(self, tmp_path):
        _init_git_repo(str(tmp_path))
        tracker = ExperimentTracker(
            log_path=str(tmp_path / "log.jsonl"),
            working_dir=str(tmp_path),
        )

        # Make and stage a change
        (tmp_path / "initial.txt").write_text("staged change")
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)

        # Revert
        result = tracker.git_revert()
        assert result is True

        # Verify reverted
        content = (tmp_path / "initial.txt").read_text()
        assert content == "initial"

    def test_git_revert_no_repo(self, tmp_path):
        """Revert in a non-git directory should return False."""
        tracker = ExperimentTracker(
            log_path=str(tmp_path / "log.jsonl"),
            working_dir=str(tmp_path),
        )
        result = tracker.git_revert()
        assert result is False

    def test_aliases_exist(self, tmp_path):
        tracker = ExperimentTracker(log_path=str(tmp_path / "log.jsonl"))
        assert hasattr(tracker, "commit_changes")
        assert hasattr(tracker, "revert_changes")
        assert hasattr(tracker, "git_reset")


class TestGitIntegration:
    """Test auto-commit on keep, auto-revert on discard."""

    def test_keep_auto_commits(self, tmp_path):
        _init_git_repo(str(tmp_path))
        tracker = ExperimentTracker(
            log_path=str(tmp_path / "log.jsonl"),
            working_dir=str(tmp_path),
            git_enabled=True,
        )
        tracker.init()

        # Make a change
        (tmp_path / "feature.txt").write_text("new feature")

        # Log as keep → should auto-commit
        result = ExperimentResult(
            command="test", exit_code=0, stdout="", stderr="",
            duration_s=1.0, success=True,
        )
        tracker.log(result=result, status="keep", description="add feature")

        # Verify committed
        log = subprocess.run(
            ["git", "log", "--oneline"],
            cwd=str(tmp_path), capture_output=True, text=True,
        )
        assert "add feature" in log.stdout

    def test_discard_auto_reverts(self, tmp_path):
        _init_git_repo(str(tmp_path))
        tracker = ExperimentTracker(
            log_path=str(tmp_path / "log.jsonl"),
            working_dir=str(tmp_path),
            git_enabled=True,
        )
        tracker.init()

        # Make a change
        (tmp_path / "initial.txt").write_text("bad change")
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)

        # Log as discard → should auto-revert
        result = ExperimentResult(
            command="test", exit_code=0, stdout="", stderr="",
            duration_s=1.0, success=True,
        )
        tracker.log(result=result, status="discard", description="bad idea")

        # Verify reverted
        content = (tmp_path / "initial.txt").read_text()
        assert content == "initial"

    def test_git_disabled_no_commit(self, tmp_path):
        """With git_enabled=False, no auto-commit/revert."""
        _init_git_repo(str(tmp_path))
        tracker = ExperimentTracker(
            log_path=str(tmp_path / "log.jsonl"),
            working_dir=str(tmp_path),
            git_enabled=False,  # default
        )
        tracker.init()

        (tmp_path / "change.txt").write_text("change")
        result = ExperimentResult(
            command="test", exit_code=0, stdout="", stderr="",
            duration_s=1.0, success=True,
        )
        tracker.log(result=result, status="keep", description="no auto-commit")

        # File should still exist (not committed, not reverted)
        assert (tmp_path / "change.txt").exists()

        # Only initial commit should exist
        log = subprocess.run(
            ["git", "log", "--oneline"],
            cwd=str(tmp_path), capture_output=True, text=True,
        )
        assert "no auto-commit" not in log.stdout

    def test_crash_auto_reverts(self, tmp_path):
        _init_git_repo(str(tmp_path))
        tracker = ExperimentTracker(
            log_path=str(tmp_path / "log.jsonl"),
            working_dir=str(tmp_path),
            git_enabled=True,
        )
        tracker.init()

        (tmp_path / "initial.txt").write_text("crash change")
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)

        result = ExperimentResult(
            command="test", exit_code=1, stdout="", stderr="",
            duration_s=1.0, success=False,
        )
        tracker.log(result=result, status="crash", description="crashed")

        content = (tmp_path / "initial.txt").read_text()
        assert content == "initial"

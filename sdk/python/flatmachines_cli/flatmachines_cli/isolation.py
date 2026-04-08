"""
Lightweight isolation using git worktrees.

Each generation runs in its own worktree branched from the parent commit.
This provides:
- Perfect isolation: bad mutations can't corrupt the main tree
- Fast creation: milliseconds, not seconds (unlike Docker)
- Same filesystem: benchmarks work identically
- Clean diff extraction: git diff captures exactly what changed

Worktree layout:
    .self_improve/
        worktrees/
            gen_0/        ← worktree for generation 0
            gen_1/        ← worktree for generation 1
        patches/
            gen_0.diff    ← diff extracted after generation 0
            gen_1.diff    ← diff extracted after generation 1
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


class WorktreeIsolation:
    """Manages git worktrees for experiment isolation.

    Each generation gets its own worktree. Diffs are extracted and
    stored as patch files for lineage reconstruction.
    """

    def __init__(
        self,
        repo_dir: str,
        base_dir: str = ".self_improve",
    ):
        self._repo_dir = os.path.abspath(repo_dir)
        self._base_dir = Path(self._repo_dir) / base_dir
        self._worktree_dir = self._base_dir / "worktrees"
        self._patch_dir = self._base_dir / "patches"

    @property
    def repo_dir(self) -> str:
        return self._repo_dir

    @property
    def patch_dir(self) -> str:
        return str(self._patch_dir)

    def create_worktree(
        self,
        generation_id: int,
        parent_commit: Optional[str] = None,
    ) -> str:
        """Create an isolated worktree for a generation.

        Args:
            generation_id: Unique generation ID.
            parent_commit: Git ref to branch from. Defaults to HEAD.

        Returns:
            Absolute path to the worktree directory.
        """
        wt_path = self._worktree_dir / f"gen_{generation_id}"
        branch_name = f"self-improve/gen-{generation_id}"

        # Clean up if exists from a previous aborted run
        if wt_path.exists():
            self.cleanup_worktree(generation_id)

        self._worktree_dir.mkdir(parents=True, exist_ok=True)

        cmd = ["git", "worktree", "add", "-b", branch_name, str(wt_path)]
        if parent_commit:
            cmd.append(parent_commit)

        result = subprocess.run(
            cmd,
            cwd=self._repo_dir,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Failed to create worktree: {result.stderr.strip()}"
            )

        # Share local virtualenv into the worktree when present.
        # .venv is usually untracked, so worktrees do not include it by default.
        source_venv = Path(self._repo_dir) / ".venv"
        target_venv = wt_path / ".venv"
        if source_venv.exists() and not target_venv.exists():
            try:
                target_venv.symlink_to(source_venv)
            except OSError:
                # Non-fatal: agent can still use python3/uv or absolute host paths.
                pass

        return str(wt_path)

    def apply_patches(
        self,
        worktree_path: str,
        patch_files: List[str],
    ) -> Tuple[bool, str]:
        """Apply ancestor patches to reconstruct a generation's state.

        Args:
            worktree_path: Path to the worktree.
            patch_files: Ordered list of patch files to apply.

        Returns:
            (success, error_message)
        """
        for patch_file in patch_files:
            if not Path(patch_file).exists():
                continue  # Skip missing patches (baseline has none)
            if Path(patch_file).stat().st_size == 0:
                continue  # Skip empty patches

            result = subprocess.run(
                ["git", "apply", "--allow-empty", patch_file],
                cwd=worktree_path,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                # Try with 3-way merge as fallback
                result = subprocess.run(
                    ["git", "apply", "--3way", "--allow-empty", patch_file],
                    cwd=worktree_path,
                    capture_output=True,
                    text=True,
                )
                if result.returncode != 0:
                    return False, f"Failed to apply {patch_file}: {result.stderr.strip()}"

        return True, ""

    def extract_diff(
        self,
        worktree_path: str,
        generation_id: int,
    ) -> str:
        """Extract the diff of changes made in a worktree.

        Args:
            worktree_path: Path to the worktree.
            generation_id: Generation ID for naming the patch file.

        Returns:
            Path to the extracted patch file.
        """
        self._patch_dir.mkdir(parents=True, exist_ok=True)
        output_path = self._patch_dir / f"gen_{generation_id}.diff"

        # Capture both staged and unstaged changes
        result = subprocess.run(
            ["git", "diff", "HEAD"],
            cwd=worktree_path,
            capture_output=True,
            text=True,
        )

        # Also get untracked files
        untracked = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            cwd=worktree_path,
            capture_output=True,
            text=True,
        )

        diff_content = result.stdout
        # For untracked files, generate a diff manually
        for ufile in untracked.stdout.strip().split("\n"):
            if ufile.strip():
                try:
                    content = (Path(worktree_path) / ufile).read_text()
                    diff_content += f"\n--- /dev/null\n+++ b/{ufile}\n"
                    for line in content.split("\n"):
                        diff_content += f"+{line}\n"
                except (OSError, UnicodeDecodeError):
                    pass

        output_path.write_text(diff_content)
        return str(output_path)

    def commit_worktree(
        self,
        worktree_path: str,
        message: str = "self-improve generation",
    ) -> Optional[str]:
        """Stage all changes and commit in a worktree.

        Returns the commit hash, or None if nothing to commit.
        """
        subprocess.run(
            ["git", "add", "-A"],
            cwd=worktree_path,
            capture_output=True,
        )

        result = subprocess.run(
            ["git", "commit", "-m", message, "--allow-empty"],
            cwd=worktree_path,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return None

        # Get the commit hash
        hash_result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=worktree_path,
            capture_output=True,
            text=True,
        )
        return hash_result.stdout.strip() if hash_result.returncode == 0 else None

    def reset_worktree(self, worktree_path: str) -> bool:
        """Reset a worktree to its branch head (discard changes)."""
        try:
            subprocess.run(
                ["git", "checkout", "--", "."],
                cwd=worktree_path,
                capture_output=True,
                check=True,
            )
            subprocess.run(
                ["git", "clean", "-fd"],
                cwd=worktree_path,
                capture_output=True,
            )
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False

    def cleanup_worktree(self, generation_id: int) -> bool:
        """Remove a worktree and its branch after the experiment is done."""
        wt_path = self._worktree_dir / f"gen_{generation_id}"
        branch_name = f"self-improve/gen-{generation_id}"

        try:
            # Remove worktree
            if wt_path.exists():
                subprocess.run(
                    ["git", "worktree", "remove", "--force", str(wt_path)],
                    cwd=self._repo_dir,
                    capture_output=True,
                )
                # Fallback: manual removal if git worktree remove fails
                if wt_path.exists():
                    shutil.rmtree(str(wt_path), ignore_errors=True)

            # Prune worktree references
            subprocess.run(
                ["git", "worktree", "prune"],
                cwd=self._repo_dir,
                capture_output=True,
            )

            # Delete the branch
            subprocess.run(
                ["git", "branch", "-D", branch_name],
                cwd=self._repo_dir,
                capture_output=True,
            )
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False

    def cleanup_all(self) -> None:
        """Remove all worktrees and patches. Full cleanup."""
        if self._worktree_dir.exists():
            # List all worktrees to clean up properly
            for wt in self._worktree_dir.iterdir():
                if wt.is_dir() and wt.name.startswith("gen_"):
                    try:
                        gen_id = int(wt.name.split("_")[1])
                        self.cleanup_worktree(gen_id)
                    except (ValueError, IndexError):
                        shutil.rmtree(str(wt), ignore_errors=True)

        # Prune any orphaned worktree refs
        subprocess.run(
            ["git", "worktree", "prune"],
            cwd=self._repo_dir,
            capture_output=True,
        )

    def get_head_commit(self, worktree_path: Optional[str] = None) -> Optional[str]:
        """Get HEAD commit hash for a worktree (or the main repo)."""
        cwd = worktree_path or self._repo_dir
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip() if result.returncode == 0 else None

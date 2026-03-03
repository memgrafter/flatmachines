"""
Unit tests for hooks non-interactive approvals and secure file reads.
"""

import tempfile
from pathlib import Path
from unittest.mock import patch

from coding_agent.hooks import CodingAgentHooks


class TestReadFileSecurity:
    def test_read_file_blocks_prefix_escape(self):
        """Block paths like ../project2 that share the same string prefix."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir) / "project"
            sibling = Path(tmpdir) / "project2"
            base.mkdir()
            sibling.mkdir()
            (sibling / "secret.txt").write_text("top-secret")

            hooks = CodingAgentHooks()
            context = {
                "working_dir": str(base),
                "action_command": "../project2/secret.txt",
            }

            result = hooks._read_file(context)
            assert result["latest_action"] == "read"
            assert "outside working directory" in result["latest_output"].lower()


class TestNonInteractiveApprovals:
    def test_plan_approval_from_env(self):
        hooks = CodingAgentHooks()
        context = {"plan": "Do thing", "task": "Task"}

        with patch.dict("os.environ", {"CODING_AGENT_APPROVAL_PLAN": "approved"}, clear=False):
            with patch("builtins.input", side_effect=AssertionError("input() should not be called")):
                result = hooks._human_review_plan(context)

        assert result["plan_approved"] is True
        assert result["human_feedback"] is None

    def test_result_feedback_from_env(self):
        hooks = CodingAgentHooks()
        context = {
            "changes": "diff",
            "issues": "issue",
            "task": "Task",
            "iteration": 1,
            "changes_history": [],
        }

        with patch.dict("os.environ", {"CODING_AGENT_APPROVAL_RESULT": "please add tests"}, clear=False):
            with patch("builtins.input", side_effect=AssertionError("input() should not be called")):
                result = hooks._human_review_result(context)

        assert result["result_approved"] is False
        assert result["human_feedback"] == "please add tests"
        assert len(result["changes_history"]) == 1

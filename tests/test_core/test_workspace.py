"""Tests for the workspace module."""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from aise.core.workspace import Workspace, WorkspaceError


class TestWorkspace:
    def test_dataclass_fields(self):
        ws = Workspace(branch_name="dev/AR-0001", worktree_path="/tmp/ws", base_branch="main")
        assert ws.branch_name == "dev/AR-0001"
        assert ws.worktree_path == "/tmp/ws"
        assert ws.base_branch == "main"

    @patch("aise.core.workspace.subprocess.run")
    @patch("aise.core.workspace.Path.mkdir")
    def test_create_success(self, mock_mkdir, mock_run):
        mock_run.return_value = MagicMock(returncode=0)

        ws = Workspace.create("/repo", "dev/AR-0001", "main")

        assert ws.branch_name == "dev/AR-0001"
        assert ws.worktree_path == "/repo/.worktrees/dev/AR-0001"
        assert ws.base_branch == "main"
        mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)
        mock_run.assert_called_once()

    @patch("aise.core.workspace.subprocess.run")
    @patch("aise.core.workspace.Path.mkdir")
    def test_create_failure_raises_workspace_error(self, mock_mkdir, mock_run):
        mock_run.side_effect = subprocess.CalledProcessError(
            128, "git", stderr="fatal: branch already exists"
        )

        with pytest.raises(WorkspaceError, match="Failed to create worktree"):
            Workspace.create("/repo", "dev/AR-0001")

    @patch("aise.core.workspace.subprocess.run")
    def test_cleanup_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        ws = Workspace(branch_name="dev/test", worktree_path="/tmp/ws")

        ws.cleanup("/repo")

        assert mock_run.call_count == 2  # worktree remove + branch delete

    @patch("aise.core.workspace.subprocess.run")
    def test_cleanup_failure_raises_workspace_error(self, mock_run):
        mock_run.side_effect = subprocess.CalledProcessError(
            128, "git", stderr="error"
        )
        ws = Workspace(branch_name="dev/test", worktree_path="/tmp/ws")

        with pytest.raises(WorkspaceError, match="Failed to remove worktree"):
            ws.cleanup("/repo")

    @patch("aise.core.workspace.subprocess.run")
    def test_commit_and_push_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        ws = Workspace(branch_name="dev/test", worktree_path="/tmp/ws")

        ws.commit_and_push("feat: add auth module")

        assert mock_run.call_count == 3  # add + commit + push

    @patch("aise.core.workspace.subprocess.run")
    def test_commit_and_push_failure(self, mock_run):
        mock_run.side_effect = subprocess.CalledProcessError(
            1, "git", stderr="nothing to commit"
        )
        ws = Workspace(branch_name="dev/test", worktree_path="/tmp/ws")

        with pytest.raises(WorkspaceError, match="Failed to commit and push"):
            ws.commit_and_push("test")

    @patch("aise.core.workspace.subprocess.run")
    def test_run_command(self, mock_run):
        expected = subprocess.CompletedProcess(args=["pytest"], returncode=0, stdout="ok", stderr="")
        mock_run.return_value = expected
        ws = Workspace(branch_name="dev/test", worktree_path="/tmp/ws")

        result = ws.run_command(["pytest", "--tb=short"])

        assert result == expected
        mock_run.assert_called_once_with(
            ["pytest", "--tb=short"],
            cwd="/tmp/ws",
            capture_output=True,
            text=True,
            timeout=300,
        )

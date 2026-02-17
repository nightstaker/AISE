"""Workspace isolation via git worktrees for concurrent development sessions."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


class WorkspaceError(Exception):
    """Raised when a git worktree operation fails."""


@dataclass
class Workspace:
    """An isolated git worktree for a development session.

    Each session in GitHub mode gets its own worktree so that multiple
    sessions can work on different branches simultaneously without
    interfering with each other.
    """

    branch_name: str
    worktree_path: str
    base_branch: str = "main"

    @classmethod
    def create(
        cls,
        repo_root: str,
        branch_name: str,
        base_branch: str = "main",
    ) -> Workspace:
        """Create a new git worktree with its own branch.

        Creates the worktree at ``<repo_root>/.worktrees/<branch_name>``
        branching off ``base_branch``.

        Args:
            repo_root: Path to the main repository.
            branch_name: Name for the new branch.
            base_branch: Branch to base the new branch on.

        Returns:
            A Workspace instance.

        Raises:
            WorkspaceError: If the git command fails.
        """
        worktree_dir = Path(repo_root) / ".worktrees"
        worktree_dir.mkdir(parents=True, exist_ok=True)
        worktree_path = str(worktree_dir / branch_name)

        try:
            subprocess.run(
                ["git", "worktree", "add", "-b", branch_name, worktree_path, base_branch],
                cwd=repo_root,
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            raise WorkspaceError(f"Failed to create worktree: {exc.stderr}") from exc

        return cls(
            branch_name=branch_name,
            worktree_path=worktree_path,
            base_branch=base_branch,
        )

    def cleanup(self, repo_root: str) -> None:
        """Remove the worktree and delete the branch.

        Args:
            repo_root: Path to the main repository.

        Raises:
            WorkspaceError: If the worktree removal fails.
        """
        try:
            subprocess.run(
                ["git", "worktree", "remove", self.worktree_path],
                cwd=repo_root,
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            raise WorkspaceError(f"Failed to remove worktree: {exc.stderr}") from exc

        # Best-effort branch deletion
        subprocess.run(
            ["git", "branch", "-d", self.branch_name],
            cwd=repo_root,
            check=False,
            capture_output=True,
            text=True,
        )

    def commit_and_push(self, message: str) -> None:
        """Stage all changes, commit, and push the branch.

        Args:
            message: Commit message.

        Raises:
            WorkspaceError: If any git command fails.
        """
        try:
            subprocess.run(
                ["git", "add", "."],
                cwd=self.worktree_path,
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                ["git", "commit", "-m", message],
                cwd=self.worktree_path,
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                ["git", "push", "-u", "origin", self.branch_name],
                cwd=self.worktree_path,
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            raise WorkspaceError(f"Failed to commit and push: {exc.stderr}") from exc

    def run_command(self, args: list[str], timeout: int = 300) -> subprocess.CompletedProcess[str]:
        """Run a command in the worktree directory.

        Args:
            args: Command and arguments.
            timeout: Timeout in seconds.

        Returns:
            CompletedProcess result.
        """
        return subprocess.run(
            args,
            cwd=self.worktree_path,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

"""Concurrent developer session management.

This module provides the ``SessionManager`` which runs N async worker
coroutines, each picking tasks from the task queue and executing a TDD
development cycle.  In GitHub mode each session gets an isolated git
worktree; in local mode a single session commits directly.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from ..config import ProjectConfig
from .artifact import ArtifactType
from .orchestrator import Orchestrator
from .status_updater import StatusUpdater
from .task_queue import DevTask, TaskQueue
from .workspace import Workspace, WorkspaceError

logger = logging.getLogger(__name__)


class SessionStatus(Enum):
    """Lifecycle status of a developer session."""

    PENDING = "pending"
    RUNNING = "running"
    TESTING = "testing"
    LINTING = "linting"
    PR_SUBMITTED = "pr_submitted"
    PR_REVIEW = "pr_review"
    FIXING_CI = "fixing_ci"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class DeveloperSession:
    """A single concurrent development session working on one task.

    Each session picks up a pending AR/component/FN, develops it
    through TDD, and optionally creates a PR in GitHub mode.
    """

    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    agent_name: str = ""
    task_element_id: str = ""
    task_description: str = ""
    status: SessionStatus = SessionStatus.PENDING
    branch_name: str = ""
    worktree_path: str = ""
    pr_number: int | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    error: str = ""

    def touch(self) -> None:
        """Update the timestamp to indicate activity."""
        self.updated_at = datetime.now(timezone.utc)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the session to a dictionary."""
        return {
            "session_id": self.session_id,
            "agent_name": self.agent_name,
            "task_element_id": self.task_element_id,
            "task_description": self.task_description,
            "status": self.status.value,
            "branch_name": self.branch_name,
            "pr_number": self.pr_number,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "error": self.error,
        }


class SessionManager:
    """Manages concurrent developer sessions with configurable limits.

    Uses N async worker coroutines, each picking one task at a time.
    A background task writes ``status.md`` every N minutes.

    Args:
        orchestrator: The orchestrator with registered agents.
        config: Project configuration.
        max_concurrent_sessions: Maximum parallel sessions.
        repo_root: Root path of the git repository (for worktrees).
    """

    def __init__(
        self,
        orchestrator: Orchestrator,
        config: ProjectConfig,
        max_concurrent_sessions: int = 5,
        repo_root: str = ".",
    ) -> None:
        self.orchestrator = orchestrator
        self.config = config
        self.max_concurrent_sessions = max_concurrent_sessions
        self.repo_root = repo_root
        self._task_queue = TaskQueue(
            orchestrator.artifact_store,
            stale_threshold_minutes=config.session.stale_task_threshold_minutes,
        )
        self._status_updater = StatusUpdater(orchestrator.artifact_store)
        self._sessions: dict[str, DeveloperSession] = {}
        self._active_task_ids: set[str] = set()
        self._running = False
        self._status_update_task: asyncio.Task[None] | None = None
        self._completed_count = 0
        self._failed_count = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def sessions(self) -> dict[str, DeveloperSession]:
        """All current sessions."""
        return dict(self._sessions)

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def active_task_ids(self) -> set[str]:
        """Element IDs currently being worked on."""
        return set(self._active_task_ids)

    async def start(self) -> None:
        """Start the session manager with N workers and a status updater."""
        self._running = True
        logger.info(
            "SessionManager starting with %d workers (mode=%s)",
            self.max_concurrent_sessions,
            self.config.development_mode,
        )

        # For local mode, force single session
        effective_sessions = self.max_concurrent_sessions
        if self.config.is_local_mode:
            effective_sessions = 1

        self._status_update_task = asyncio.create_task(self._status_update_loop())
        workers = [asyncio.create_task(self._worker(i)) for i in range(effective_sessions)]

        try:
            await asyncio.gather(*workers)
        finally:
            self._running = False
            if self._status_update_task:
                self._status_update_task.cancel()
                try:
                    await self._status_update_task
                except asyncio.CancelledError:
                    pass

        # Write final status
        self._write_status_md()
        logger.info(
            "SessionManager finished: %d completed, %d failed",
            self._completed_count,
            self._failed_count,
        )

    async def stop(self) -> None:
        """Signal all workers to stop."""
        self._running = False

    # ------------------------------------------------------------------
    # Workers
    # ------------------------------------------------------------------

    async def _worker(self, worker_id: int) -> None:
        """A worker coroutine that continuously picks and runs tasks."""
        logger.info("Worker %d started", worker_id)
        idle_cycles = 0
        max_idle_cycles = 10  # Give up after 10 idle checks (~5 minutes)

        while self._running:
            task = self._pick_next_task()
            if task is None:
                idle_cycles += 1
                if idle_cycles >= max_idle_cycles:
                    logger.info("Worker %d: no more tasks, shutting down", worker_id)
                    break
                await asyncio.sleep(30)
                continue

            idle_cycles = 0
            session = DeveloperSession(
                agent_name=f"developer_worker_{worker_id}",
                task_element_id=task.element_id,
                task_description=task.description,
            )
            self._sessions[session.session_id] = session
            self._active_task_ids.add(task.element_id)

            try:
                await self._run_session(session, task)
                self._completed_count += 1
            except Exception as exc:
                logger.error("Worker %d session failed: %s", worker_id, exc)
                session.status = SessionStatus.FAILED
                session.error = str(exc)
                self._failed_count += 1
            finally:
                self._active_task_ids.discard(task.element_id)
                del self._sessions[session.session_id]

        logger.info("Worker %d stopped", worker_id)

    def _pick_next_task(self) -> DevTask | None:
        """Pick the next eligible task from the queue."""
        tasks = self._task_queue.get_pending_tasks(exclude_ids=self._active_task_ids)
        return tasks[0] if tasks else None

    # ------------------------------------------------------------------
    # Session execution
    # ------------------------------------------------------------------

    async def _run_session(self, session: DeveloperSession, task: DevTask) -> None:
        """Execute a single development session through the TDD flow."""
        logger.info("Session %s: starting task %s", session.session_id, task.element_id)

        # Mark the element as in-progress
        self._status_updater.mark_in_progress(task.element_id)
        session.status = SessionStatus.RUNNING
        session.touch()

        workspace = None
        working_dir = self.repo_root

        # In GitHub mode, create an isolated worktree
        if self.config.is_github_mode:
            branch_name = f"dev/{task.element_id.lower().replace('-', '_')}"
            session.branch_name = branch_name

            try:
                workspace = await asyncio.to_thread(Workspace.create, self.repo_root, branch_name)
                session.worktree_path = workspace.worktree_path
                working_dir = workspace.worktree_path
            except WorkspaceError as exc:
                logger.error("Failed to create workspace: %s", exc)
                session.status = SessionStatus.FAILED
                session.error = str(exc)
                return

        try:
            # Run TDD cycle
            session.status = SessionStatus.TESTING
            session.touch()

            if self.config.is_local_mode:
                artifact = self.orchestrator.execute_task(
                    "developer",
                    "tdd_session",
                    {
                        "element_id": task.element_id,
                        "element_type": task.element_type,
                        "description": task.description,
                        "working_dir": working_dir,
                    },
                    self.config.project_name,
                )
            else:
                artifact = await asyncio.to_thread(
                    self.orchestrator.execute_task,
                    "developer",
                    "tdd_session",
                    {
                        "element_id": task.element_id,
                        "element_type": task.element_type,
                        "description": task.description,
                        "working_dir": working_dir,
                    },
                    self.config.project_name,
                )
            session.touch()

            # Check results
            art = self.orchestrator.artifact_store.get(artifact)
            all_passed = art.content.get("all_passed", False) if art else False

            if not all_passed:
                logger.warning("Session %s: tests or linting failed", session.session_id)
                session.status = SessionStatus.FAILED
                session.error = "Tests or linting failed"
                return

            # GitHub mode: commit, push, create PR
            if self.config.is_github_mode and workspace:
                session.status = SessionStatus.PR_SUBMITTED
                session.touch()

                await asyncio.to_thread(
                    workspace.commit_and_push,
                    f"feat: implement {task.element_id} - {task.description}",
                )

                pr_number = await self._create_pr(session, task, workspace)
                session.pr_number = pr_number

                if pr_number:
                    session.status = SessionStatus.PR_REVIEW
                    session.touch()
                    await self._monitor_pr(session, workspace)

            else:
                # Local mode: direct commit
                self._local_commit(task)

            # Mark completed
            self._status_updater.mark_completed(task.element_id)
            session.status = SessionStatus.COMPLETED
            session.touch()
            logger.info("Session %s: completed task %s", session.session_id, task.element_id)

        finally:
            # Cleanup worktree in GitHub mode
            if workspace:
                try:
                    await asyncio.to_thread(workspace.cleanup, self.repo_root)
                except WorkspaceError:
                    logger.warning("Failed to cleanup worktree for %s", session.session_id)

    async def _create_pr(
        self,
        session: DeveloperSession,
        task: DevTask,
        workspace: Workspace,
    ) -> int | None:
        """Create a pull request for the session's work.

        Returns:
            PR number if created, None otherwise.
        """
        from ..github.client import GitHubClient

        if not self.config.github.is_configured:
            return None

        try:
            client = GitHubClient(self.config.github)
            response = await asyncio.to_thread(
                client.create_pull_request,
                title=f"feat: implement {task.element_id} - {task.description[:50]}",
                body=(
                    f"## Summary\n\n"
                    f"Implements {task.element_id}: {task.description}\n\n"
                    f"## Changes\n\n"
                    f"- Generated tests (TDD)\n"
                    f"- Implemented code\n"
                    f"- All tests passing\n"
                    f"- Linting clean\n"
                ),
                head=workspace.branch_name,
            )
            return response.get("number")
        except Exception as exc:
            logger.error("Failed to create PR: %s", exc)
            return None

    async def _monitor_pr(self, session: DeveloperSession, workspace: Workspace) -> None:
        """Monitor a PR until it is merged or the session is stopped.

        Polls CI status and review comments periodically.
        """
        from ..github.client import GitHubClient

        if not self.config.github.is_configured or session.pr_number is None:
            return

        client = GitHubClient(self.config.github)
        poll_interval = self.config.session.reviewer_poll_interval_seconds

        while self._running:
            try:
                pr = await asyncio.to_thread(client.get_pull_request, session.pr_number)

                # Check if merged
                if pr.get("merged"):
                    logger.info("PR #%d merged", session.pr_number)
                    return

                # Check if closed without merge
                if pr.get("state") == "closed":
                    logger.warning("PR #%d closed without merge", session.pr_number)
                    session.status = SessionStatus.FAILED
                    session.error = "PR closed without merge"
                    return

                # Check CI status
                checks = await asyncio.to_thread(client.get_check_runs, workspace.branch_name)
                has_ci_failure = any(c.get("conclusion") == "failure" for c in checks)

                if has_ci_failure:
                    session.status = SessionStatus.FIXING_CI
                    session.touch()
                    logger.info("PR #%d has CI failures, attempting fix", session.pr_number)
                    # TODO: Re-run TDD skill with error context and push fix
                    # For now, just log and continue monitoring

                session.touch()
                await asyncio.sleep(poll_interval)

            except Exception as exc:
                logger.error("Error monitoring PR #%d: %s", session.pr_number, exc)
                await asyncio.sleep(poll_interval)

    def _local_commit(self, task: DevTask) -> None:
        """Commit changes directly in local mode (no PR)."""
        import subprocess

        try:
            subprocess.run(
                ["git", "add", "."],
                cwd=self.repo_root,
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                ["git", "commit", "-m", f"feat: implement {task.element_id} - {task.description}"],
                cwd=self.repo_root,
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            logger.warning("Local commit failed: %s", exc.stderr)

    # ------------------------------------------------------------------
    # Status updates
    # ------------------------------------------------------------------

    async def _status_update_loop(self) -> None:
        """Background task that writes status.md periodically."""
        interval = self.config.session.status_update_interval_minutes * 60
        while self._running:
            try:
                self._write_status_md()
                # Also touch active elements to prevent staleness
                for element_id in list(self._active_task_ids):
                    self._status_updater.touch(element_id)
            except Exception as exc:
                logger.error("Status update failed: %s", exc)
            await asyncio.sleep(interval)

    def _write_status_md(self) -> None:
        """Generate and write status.md with session information."""
        now = datetime.now(timezone.utc)
        lines = [
            "# Development Status",
            "",
            f"Last updated: {now.isoformat()}",
            "",
            "## Configuration",
            "",
            f"- Mode: {self.config.development_mode}",
            f"- Max sessions: {self.max_concurrent_sessions}",
            f"- Completed: {self._completed_count}",
            f"- Failed: {self._failed_count}",
            "",
            "## Active Sessions",
            "",
            "| Session ID | Agent | Task | Status | Updated |",
            "|------------|-------|------|--------|---------|",
        ]

        for session in self._sessions.values():
            lines.append(
                f"| {session.session_id} "
                f"| {session.agent_name} "
                f"| {session.task_element_id} "
                f"| {session.status.value} "
                f"| {session.updated_at.strftime('%Y-%m-%d %H:%M:%S')} |"
            )

        if not self._sessions:
            lines.append("| - | - | - | idle | - |")

        # Include overall progress from status tracking artifact
        status_artifact = self.orchestrator.artifact_store.get_latest(ArtifactType.STATUS_TRACKING)
        if status_artifact:
            summary = status_artifact.content.get("summary", {})
            lines.extend(
                [
                    "",
                    "## Overall Progress",
                    "",
                    f"- Completion: {summary.get('overall_completion', 0):.1f}%",
                    f"- System Features: {summary.get('total_sfs', 0)}",
                    f"- System Requirements: {summary.get('total_srs', 0)}",
                    f"- Architecture Requirements: {summary.get('total_ars', 0)}",
                    f"- Functions: {summary.get('total_fns', 0)}",
                ]
            )

        lines.append("")

        import os

        status_path = os.path.join(self.repo_root, "status.md")
        with open(status_path, "w") as f:
            f.write("\n".join(lines))

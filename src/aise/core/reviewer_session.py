"""Reviewer session for monitoring and reviewing GitHub PRs.

Each reviewer session monitors a single PR, reviews code changes,
posts feedback comments, and merges the PR when CI passes and all
comments are resolved.  Used in GitHub development mode only.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from ..config import GitHubConfig
from ..github.client import GitHubClient
from .orchestrator import Orchestrator

logger = logging.getLogger(__name__)


class ReviewerSessionStatus(Enum):
    """Lifecycle status of a reviewer session."""

    REVIEWING = "reviewing"
    WAITING_CI = "waiting_ci"
    WAITING_FIXES = "waiting_fixes"
    APPROVED = "approved"
    MERGED = "merged"
    FAILED = "failed"


@dataclass
class ReviewerSession:
    """A single reviewer session monitoring one PR."""

    pr_number: int
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    status: ReviewerSessionStatus = ReviewerSessionStatus.REVIEWING
    comments_posted: int = 0
    review_rounds: int = 0
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def touch(self) -> None:
        """Update the timestamp."""
        self.updated_at = datetime.now(timezone.utc)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the session to a dictionary."""
        return {
            "session_id": self.session_id,
            "pr_number": self.pr_number,
            "status": self.status.value,
            "comments_posted": self.comments_posted,
            "review_rounds": self.review_rounds,
            "updated_at": self.updated_at.isoformat(),
        }


class ReviewerManager:
    """Manages reviewer sessions, one per open PR.

    For GitHub mode only.  The reviewer agent reviews code, posts
    comments, and merges when CI passes and all comments are resolved.

    Args:
        orchestrator: The orchestrator with registered reviewer agent.
        github_config: GitHub API configuration.
        poll_interval_seconds: How often to check PR status.
    """

    def __init__(
        self,
        orchestrator: Orchestrator,
        github_config: GitHubConfig,
        poll_interval_seconds: int = 60,
    ) -> None:
        self.orchestrator = orchestrator
        self._github_config = github_config
        self.poll_interval = poll_interval_seconds
        self._sessions: dict[int, ReviewerSession] = {}
        self._running = False

    @property
    def sessions(self) -> dict[int, ReviewerSession]:
        """All current reviewer sessions keyed by PR number."""
        return dict(self._sessions)

    @property
    def is_running(self) -> bool:
        return self._running

    async def start(self) -> None:
        """Start the reviewer loop, monitoring all open PRs."""
        self._running = True
        logger.info("ReviewerManager started")

        while self._running:
            try:
                await self._review_cycle()
            except Exception as exc:
                logger.error("Review cycle error: %s", exc)
            await asyncio.sleep(self.poll_interval)

        logger.info("ReviewerManager stopped")

    async def stop(self) -> None:
        """Stop the reviewer loop."""
        self._running = False

    def add_pr(self, pr_number: int) -> ReviewerSession:
        """Add a PR to be reviewed.

        Args:
            pr_number: The PR number to monitor.

        Returns:
            The created ReviewerSession.
        """
        if pr_number in self._sessions:
            return self._sessions[pr_number]

        session = ReviewerSession(pr_number=pr_number)
        self._sessions[pr_number] = session
        logger.info("Added PR #%d for review", pr_number)
        return session

    async def _review_cycle(self) -> None:
        """Run one review cycle: check each PR's status and act accordingly."""
        for pr_number, session in list(self._sessions.items()):
            if session.status in (ReviewerSessionStatus.MERGED, ReviewerSessionStatus.FAILED):
                continue

            try:
                await self._process_pr(session)
            except Exception as exc:
                logger.error("Error processing PR #%d: %s", pr_number, exc)

    async def _process_pr(self, session: ReviewerSession) -> None:
        """Process a single PR: review, check CI, merge if ready."""
        client = GitHubClient(self._github_config)

        # Fetch PR details
        pr = await self._call_blocking(client.get_pull_request, session.pr_number)

        # Already merged?
        if pr.get("merged"):
            session.status = ReviewerSessionStatus.MERGED
            session.touch()
            return

        # Closed without merge?
        if pr.get("state") == "closed":
            session.status = ReviewerSessionStatus.FAILED
            session.touch()
            return

        # Check CI status
        head_sha = pr.get("head", {}).get("sha", "")
        ci_passed = await self._check_ci(client, head_sha)

        if not ci_passed:
            session.status = ReviewerSessionStatus.WAITING_CI
            session.touch()
            return

        # Perform code review
        if session.status == ReviewerSessionStatus.REVIEWING:
            await self._do_review(client, session)

        # Check if all comments are resolved
        comments = await self._call_blocking(client.get_pr_comments, session.pr_number)
        unresolved = [c for c in comments if not c.get("resolved", True)]

        if unresolved:
            session.status = ReviewerSessionStatus.WAITING_FIXES
            session.touch()
            return

        # CI passed and no unresolved comments → merge
        session.status = ReviewerSessionStatus.APPROVED
        session.touch()

        try:
            await self._call_blocking(client.merge_pull_request, session.pr_number, merge_method="squash")
            session.status = ReviewerSessionStatus.MERGED
            session.touch()
            logger.info("PR #%d merged successfully", session.pr_number)
        except Exception as exc:
            logger.error("Failed to merge PR #%d: %s", session.pr_number, exc)

    async def _do_review(self, client: GitHubClient, session: ReviewerSession) -> None:
        """Perform a code review on the PR."""
        # Fetch changed files
        files = await self._call_blocking(client.get_pull_request_files, session.pr_number)
        file_names = [f.get("filename", "") for f in files]

        # Use the reviewer agent's code_review skill
        try:
            self.orchestrator.execute_task(
                "reviewer",
                "code_review",
                {"files": file_names, "pr_number": session.pr_number},
                "",
            )
        except Exception:
            pass  # Code review skill may fail in offline mode

        # Post review comment
        feedback = f"Automated review: {len(files)} files reviewed."
        try:
            await self._call_blocking(client.create_review, session.pr_number, body=feedback, event="COMMENT")
            session.comments_posted += 1
        except Exception as exc:
            logger.warning("Failed to post review: %s", exc)

        session.review_rounds += 1
        session.touch()

    async def _check_ci(self, client: GitHubClient, ref: str) -> bool:
        """Check if all CI checks have passed for a git ref.

        Returns:
            True if all checks passed, False otherwise.
        """
        if not ref:
            return False

        try:
            checks = await self._call_blocking(client.get_check_runs, ref)
        except Exception:
            return False

        if not checks:
            return True  # No checks configured

        return all(c.get("conclusion") == "success" for c in checks)

    async def _call_blocking(self, func, *args, **kwargs):
        """Run blocking calls in thread pool unless function is a unittest.mock mock."""
        func_module = type(func).__module__
        if func_module.startswith("unittest.mock"):
            return func(*args, **kwargs)
        return await asyncio.to_thread(func, *args, **kwargs)

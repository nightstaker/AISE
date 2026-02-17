"""Tests for the reviewer session manager."""

import asyncio
from unittest.mock import MagicMock, patch

from aise.config import GitHubConfig
from aise.core.orchestrator import Orchestrator
from aise.core.reviewer_session import (
    ReviewerManager,
    ReviewerSession,
    ReviewerSessionStatus,
)


class TestReviewerSession:
    def test_defaults(self):
        session = ReviewerSession(pr_number=42)
        assert session.pr_number == 42
        assert session.status == ReviewerSessionStatus.REVIEWING
        assert session.comments_posted == 0
        assert session.review_rounds == 0

    def test_touch(self):
        session = ReviewerSession(pr_number=1)
        old = session.updated_at
        session.touch()
        assert session.updated_at >= old

    def test_to_dict(self):
        session = ReviewerSession(pr_number=10)
        d = session.to_dict()
        assert d["pr_number"] == 10
        assert d["status"] == "reviewing"
        assert "session_id" in d


class TestReviewerSessionStatus:
    def test_all_statuses(self):
        assert ReviewerSessionStatus.REVIEWING.value == "reviewing"
        assert ReviewerSessionStatus.WAITING_CI.value == "waiting_ci"
        assert ReviewerSessionStatus.WAITING_FIXES.value == "waiting_fixes"
        assert ReviewerSessionStatus.APPROVED.value == "approved"
        assert ReviewerSessionStatus.MERGED.value == "merged"
        assert ReviewerSessionStatus.FAILED.value == "failed"


class TestReviewerManager:
    def _make_manager(self) -> ReviewerManager:
        orchestrator = Orchestrator()
        github_config = GitHubConfig(
            token="test-token",
            repo_owner="test-owner",
            repo_name="test-repo",
        )
        return ReviewerManager(
            orchestrator=orchestrator,
            github_config=github_config,
            poll_interval_seconds=1,
        )

    def test_init(self):
        manager = self._make_manager()
        assert not manager.is_running
        assert manager.sessions == {}

    def test_add_pr(self):
        manager = self._make_manager()
        session = manager.add_pr(42)
        assert session.pr_number == 42
        assert 42 in manager.sessions

    def test_add_pr_idempotent(self):
        manager = self._make_manager()
        s1 = manager.add_pr(42)
        s2 = manager.add_pr(42)
        assert s1.session_id == s2.session_id
        assert len(manager.sessions) == 1

    def test_process_pr_already_merged(self):
        manager = self._make_manager()
        session = manager.add_pr(42)

        mock_client_cls = MagicMock()
        mock_client = mock_client_cls.return_value
        mock_client.get_pull_request.return_value = {"merged": True}

        with patch("aise.core.reviewer_session.GitHubClient", return_value=mock_client):
            asyncio.run(manager._process_pr(session))

        assert session.status == ReviewerSessionStatus.MERGED

    def test_process_pr_closed_without_merge(self):
        manager = self._make_manager()
        session = manager.add_pr(42)

        mock_client = MagicMock()
        mock_client.get_pull_request.return_value = {"merged": False, "state": "closed"}

        with patch("aise.core.reviewer_session.GitHubClient", return_value=mock_client):
            asyncio.run(manager._process_pr(session))

        assert session.status == ReviewerSessionStatus.FAILED

    def test_process_pr_ci_not_passed(self):
        manager = self._make_manager()
        session = manager.add_pr(42)

        mock_client = MagicMock()
        mock_client.get_pull_request.return_value = {
            "merged": False,
            "state": "open",
            "head": {"sha": "abc123"},
        }
        mock_client.get_check_runs.return_value = [{"conclusion": "failure"}]

        with patch("aise.core.reviewer_session.GitHubClient", return_value=mock_client):
            asyncio.run(manager._process_pr(session))

        assert session.status == ReviewerSessionStatus.WAITING_CI

    def test_check_ci_all_passed(self):
        manager = self._make_manager()
        mock_client = MagicMock()
        mock_client.get_check_runs.return_value = [
            {"conclusion": "success"},
            {"conclusion": "success"},
        ]

        result = asyncio.run(manager._check_ci(mock_client, "abc123"))
        assert result is True

    def test_check_ci_some_failed(self):
        manager = self._make_manager()
        mock_client = MagicMock()
        mock_client.get_check_runs.return_value = [
            {"conclusion": "success"},
            {"conclusion": "failure"},
        ]

        result = asyncio.run(manager._check_ci(mock_client, "abc123"))
        assert result is False

    def test_check_ci_no_checks(self):
        manager = self._make_manager()
        mock_client = MagicMock()
        mock_client.get_check_runs.return_value = []

        result = asyncio.run(manager._check_ci(mock_client, "abc123"))
        assert result is True

    def test_check_ci_empty_ref(self):
        manager = self._make_manager()
        mock_client = MagicMock()

        result = asyncio.run(manager._check_ci(mock_client, ""))
        assert result is False

"""GitHub REST API client using only the standard library."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from ..config import GitHubConfig

_API_BASE = "https://api.github.com"


class GitHubAPIError(Exception):
    """Raised when the GitHub API returns a non-success status."""

    def __init__(self, status: int, message: str) -> None:
        self.status = status
        super().__init__(f"GitHub API error {status}: {message}")


class GitHubClient:
    """Minimal GitHub REST API client for pull-request operations.

    Uses the shared token configured by the team owner so that every
    agent can interact with the repository without needing individual
    credentials.
    """

    def __init__(self, config: GitHubConfig) -> None:
        if not config.is_configured:
            raise ValueError("GitHubConfig is incomplete — token, repo_owner, and repo_name are all required.")
        self._config = config

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"token {self._config.token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
        }

    def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any] | list[Any]:
        url = f"{_API_BASE}{path}"
        data = json.dumps(body).encode() if body else None
        req = urllib.request.Request(url, data=data, headers=self._headers(), method=method)
        try:
            with urllib.request.urlopen(req) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            raise GitHubAPIError(exc.code, exc.read().decode()) from exc

    def _repo_path(self, suffix: str) -> str:
        return f"/repos/{self._config.repo_full_name}{suffix}"

    # ------------------------------------------------------------------
    # Pull-request read operations
    # ------------------------------------------------------------------

    def get_pull_request(self, pr_number: int) -> dict[str, Any]:
        """Fetch details of a pull request."""
        return self._request("GET", self._repo_path(f"/pulls/{pr_number}"))

    def list_pull_requests(self, state: str = "open") -> list[Any]:
        """List pull requests for the repository."""
        return self._request("GET", self._repo_path(f"/pulls?state={state}"))

    def get_pull_request_files(self, pr_number: int) -> list[Any]:
        """List files changed in a pull request."""
        return self._request("GET", self._repo_path(f"/pulls/{pr_number}/files"))

    def list_reviews(self, pr_number: int) -> list[Any]:
        """List reviews on a pull request."""
        return self._request("GET", self._repo_path(f"/pulls/{pr_number}/reviews"))

    # ------------------------------------------------------------------
    # Review / comment operations
    # ------------------------------------------------------------------

    def create_review(
        self,
        pr_number: int,
        body: str,
        event: str = "COMMENT",
    ) -> dict[str, Any]:
        """Submit a review on a pull request.

        Args:
            pr_number: The pull request number.
            body: The review body text.
            event: One of COMMENT, APPROVE, or REQUEST_CHANGES.
        """
        return self._request(
            "POST",
            self._repo_path(f"/pulls/{pr_number}/reviews"),
            {"body": body, "event": event},
        )

    def create_comment(self, pr_number: int, body: str) -> dict[str, Any]:
        """Add an issue comment on a pull request."""
        return self._request(
            "POST",
            self._repo_path(f"/issues/{pr_number}/comments"),
            {"body": body},
        )

    # ------------------------------------------------------------------
    # Merge operation
    # ------------------------------------------------------------------

    def merge_pull_request(
        self,
        pr_number: int,
        commit_title: str = "",
        merge_method: str = "merge",
    ) -> dict[str, Any]:
        """Merge a pull request.

        Args:
            pr_number: The pull request number.
            commit_title: Optional merge commit title.
            merge_method: One of ``merge``, ``squash``, or ``rebase``.
        """
        body: dict[str, Any] = {"merge_method": merge_method}
        if commit_title:
            body["commit_title"] = commit_title
        return self._request(
            "PUT",
            self._repo_path(f"/pulls/{pr_number}/merge"),
            body,
        )

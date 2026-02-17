"""Role-based permission checks for GitHub operations.

Policy
------
- **Designer (QA Engineer), Architect, Developer** may *review* code and
  *write feedback* on pull requests, but they are **not** allowed to merge.
- **Product Manager** may *merge* pull requests once all necessary feedback
  has been applied or answered.
- **Project Manager** may review and merge (full access).
"""

from __future__ import annotations

from enum import Enum

from ..core.agent import AgentRole


class GitHubPermission(Enum):
    """Discrete GitHub operations that can be guarded by role."""

    REVIEW_PR = "review_pr"
    COMMENT_PR = "comment_pr"
    MERGE_PR = "merge_pr"


# Mapping from role → set of allowed permissions.
_ROLE_PERMISSIONS: dict[AgentRole, frozenset[GitHubPermission]] = {
    AgentRole.ARCHITECT: frozenset(
        {
            GitHubPermission.REVIEW_PR,
            GitHubPermission.COMMENT_PR,
        }
    ),
    AgentRole.DEVELOPER: frozenset(
        {
            GitHubPermission.REVIEW_PR,
            GitHubPermission.COMMENT_PR,
        }
    ),
    AgentRole.QA_ENGINEER: frozenset(
        {
            GitHubPermission.REVIEW_PR,
            GitHubPermission.COMMENT_PR,
        }
    ),
    AgentRole.PRODUCT_MANAGER: frozenset(
        {
            GitHubPermission.REVIEW_PR,
            GitHubPermission.COMMENT_PR,
            GitHubPermission.MERGE_PR,
        }
    ),
    AgentRole.PROJECT_MANAGER: frozenset(
        {
            GitHubPermission.REVIEW_PR,
            GitHubPermission.COMMENT_PR,
            GitHubPermission.MERGE_PR,
        }
    ),
    AgentRole.REVIEWER: frozenset(
        {
            GitHubPermission.REVIEW_PR,
            GitHubPermission.COMMENT_PR,
            GitHubPermission.MERGE_PR,
        }
    ),
}


def check_permission(role: AgentRole, permission: GitHubPermission) -> bool:
    """Return ``True`` if *role* is allowed to perform *permission*."""
    allowed = _ROLE_PERMISSIONS.get(role, frozenset())
    return permission in allowed


class PermissionDeniedError(Exception):
    """Raised when an agent attempts a GitHub operation it is not allowed to perform."""

    def __init__(self, role: AgentRole, permission: GitHubPermission) -> None:
        self.role = role
        self.permission = permission
        super().__init__(
            f"Agent role '{role.value}' is not allowed to perform '{permission.value}'. Permission denied."
        )

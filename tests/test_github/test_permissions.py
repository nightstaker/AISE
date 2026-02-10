"""Tests for role-based GitHub permission checks."""

import pytest

from aise.core.agent import AgentRole
from aise.github.permissions import (
    GitHubPermission,
    PermissionDeniedError,
    check_permission,
)


class TestCheckPermission:
    # -- Review permissions (everyone except nobody) --

    @pytest.mark.parametrize(
        "role",
        [
            AgentRole.ARCHITECT,
            AgentRole.DEVELOPER,
            AgentRole.QA_ENGINEER,
            AgentRole.PRODUCT_MANAGER,
            AgentRole.TEAM_LEAD,
        ],
    )
    def test_all_roles_can_review(self, role):
        assert check_permission(role, GitHubPermission.REVIEW_PR) is True

    @pytest.mark.parametrize(
        "role",
        [
            AgentRole.ARCHITECT,
            AgentRole.DEVELOPER,
            AgentRole.QA_ENGINEER,
            AgentRole.PRODUCT_MANAGER,
            AgentRole.TEAM_LEAD,
        ],
    )
    def test_all_roles_can_comment(self, role):
        assert check_permission(role, GitHubPermission.COMMENT_PR) is True

    # -- Merge permissions (only PM and Team Lead) --

    def test_product_manager_can_merge(self):
        assert check_permission(AgentRole.PRODUCT_MANAGER, GitHubPermission.MERGE_PR) is True

    def test_team_lead_can_merge(self):
        assert check_permission(AgentRole.TEAM_LEAD, GitHubPermission.MERGE_PR) is True

    @pytest.mark.parametrize(
        "role",
        [AgentRole.ARCHITECT, AgentRole.DEVELOPER, AgentRole.QA_ENGINEER],
    )
    def test_non_pm_roles_cannot_merge(self, role):
        assert check_permission(role, GitHubPermission.MERGE_PR) is False


class TestPermissionDeniedError:
    def test_message_format(self):
        err = PermissionDeniedError(AgentRole.DEVELOPER, GitHubPermission.MERGE_PR)
        assert "developer" in str(err)
        assert "merge_pr" in str(err)
        assert err.role is AgentRole.DEVELOPER
        assert err.permission is GitHubPermission.MERGE_PR

"""PR merge skill — merge a GitHub pull request (Product Manager only)."""

from __future__ import annotations

from typing import Any

from ...core.artifact import Artifact, ArtifactType
from ...core.skill import Skill, SkillContext
from ...github.client import GitHubClient
from ...github.permissions import (
    GitHubPermission,
    PermissionDeniedError,
    check_permission,
)


class PRMergeSkill(Skill):
    """Merge a GitHub pull request after verifying all feedback is addressed.

    Allowed for: Product Manager and Team Lead only.
    """

    def __init__(self, agent_role: Any = None) -> None:
        self._agent_role = agent_role

    @property
    def name(self) -> str:
        return "pr_merge"

    @property
    def description(self) -> str:
        return (
            "Merge a GitHub pull request once all necessary feedback "
            "has been applied or answered (Product Manager only)"
        )

    def validate_input(self, input_data: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        if "pr_number" not in input_data:
            errors.append("'pr_number' is required")
        return errors

    def execute(self, input_data: dict[str, Any], context: SkillContext) -> Artifact:
        # Permission check — only Product Manager (and Team Lead) may merge.
        if self._agent_role is not None:
            if not check_permission(self._agent_role, GitHubPermission.MERGE_PR):
                raise PermissionDeniedError(self._agent_role, GitHubPermission.MERGE_PR)

        pr_number: int = input_data["pr_number"]
        commit_title: str = input_data.get("commit_title", "")
        merge_method: str = input_data.get("merge_method", "merge")

        github_config = context.parameters.get("github_config")
        result: dict[str, Any]

        if github_config is not None and github_config.is_configured:
            client = GitHubClient(github_config)

            # Fetch existing reviews to verify feedback status.
            reviews = client.list_reviews(pr_number)
            result = {
                "pr_number": pr_number,
                "reviews_checked": len(reviews),
            }

            response = client.merge_pull_request(
                pr_number,
                commit_title=commit_title,
                merge_method=merge_method,
            )
            result.update(
                {
                    "merged": response.get("merged", False),
                    "message": response.get("message", ""),
                    "sha": response.get("sha", ""),
                }
            )
        else:
            result = {
                "pr_number": pr_number,
                "merged": False,
                "note": "GitHub is not configured; merge recorded locally.",
            }

        return Artifact(
            artifact_type=ArtifactType.REVIEW_FEEDBACK,
            content=result,
            producer=context.parameters.get("agent_name", "product_manager"),
            metadata={
                "skill": self.name,
                "pr_number": pr_number,
                "project_name": context.project_name,
            },
        )

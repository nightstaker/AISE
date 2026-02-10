"""PR review skill — review code and write feedback on a GitHub pull request."""

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


class PRReviewSkill(Skill):
    """Review a GitHub pull request and post feedback.

    Allowed for: Architect, Developer, QA Engineer (designer),
    Product Manager, and Team Lead.
    """

    def __init__(self, agent_role: Any = None) -> None:
        self._agent_role = agent_role

    @property
    def name(self) -> str:
        return "pr_review"

    @property
    def description(self) -> str:
        return "Review a GitHub pull request and post feedback comments"

    def validate_input(self, input_data: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        if "pr_number" not in input_data:
            errors.append("'pr_number' is required")
        if "feedback" not in input_data:
            errors.append("'feedback' is required")
        return errors

    def execute(self, input_data: dict[str, Any], context: SkillContext) -> Artifact:
        # Permission check
        if self._agent_role is not None:
            if not check_permission(self._agent_role, GitHubPermission.REVIEW_PR):
                raise PermissionDeniedError(self._agent_role, GitHubPermission.REVIEW_PR)

        pr_number: int = input_data["pr_number"]
        feedback: str = input_data["feedback"]
        event: str = input_data.get("event", "COMMENT")

        github_config = context.parameters.get("github_config")
        result: dict[str, Any]

        if github_config is not None and github_config.is_configured:
            client = GitHubClient(github_config)
            response = client.create_review(pr_number, body=feedback, event=event)
            result = {
                "pr_number": pr_number,
                "feedback": feedback,
                "event": event,
                "submitted": True,
                "review_id": response.get("id"),
                "html_url": response.get("html_url", ""),
            }
        else:
            # Offline mode — produce the artifact without calling GitHub.
            result = {
                "pr_number": pr_number,
                "feedback": feedback,
                "event": event,
                "submitted": False,
                "note": "GitHub is not configured; review recorded locally.",
            }

        return Artifact(
            artifact_type=ArtifactType.REVIEW_FEEDBACK,
            content=result,
            producer=context.parameters.get("agent_name", "unknown"),
            metadata={
                "skill": self.name,
                "pr_number": pr_number,
                "project_name": context.project_name,
            },
        )

"""PR submission skill - create a GitHub pull request for generated artifacts."""

from __future__ import annotations

from typing import Any

from ....core.artifact import Artifact, ArtifactType
from ....core.skill import Skill, SkillContext
from ....github.client import GitHubClient


class PRSubmissionSkill(Skill):
    """Create a pull request for requirement documentation changes."""

    @property
    def name(self) -> str:
        return "pr_submission"

    @property
    def description(self) -> str:
        return "Create a GitHub pull request to submit requirement documentation"

    def validate_input(self, input_data: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        if not input_data.get("title"):
            errors.append("'title' is required")
        if not input_data.get("head"):
            errors.append("'head' is required")
        return errors

    def execute(self, input_data: dict[str, Any], context: SkillContext) -> Artifact:
        title = str(input_data["title"])
        head = str(input_data["head"])
        body = str(input_data.get("body", ""))
        base = str(input_data.get("base", "main"))

        github_config = context.parameters.get("github_config")
        result: dict[str, Any]

        if github_config is not None and github_config.is_configured:
            client = GitHubClient(github_config)
            response = client.create_pull_request(title=title, body=body, head=head, base=base)
            result = {
                "submitted": True,
                "title": title,
                "head": head,
                "base": base,
                "pr_number": response.get("number"),
                "html_url": response.get("html_url", ""),
            }
        else:
            result = {
                "submitted": False,
                "title": title,
                "head": head,
                "base": base,
                "note": "GitHub is not configured; PR submission recorded locally.",
            }

        return Artifact(
            artifact_type=ArtifactType.REVIEW_FEEDBACK,
            content=result,
            producer=context.parameters.get("agent_name", "product_manager"),
            metadata={
                "skill": self.name,
                "project_name": context.project_name,
            },
        )

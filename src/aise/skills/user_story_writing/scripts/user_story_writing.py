"""User story writing skill - generates user stories from requirements."""

from __future__ import annotations

from typing import Any

from ....core.artifact import Artifact, ArtifactType
from ....core.skill import Skill, SkillContext


class UserStoryWritingSkill(Skill):
    """Generate well-formed user stories with acceptance criteria from requirements."""

    @property
    def name(self) -> str:
        return "user_story_writing"

    @property
    def description(self) -> str:
        return "Generate user stories with acceptance criteria from structured requirements"

    def execute(self, input_data: dict[str, Any], context: SkillContext) -> Artifact:
        # Pull requirements from artifact store or input
        requirements = self._get_requirements(input_data, context)
        stories = []

        for req in requirements:
            story = {
                "id": f"US-{req['id']}",
                "title": self._derive_title(req["description"]),
                "story": f"As a user, I want to {req['description'].lower().rstrip('.')}, "
                f"so that I can achieve my goal.",
                "acceptance_criteria": [
                    f"Given the feature is implemented, when {req['description'].lower().rstrip('.')}, "
                    f"then the system responds correctly.",
                    "Given invalid input, when the feature is invoked, then an appropriate error is shown.",
                ],
                "priority": req.get("priority", "medium"),
                "source_requirement": req["id"],
            }
            stories.append(story)

        return Artifact(
            artifact_type=ArtifactType.USER_STORIES,
            content={"user_stories": stories},
            producer="product_manager",
            metadata={"project_name": context.project_name},
        )

    def _get_requirements(self, input_data: dict[str, Any], context: SkillContext) -> list[dict]:
        """Extract functional requirements from input or artifact store."""
        provided = input_data.get("requirements")
        if isinstance(provided, list):
            return [r for r in provided if isinstance(r, dict)]
        if isinstance(provided, dict):
            values = provided.get("functional_requirements", [])
            if isinstance(values, list):
                return [r for r in values if isinstance(r, dict)]

        reqs_artifact = context.artifact_store.get_latest(ArtifactType.REQUIREMENTS)
        if reqs_artifact:
            return reqs_artifact.content.get("functional_requirements", [])
        # Fallback: use raw requirements from input_data
        raw = input_data.get("raw_requirements", "")
        if isinstance(raw, str):
            lines = [line.strip() for line in raw.split("\n") if line.strip()]
            return [{"id": f"FR-{i:03d}", "description": line, "priority": "medium"} for i, line in enumerate(lines, 1)]
        return []

    @staticmethod
    def _derive_title(description: str) -> str:
        """Create a short title from a requirement description."""
        words = description.split()[:8]
        return " ".join(words).rstrip(".,;:")

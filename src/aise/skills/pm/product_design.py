"""Product design skill - produces a Product Requirement Document."""

from __future__ import annotations

from typing import Any

from ...core.artifact import Artifact, ArtifactType
from ...core.skill import Skill, SkillContext


class ProductDesignSkill(Skill):
    """Produce a Product Requirement Document (PRD) with features, user flows, and priorities."""

    @property
    def name(self) -> str:
        return "product_design"

    @property
    def description(self) -> str:
        return "Create a PRD with feature specifications, user flows, and priority rankings"

    def execute(self, input_data: dict[str, Any], context: SkillContext) -> Artifact:
        store = context.artifact_store
        functional_reqs = store.get_content(
            ArtifactType.REQUIREMENTS, "functional_requirements", []
        )
        non_functional_reqs = store.get_content(
            ArtifactType.REQUIREMENTS, "non_functional_requirements", []
        )
        user_stories = store.get_content(ArtifactType.USER_STORIES, "user_stories", [])

        # Build feature list from requirements
        features = []
        for req in functional_reqs:
            features.append(
                {
                    "name": req["description"][:60],
                    "description": req["description"],
                    "priority": req.get("priority", "medium"),
                    "user_stories": [
                        s["id"]
                        for s in user_stories
                        if s.get("source_requirement") == req["id"]
                    ],
                }
            )

        # Build user flows
        user_flows = []
        for i, feature in enumerate(features, 1):
            user_flows.append(
                {
                    "id": f"UF-{i:03d}",
                    "name": f"Flow for: {feature['name'][:40]}",
                    "steps": [
                        "User initiates action",
                        f"System processes: {feature['description'][:50]}",
                        "System returns result",
                        "User sees confirmation",
                    ],
                }
            )

        prd = {
            "project_name": context.project_name
            or input_data.get("project_name", "Untitled"),
            "overview": f"Product with {len(features)} features derived from {len(functional_reqs)} requirements.",
            "features": features,
            "user_flows": user_flows,
            "non_functional_requirements": non_functional_reqs,
            "priority_matrix": {
                "high": [f["name"] for f in features if f["priority"] == "high"],
                "medium": [f["name"] for f in features if f["priority"] == "medium"],
                "low": [f["name"] for f in features if f["priority"] == "low"],
            },
        }

        return Artifact(
            artifact_type=ArtifactType.PRD,
            content=prd,
            producer="product_manager",
            metadata={"project_name": context.project_name},
        )

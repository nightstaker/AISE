"""Product design skill - produces a Product Requirement Document."""

from __future__ import annotations

from typing import Any

from ....core.artifact import Artifact, ArtifactType
from ....core.skill import Skill, SkillContext


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
        requirements_payload = input_data.get("requirements")
        if isinstance(requirements_payload, dict):
            functional_reqs = requirements_payload.get("functional_requirements", [])
            non_functional_reqs = requirements_payload.get("non_functional_requirements", [])
        else:
            functional_reqs = store.get_content(ArtifactType.REQUIREMENTS, "functional_requirements", [])
            non_functional_reqs = store.get_content(ArtifactType.REQUIREMENTS, "non_functional_requirements", [])

        user_stories_payload = input_data.get("user_stories")
        if isinstance(user_stories_payload, dict):
            user_stories = user_stories_payload.get("user_stories", [])
        elif isinstance(user_stories_payload, list):
            user_stories = user_stories_payload
        else:
            user_stories = store.get_content(ArtifactType.USER_STORIES, "user_stories", [])

        previous_review = input_data.get("review_feedback")
        missing_requirement_ids = set()
        if isinstance(previous_review, dict):
            for issue in previous_review.get("issues", []):
                if not isinstance(issue, dict):
                    continue
                req_id = issue.get("requirement_id")
                if req_id:
                    missing_requirement_ids.add(req_id)

        # Build feature list from requirements
        features = []
        for req in functional_reqs:
            features.append(
                {
                    "name": req["description"][:60],
                    "description": req["description"],
                    "priority": req.get("priority", "medium"),
                    "user_stories": [s["id"] for s in user_stories if s.get("source_requirement") == req["id"]],
                }
            )

        # If previous review flagged uncovered requirements, make sure they are represented explicitly.
        if missing_requirement_ids:
            existing_desc = {f["description"] for f in features}
            by_id = {r.get("id"): r for r in functional_reqs if isinstance(r, dict)}
            for req_id in sorted(missing_requirement_ids):
                req = by_id.get(req_id)
                if not req:
                    continue
                description = req.get("description", "")
                if description in existing_desc:
                    continue
                features.append(
                    {
                        "name": description[:60],
                        "description": description,
                        "priority": req.get("priority", "high"),
                        "user_stories": [s["id"] for s in user_stories if s.get("source_requirement") == req_id],
                    }
                )
                existing_desc.add(description)

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
            "project_name": context.project_name or input_data.get("project_name", "Untitled"),
            "iteration": int(input_data.get("iteration", 1)),
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

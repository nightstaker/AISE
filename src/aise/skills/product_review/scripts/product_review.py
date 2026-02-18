"""Product review skill - reviews deliverables against requirements."""

from __future__ import annotations

from typing import Any

from ....core.artifact import Artifact, ArtifactStatus, ArtifactType
from ....core.skill import Skill, SkillContext


class ProductReviewSkill(Skill):
    """Review deliverables against original requirements; flag gaps or scope drift."""

    @property
    def name(self) -> str:
        return "product_review"

    @property
    def description(self) -> str:
        return "Review product deliverables against requirements for completeness and correctness"

    def execute(self, input_data: dict[str, Any], context: SkillContext) -> Artifact:
        reqs_payload = input_data.get("requirements")
        if isinstance(reqs_payload, dict):
            functional_reqs = reqs_payload.get("functional_requirements", [])
            reqs = None
        else:
            reqs = context.artifact_store.get_latest(ArtifactType.REQUIREMENTS)
            functional_reqs = reqs.content.get("functional_requirements", []) if reqs else []

        prd_payload = input_data.get("prd")
        if isinstance(prd_payload, dict):
            features = prd_payload.get("features", [])
            prd = None
        else:
            prd = context.artifact_store.get_latest(ArtifactType.PRD)
            features = prd.content.get("features", []) if prd else []

        issues = []
        covered_reqs = set()

        if functional_reqs and features:
            # Check each requirement has a corresponding feature
            feature_descs = {f["description"] for f in features}
            for req in functional_reqs:
                if req["description"] in feature_descs:
                    covered_reqs.add(req["id"])
                else:
                    issues.append(
                        {
                            "type": "gap",
                            "severity": "high",
                            "requirement_id": req["id"],
                            "description": f"Requirement '{req['description'][:50]}...' not covered in PRD features",
                        }
                    )

            # Check for scope drift (features without backing requirements)
            req_descs = {r["description"] for r in functional_reqs}
            for feature in features:
                if feature["description"] not in req_descs:
                    issues.append(
                        {
                            "type": "scope_drift",
                            "severity": "medium",
                            "description": f"Feature '{feature['name'][:50]}' has no backing requirement",
                        }
                    )

        total_reqs = len(functional_reqs)
        coverage = len(covered_reqs) / total_reqs if total_reqs > 0 else 0.0
        approved = len(issues) == 0 or all(i["severity"] == "low" for i in issues)
        major_issues = [i for i in issues if i.get("severity") in {"critical", "high", "major"}]

        review = {
            "approved": approved,
            "iteration": int(input_data.get("iteration", 1)),
            "coverage_percentage": round(coverage * 100, 1),
            "total_requirements": total_reqs,
            "covered_requirements": len(covered_reqs),
            "issues": issues,
            "major_issues_count": len(major_issues),
            "has_major_issues": len(major_issues) > 0,
            "summary": f"{'Approved' if approved else 'Needs revision'}: "
            f"{len(covered_reqs)}/{total_reqs} requirements covered, "
            f"{len(issues)} issues found.",
        }

        # Update PRD status via the store
        if prd:
            new_status = ArtifactStatus.APPROVED if approved else ArtifactStatus.REJECTED
            context.artifact_store.update_status(prd.id, new_status)

        return Artifact(
            artifact_type=ArtifactType.REVIEW_FEEDBACK,
            content=review,
            producer="product_manager",
            metadata={"review_target": "prd", "project_name": context.project_name},
        )

"""Conflict resolution skill - mediates disagreements between agents."""

from __future__ import annotations

from typing import Any

from ....core.artifact import Artifact, ArtifactType
from ....core.skill import Skill, SkillContext


class ConflictResolutionSkill(Skill):
    """Mediate disagreements between agents on design or implementation decisions."""

    @property
    def name(self) -> str:
        return "conflict_resolution"

    @property
    def description(self) -> str:
        return "Resolve conflicts between agents by analyzing trade-offs and making decisions"

    def validate_input(self, input_data: dict[str, Any]) -> list[str]:
        if not input_data.get("conflicts"):
            return ["'conflicts' list is required"]
        return []

    def execute(self, input_data: dict[str, Any], context: SkillContext) -> Artifact:
        conflicts = input_data["conflicts"]
        resolutions = []

        for conflict in conflicts:
            parties = conflict.get("parties", [])
            issue = conflict.get("issue", "")
            options = conflict.get("options", [])

            # Decision logic: prefer options aligned with requirements
            reqs = context.artifact_store.get_latest(ArtifactType.REQUIREMENTS)
            nfr_text = ""
            if reqs:
                nfr_text = " ".join(
                    r.get("description", "").lower() for r in reqs.content.get("non_functional_requirements", [])
                )

            chosen_option = options[0] if options else "defer to architect"
            rationale = "Default selection - first proposed option"

            # Simple heuristic: prefer performance-oriented options if NFRs mention performance
            if "performance" in nfr_text:
                for opt in options:
                    if "performance" in str(opt).lower() or "fast" in str(opt).lower():
                        chosen_option = opt
                        rationale = "Selected for performance alignment with NFRs"
                        break
            elif "security" in nfr_text:
                for opt in options:
                    if "security" in str(opt).lower() or "secure" in str(opt).lower():
                        chosen_option = opt
                        rationale = "Selected for security alignment with NFRs"
                        break

            resolutions.append(
                {
                    "issue": issue,
                    "parties": parties,
                    "decision": chosen_option,
                    "rationale": rationale,
                    "status": "resolved",
                }
            )

        return Artifact(
            artifact_type=ArtifactType.REVIEW_FEEDBACK,
            content={
                "resolutions": resolutions,
                "total_conflicts": len(conflicts),
                "resolved_count": sum(1 for r in resolutions if r["status"] == "resolved"),
            },
            producer="project_manager",
            metadata={
                "type": "conflict_resolution",
                "project_name": context.project_name,
            },
        )

"""Requirement distribution skill - distributes original project requirements to the team."""

from __future__ import annotations

from typing import Any

from ....core.artifact import Artifact, ArtifactType
from ....core.skill import Skill, SkillContext


class RequirementDistributionSkill(Skill):
    """Distribute original project requirements (product + architecture) to the team.

    The RD Director uses this skill to formally hand off the raw project
    requirements to the team. This includes both product-level requirements
    (what to build) and architecture-level requirements (how to build it).
    The output is a structured distribution record that downstream agents
    can reference as the authoritative source of initial requirements.
    """

    @property
    def name(self) -> str:
        return "requirement_distribution"

    @property
    def description(self) -> str:
        return "Distribute original product and architecture requirements to the project team"

    def validate_input(self, input_data: dict[str, Any]) -> list[str]:
        errors = []
        if not input_data.get("product_requirements"):
            errors.append("'product_requirements' is required")
        return errors

    def execute(self, input_data: dict[str, Any], context: SkillContext) -> Artifact:
        product_requirements: Any = input_data.get("product_requirements", "")
        architecture_requirements: Any = input_data.get("architecture_requirements", "")
        project_name: str = input_data.get("project_name", context.project_name)
        recipients: list[str] = input_data.get(
            "recipients",
            ["product_manager", "architect", "developer", "qa_engineer"],
        )

        # Normalise requirements to lists for consistent downstream consumption
        if isinstance(product_requirements, str):
            product_requirements = [product_requirements] if product_requirements else []
        if isinstance(architecture_requirements, str):
            architecture_requirements = [architecture_requirements] if architecture_requirements else []

        distribution_record = {
            "project_name": project_name,
            "product_requirements": product_requirements,
            "architecture_requirements": architecture_requirements,
            "recipients": recipients,
            "product_requirement_count": len(product_requirements),
            "architecture_requirement_count": len(architecture_requirements),
        }

        return Artifact(
            artifact_type=ArtifactType.REQUIREMENTS,
            content={
                "report_type": "requirement_distribution",
                "distribution": distribution_record,
                "raw_input": "\n".join(product_requirements + architecture_requirements),
                "functional_requirements": [
                    {"id": f"PR-{i + 1}", "type": "functional", "description": req}
                    for i, req in enumerate(product_requirements)
                ],
                "non_functional_requirements": [
                    {"id": f"AR-{i + 1}", "type": "architecture", "description": req}
                    for i, req in enumerate(architecture_requirements)
                ],
                "constraints": [],
            },
            producer="rd_director",
            metadata={
                "type": "requirement_distribution",
                "project_name": project_name,
                "recipients": recipients,
            },
        )

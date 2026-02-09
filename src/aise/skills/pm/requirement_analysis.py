"""Requirement analysis skill - parses raw input into structured requirements."""

from __future__ import annotations

from typing import Any

from ...core.artifact import Artifact, ArtifactType
from ...core.skill import Skill, SkillContext


class RequirementAnalysisSkill(Skill):
    """Parse raw user input into structured functional and non-functional requirements."""

    @property
    def name(self) -> str:
        return "requirement_analysis"

    @property
    def description(self) -> str:
        return "Analyze raw input and produce structured requirements (functional, non-functional, constraints)"

    def validate_input(self, input_data: dict[str, Any]) -> list[str]:
        errors = []
        if not input_data.get("raw_requirements"):
            errors.append("'raw_requirements' field is required")
        return errors

    def execute(self, input_data: dict[str, Any], context: SkillContext) -> Artifact:
        raw = input_data["raw_requirements"]

        # Parse raw requirements into structured format
        functional = []
        non_functional = []
        constraints = []

        if isinstance(raw, str):
            lines = [line.strip() for line in raw.strip().split("\n") if line.strip()]
            for i, line in enumerate(lines, 1):
                line_lower = line.lower()
                if any(
                    kw in line_lower
                    for kw in [
                        "performance",
                        "security",
                        "scalab",
                        "reliab",
                        "maintain",
                    ]
                ):
                    non_functional.append(
                        {
                            "id": f"NFR-{len(non_functional) + 1:03d}",
                            "description": line,
                            "priority": "high",
                        }
                    )
                elif any(
                    kw in line_lower
                    for kw in [
                        "constraint",
                        "must use",
                        "limited to",
                        "budget",
                        "deadline",
                    ]
                ):
                    constraints.append(
                        {
                            "id": f"CON-{len(constraints) + 1:03d}",
                            "description": line,
                        }
                    )
                else:
                    functional.append(
                        {
                            "id": f"FR-{len(functional) + 1:03d}",
                            "description": line,
                            "priority": "medium",
                        }
                    )
        elif isinstance(raw, list):
            for i, item in enumerate(raw, 1):
                functional.append(
                    {
                        "id": f"FR-{i:03d}",
                        "description": str(item),
                        "priority": "medium",
                    }
                )

        return Artifact(
            artifact_type=ArtifactType.REQUIREMENTS,
            content={
                "functional_requirements": functional,
                "non_functional_requirements": non_functional,
                "constraints": constraints,
                "raw_input": raw,
            },
            producer="product_manager",
            metadata={"project_name": context.project_name},
        )

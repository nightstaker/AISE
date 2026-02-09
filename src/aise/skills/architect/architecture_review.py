"""Architecture review skill - reviews implementation against architecture."""

from __future__ import annotations

from typing import Any

from ...core.artifact import Artifact, ArtifactStatus, ArtifactType
from ...core.skill import Skill, SkillContext


class ArchitectureReviewSkill(Skill):
    """Review implementation against architecture design; identify violations."""

    @property
    def name(self) -> str:
        return "architecture_review"

    @property
    def description(self) -> str:
        return "Review artifacts against architectural design for consistency and violations"

    def execute(self, input_data: dict[str, Any], context: SkillContext) -> Artifact:
        arch = context.artifact_store.get_latest(ArtifactType.ARCHITECTURE_DESIGN)
        api = context.artifact_store.get_latest(ArtifactType.API_CONTRACT)
        code = context.artifact_store.get_latest(ArtifactType.SOURCE_CODE)

        issues = []
        checks = []

        # Check architecture completeness
        if arch:
            components = arch.content.get("components", [])
            checks.append(
                {
                    "check": "component_coverage",
                    "status": "pass" if len(components) > 0 else "fail",
                    "detail": f"{len(components)} components defined",
                }
            )

            data_flows = arch.content.get("data_flows", [])
            checks.append(
                {
                    "check": "data_flow_defined",
                    "status": "pass" if len(data_flows) > 0 else "fail",
                    "detail": f"{len(data_flows)} data flows defined",
                }
            )
        else:
            issues.append(
                {
                    "type": "missing_artifact",
                    "severity": "critical",
                    "description": "No architecture design artifact found",
                }
            )

        # Check API contract exists and has endpoints
        if api:
            endpoints = api.content.get("endpoints", [])
            checks.append(
                {
                    "check": "api_endpoints_defined",
                    "status": "pass" if len(endpoints) > 0 else "fail",
                    "detail": f"{len(endpoints)} API endpoints defined",
                }
            )
        else:
            issues.append(
                {
                    "type": "missing_artifact",
                    "severity": "high",
                    "description": "No API contract artifact found",
                }
            )

        # Check code alignment if code exists
        if code and arch:
            code_modules = code.content.get("modules", [])
            component_names = {c["name"] for c in arch.content.get("components", []) if c["type"] == "service"}
            for comp_name in component_names:
                found = any(comp_name.lower() in m.get("name", "").lower() for m in code_modules)
                if not found:
                    issues.append(
                        {
                            "type": "missing_implementation",
                            "severity": "high",
                            "description": f"Component '{comp_name}' has no corresponding code module",
                        }
                    )

        approved = all(i["severity"] not in ("critical", "high") for i in issues) if issues else True

        if arch:
            new_status = ArtifactStatus.APPROVED if approved else ArtifactStatus.REJECTED
            context.artifact_store.update_status(arch.id, new_status)

        return Artifact(
            artifact_type=ArtifactType.REVIEW_FEEDBACK,
            content={
                "approved": approved,
                "checks": checks,
                "issues": issues,
                "summary": f"Architecture review: {'Approved' if approved else 'Needs revision'}, "
                f"{len(checks)} checks, {len(issues)} issues.",
            },
            producer="architect",
            metadata={
                "review_target": "architecture",
                "project_name": context.project_name,
            },
        )

"""System Feature Analysis skill - produces system features (SF) from raw requirements."""

from __future__ import annotations

from typing import Any

from ...core.artifact import Artifact, ArtifactType
from ...core.skill import Skill, SkillContext


class SystemFeatureAnalysisSkill(Skill):
    """Analyze Team Leader's requirements and produce System Features (SF) list."""

    @property
    def name(self) -> str:
        return "system_feature_analysis"

    @property
    def description(self) -> str:
        return "Analyze requirements and produce System Features (SF) with external and internal DFX characteristics"

    def validate_input(self, input_data: dict[str, Any]) -> list[str]:
        errors = []
        if not input_data.get("raw_requirements"):
            errors.append("'raw_requirements' field is required")
        return errors

    def execute(self, input_data: dict[str, Any], context: SkillContext) -> Artifact:
        raw = input_data["raw_requirements"]
        project_name = context.project_name or input_data.get("project_name", "Untitled")

        # Parse requirements into external and internal features
        external_features = []
        internal_features = []

        if isinstance(raw, str):
            lines = [line.strip() for line in raw.strip().split("\n") if line.strip()]
            for line in lines:
                line_lower = line.lower()
                # Classify as internal DFX or external feature
                if any(
                    kw in line_lower
                    for kw in [
                        "performance",
                        "security",
                        "scalability",
                        "reliability",
                        "maintainability",
                        "testability",
                        "observability",
                        "availability",
                        "logging",
                        "monitoring",
                        "dfx",
                    ]
                ):
                    internal_features.append(line)
                else:
                    external_features.append(line)
        elif isinstance(raw, list):
            # If raw is a list, treat all as external features by default
            external_features = [str(item) for item in raw]

        # Generate SF IDs and structured features
        all_features = []
        sf_counter = 1

        # Add external features
        for feature_desc in external_features:
            sf_id = f"SF-{sf_counter:03d}"
            all_features.append(
                {
                    "id": sf_id,
                    "description": feature_desc,
                    "type": "external",
                    "category": self._categorize_external_feature(feature_desc),
                }
            )
            sf_counter += 1

        # Add internal DFX features
        for feature_desc in internal_features:
            sf_id = f"SF-{sf_counter:03d}"
            all_features.append(
                {
                    "id": sf_id,
                    "description": feature_desc,
                    "type": "internal_dfx",
                    "category": self._categorize_internal_feature(feature_desc),
                }
            )
            sf_counter += 1

        system_design = {
            "project_name": project_name,
            "overview": f"System design with {len(all_features)} features "
            f"({len(external_features)} external, {len(internal_features)} internal DFX)",
            "external_features": [f for f in all_features if f["type"] == "external"],
            "internal_dfx_features": [f for f in all_features if f["type"] == "internal_dfx"],
            "all_features": all_features,
            "raw_input": raw,
        }

        return Artifact(
            artifact_type=ArtifactType.SYSTEM_DESIGN,
            content=system_design,
            producer="product_manager",
            metadata={"project_name": project_name},
        )

    def _categorize_external_feature(self, description: str) -> str:
        """Categorize external feature based on description keywords."""
        desc_lower = description.lower()
        if any(kw in desc_lower for kw in ["user", "login", "auth", "account"]):
            return "User Management"
        elif any(kw in desc_lower for kw in ["data", "store", "save", "retrieve"]):
            return "Data Management"
        elif any(kw in desc_lower for kw in ["api", "interface", "endpoint"]):
            return "API/Interface"
        elif any(kw in desc_lower for kw in ["ui", "display", "show", "view"]):
            return "User Interface"
        else:
            return "Functional"

    def _categorize_internal_feature(self, description: str) -> str:
        """Categorize internal DFX feature based on description keywords."""
        desc_lower = description.lower()
        if any(kw in desc_lower for kw in ["performance", "speed", "latency", "throughput"]):
            return "Performance"
        elif any(kw in desc_lower for kw in ["security", "auth", "encrypt", "protect"]):
            return "Security"
        elif any(kw in desc_lower for kw in ["scalability", "scale", "load"]):
            return "Scalability"
        elif any(kw in desc_lower for kw in ["reliability", "available", "uptime"]):
            return "Reliability"
        elif any(kw in desc_lower for kw in ["maintain", "debug", "log", "monitor", "observ"]):
            return "Maintainability"
        elif any(kw in desc_lower for kw in ["test", "quality"]):
            return "Testability"
        else:
            return "DFX"

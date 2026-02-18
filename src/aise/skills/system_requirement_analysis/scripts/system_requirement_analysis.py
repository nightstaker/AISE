"""System Requirement Analysis skill - produces system requirements (SR) from system features (SF)."""

from __future__ import annotations

from typing import Any

from ....core.artifact import Artifact, ArtifactType
from ....core.skill import Skill, SkillContext


class SystemRequirementAnalysisSkill(Skill):
    """Analyze System Features (SF) and produce detailed System Requirements (SR) list."""

    @property
    def name(self) -> str:
        return "system_requirement_analysis"

    @property
    def description(self) -> str:
        return "Generate System Requirements (SR) from System Features (SF) with full traceability"

    def execute(self, input_data: dict[str, Any], context: SkillContext) -> Artifact:
        store = context.artifact_store
        project_name = context.project_name or input_data.get("project_name", "Untitled")

        # Get system design (SF list) from input first, then artifact store.
        system_design_payload = input_data.get("system_design")
        if isinstance(system_design_payload, dict):
            all_features = system_design_payload.get("all_features", [])
        else:
            system_design = store.get_latest(ArtifactType.SYSTEM_DESIGN)
            if not system_design:
                raise ValueError("No SYSTEM_DESIGN artifact found. Please run system_feature_analysis first.")
            all_features = system_design.content.get("all_features", [])

        if not all_features:
            raise ValueError("No SYSTEM_DESIGN artifact found. Please run system_feature_analysis first.")

        # Generate system requirements from features
        system_requirements = []
        sr_counter = 1

        for sf in all_features:
            # Generate one or more SRs for each SF
            # For simplicity, we'll generate one SR per SF, but this could be expanded
            # to generate multiple SRs for complex features
            requirements = self._generate_requirements_for_feature(sf, sr_counter)

            for req in requirements:
                system_requirements.append(req)
                sr_counter += 1

        # Validate coverage: ensure all SFs are covered
        covered_sfs = set()
        for sr in system_requirements:
            covered_sfs.update(sr["source_sfs"])

        all_sf_ids = {sf["id"] for sf in all_features}
        uncovered_sfs = all_sf_ids - covered_sfs

        system_requirements_doc = {
            "project_name": project_name,
            "overview": f"System requirements with {len(system_requirements)} requirements "
            f"covering {len(all_features)} system features",
            "requirements": system_requirements,
            "coverage_summary": {
                "total_sfs": len(all_features),
                "covered_sfs": len(covered_sfs),
                "uncovered_sfs": list(uncovered_sfs),
                "coverage_percentage": (len(covered_sfs) / len(all_features) * 100) if all_features else 0,
            },
            "traceability_matrix": self._build_traceability_matrix(system_requirements, all_features),
        }

        return Artifact(
            artifact_type=ArtifactType.SYSTEM_REQUIREMENTS,
            content=system_requirements_doc,
            producer="product_manager",
            metadata={"project_name": project_name},
        )

    def _generate_requirements_for_feature(self, sf: dict[str, Any], start_counter: int) -> list[dict[str, Any]]:
        """Generate detailed system requirements for a given system feature."""
        sf_id = sf["id"]
        sf_desc = sf["description"]
        sf_type = sf["type"]
        sf_category = sf.get("category", "Uncategorized")

        requirements = []

        # Main functional requirement
        sr_id = f"SR-{start_counter:04d}"
        requirements.append(
            {
                "id": sr_id,
                "description": sf_desc,
                "source_sfs": [sf_id],
                "type": "functional" if sf_type == "external" else "non_functional",
                "category": sf_category,
                "priority": self._determine_priority(sf),
                "verification_method": self._determine_verification_method(sf),
            }
        )

        # For external features, add additional requirements as needed
        # (e.g., validation, error handling)
        if sf_type == "external":
            # Add input validation requirement
            if start_counter + 1:  # Always true, just to show pattern
                requirements.append(
                    {
                        "id": f"SR-{start_counter + 1:04d}",
                        "description": f"Input validation for: {sf_desc[:80]}",
                        "source_sfs": [sf_id],
                        "type": "functional",
                        "category": "Input Validation",
                        "priority": "high",
                        "verification_method": "unit_test",
                    }
                )

        return requirements

    def _determine_priority(self, sf: dict[str, Any]) -> str:
        """Determine requirement priority based on feature characteristics."""
        sf_type = sf["type"]
        sf_category = sf.get("category", "")

        # Security and reliability are always high priority
        if sf_category in ["Security", "Reliability"]:
            return "high"

        # Internal DFX features are typically medium to high priority
        if sf_type == "internal_dfx":
            return "high" if sf_category in ["Performance", "Scalability"] else "medium"

        # External features default to medium
        return "medium"

    def _determine_verification_method(self, sf: dict[str, Any]) -> str:
        """Determine how this requirement should be verified."""
        sf_type = sf["type"]
        sf_category = sf.get("category", "")

        if sf_type == "external":
            return "integration_test"
        elif sf_category in ["Performance", "Scalability"]:
            return "performance_test"
        elif sf_category == "Security":
            return "security_test"
        else:
            return "unit_test"

    def _build_traceability_matrix(
        self, requirements: list[dict[str, Any]], features: list[dict[str, Any]]
    ) -> dict[str, list[str]]:
        """Build a traceability matrix mapping SFs to SRs."""
        matrix = {}
        for sf in features:
            sf_id = sf["id"]
            matrix[sf_id] = [req["id"] for req in requirements if sf_id in req["source_sfs"]]
        return matrix

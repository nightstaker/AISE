"""Architecture Requirement Analysis skill - decomposes SR into AR."""

from __future__ import annotations

from typing import Any

from ...core.artifact import Artifact, ArtifactType
from ...core.skill import Skill, SkillContext


class ArchitectureRequirementSkill(Skill):
    """Decompose System Requirements (SR) into Architecture Requirements (AR)."""

    @property
    def name(self) -> str:
        return "architecture_requirement_analysis"

    @property
    def description(self) -> str:
        return "Decompose System Requirements into Architecture Requirements with layer classification"

    def execute(self, input_data: dict[str, Any], context: SkillContext) -> Artifact:
        store = context.artifact_store
        project_name = context.project_name or input_data.get("project_name", "Untitled")

        # Get SYSTEM_REQUIREMENTS artifact
        sr_artifact = store.get_latest(ArtifactType.SYSTEM_REQUIREMENTS)
        if not sr_artifact:
            raise ValueError("No SYSTEM_REQUIREMENTS artifact found. Please run system_requirement_analysis first.")

        requirements = sr_artifact.content["requirements"]

        # Decompose each SR into one or more ARs
        ar_list = []
        for sr in requirements:
            ars = self._decompose_sr_to_ars(sr)
            ar_list.extend(ars)

        # Calculate coverage
        coverage = self._calculate_coverage(requirements, ar_list)

        # Build traceability matrix
        matrix = self._build_traceability_matrix(requirements, ar_list)

        architecture_requirements_doc = {
            "project_name": project_name,
            "overview": f"Architecture requirements with {len(ar_list)} ARs covering {len(requirements)} SRs",
            "architecture_requirements": ar_list,
            "traceability_matrix": matrix,
            "coverage_summary": coverage,
        }

        return Artifact(
            artifact_type=ArtifactType.ARCHITECTURE_REQUIREMENT,
            content=architecture_requirements_doc,
            producer="architect",
            metadata={"project_name": project_name},
        )

    def _decompose_sr_to_ars(self, sr: dict[str, Any]) -> list[dict[str, Any]]:
        """Decompose SR into 1 or more ARs based on architectural layers.

        For functional requirements, create ARs for API, business, and optionally data layer.
        For non-functional requirements, create a single AR for the most appropriate layer.
        """
        sr_id = sr["id"]
        sr_num = sr_id.replace("SR-", "")  # Extract number: "SR-0001" -> "0001"
        sr_desc = sr["description"]
        sr_type = sr["type"]
        sr_category = sr.get("category", "Unknown")

        ars = []

        if sr_type == "functional":
            # Functional requirements typically span multiple layers
            # Create AR for API layer
            ars.append(
                {
                    "id": f"AR-SR-{sr_num}-1",
                    "description": f"API层: {sr_desc[:80]}...",
                    "source_sr": sr_id,
                    "target_layer": "api",
                    "component_type": "service",
                    "estimated_complexity": self._estimate_complexity(sr),
                }
            )

            # Create AR for business layer
            ars.append(
                {
                    "id": f"AR-SR-{sr_num}-2",
                    "description": f"业务层: {sr_desc[:80]}...",
                    "source_sr": sr_id,
                    "target_layer": "business",
                    "component_type": "service",
                    "estimated_complexity": self._estimate_complexity(sr),
                }
            )

            # For data management features, add data layer AR
            if any(keyword in sr_category.lower() for keyword in ["data", "storage", "persistence"]):
                ars.append(
                    {
                        "id": f"AR-SR-{sr_num}-3",
                        "description": f"数据层: {sr_desc[:80]}...",
                        "source_sr": sr_id,
                        "target_layer": "data",
                        "component_type": "component",
                        "estimated_complexity": self._estimate_complexity(sr),
                    }
                )

        else:
            # Non-functional requirements typically map to a single layer
            target_layer = self._determine_nfr_layer(sr)
            ars.append(
                {
                    "id": f"AR-SR-{sr_num}-1",
                    "description": sr_desc,
                    "source_sr": sr_id,
                    "target_layer": target_layer,
                    "component_type": "component",
                    "estimated_complexity": self._estimate_complexity(sr),
                }
            )

        return ars

    def _determine_nfr_layer(self, sr: dict[str, Any]) -> str:
        """Determine the most appropriate layer for a non-functional requirement."""
        sr_category = sr.get("category", "").lower()
        sr_desc = sr.get("description", "").lower()

        # Performance/Scalability -> integration layer (caching, load balancing)
        if any(keyword in sr_category or keyword in sr_desc for keyword in ["performance", "scalability", "caching"]):
            return "integration"

        # Security -> often cross-cutting, but prioritize API layer
        if any(keyword in sr_category or keyword in sr_desc for keyword in ["security", "authentication", "authorization"]):
            return "api"

        # Data-related NFRs -> data layer
        if any(keyword in sr_category or keyword in sr_desc for keyword in ["data", "database", "persistence", "consistency"]):
            return "data"

        # Default to business layer for other NFRs
        return "business"

    def _estimate_complexity(self, sr: dict[str, Any]) -> str:
        """Estimate implementation complexity of an SR."""
        priority = sr.get("priority", "medium")

        # Simple heuristic: high priority often indicates complexity
        if priority == "high":
            return "high"
        elif priority == "low":
            return "low"
        else:
            return "medium"

    def _calculate_coverage(self, requirements: list[dict], ar_list: list[dict]) -> dict[str, Any]:
        """Calculate SR coverage by ARs."""
        covered_srs = set()
        for ar in ar_list:
            covered_srs.add(ar["source_sr"])

        all_sr_ids = {sr["id"] for sr in requirements}
        uncovered_srs = all_sr_ids - covered_srs

        return {
            "total_srs": len(requirements),
            "covered_srs": len(covered_srs),
            "total_ars": len(ar_list),
            "uncovered_srs": list(uncovered_srs),
            "coverage_percentage": (len(covered_srs) / len(requirements) * 100) if requirements else 0,
        }

    def _build_traceability_matrix(self, requirements: list[dict], ar_list: list[dict]) -> dict[str, list[str]]:
        """Build traceability matrix mapping SR IDs to AR IDs."""
        matrix = {}
        for sr in requirements:
            sr_id = sr["id"]
            matrix[sr_id] = [ar["id"] for ar in ar_list if ar["source_sr"] == sr_id]
        return matrix

"""Status Tracking skill - tracks SF-SR-AR-FN traceability and status."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ....core.artifact import Artifact, ArtifactType
from ....core.skill import Skill, SkillContext


class StatusTrackingSkill(Skill):
    """Track status and traceability of all SF-SR-AR-FN elements."""

    @property
    def name(self) -> str:
        return "status_tracking"

    @property
    def description(self) -> str:
        return "Generate complete SF-SR-AR-FN traceability and status information"

    def execute(self, input_data: dict[str, Any], context: SkillContext) -> Artifact:
        store = context.artifact_store
        project_name = context.project_name or input_data.get("project_name", "Untitled")

        # Gather all artifacts
        system_design = store.get_latest(ArtifactType.SYSTEM_DESIGN)
        system_requirements = store.get_latest(ArtifactType.SYSTEM_REQUIREMENTS)
        architecture_requirements = store.get_latest(ArtifactType.ARCHITECTURE_REQUIREMENT)
        functional_design = store.get_latest(ArtifactType.FUNCTIONAL_DESIGN)

        if not all([system_design, system_requirements, architecture_requirements, functional_design]):
            raise ValueError(
                "Missing required artifacts. Please ensure all pipeline stages are complete:\n"
                "1. system_feature_analysis (SF)\n"
                "2. system_requirement_analysis (SR)\n"
                "3. architecture_requirement_analysis (AR)\n"
                "4. functional_design (FN)"
            )

        # Extract data from artifacts
        sfs = system_design.content.get("all_features", [])
        srs = system_requirements.content.get("requirements", [])
        ars = architecture_requirements.content.get("architecture_requirements", [])
        fns = functional_design.content.get("functions", [])

        # Build traceability matrices
        sf_to_sr = system_requirements.content.get("traceability_matrix", {})
        sr_to_ar = architecture_requirements.content.get("traceability_matrix", {})
        ar_to_fn = functional_design.content.get("traceability_matrix", {})

        # Build element registry with status
        elements = {}

        # Add SFs
        for sf in sfs:
            sf_id = sf["id"]
            children = sf_to_sr.get(sf_id, [])
            elements[sf_id] = {
                "type": "system_feature",
                "description": sf["description"],
                "status": "未开始",
                "parent": None,
                "children": children,
                "completion_percentage": 0.0,
            }

        # Add SRs
        for sr in srs:
            sr_id = sr["id"]
            children = sr_to_ar.get(sr_id, [])
            parent_sfs = [sf_id for sf_id, sr_list in sf_to_sr.items() if sr_id in sr_list]
            parent = parent_sfs[0] if parent_sfs else None

            elements[sr_id] = {
                "type": "system_requirement",
                "description": sr["description"],
                "status": "未开始",
                "parent": parent,
                "children": children,
                "completion_percentage": 0.0,
            }

        # Add ARs
        for ar in ars:
            ar_id = ar["id"]
            children = ar_to_fn.get(ar_id, [])
            parent_srs = [sr_id for sr_id, ar_list in sr_to_ar.items() if ar_id in ar_list]
            parent = parent_srs[0] if parent_srs else None

            elements[ar_id] = {
                "type": "architecture_requirement",
                "description": ar["description"],
                "status": "未开始",
                "parent": parent,
                "children": children,
                "completion_percentage": 0.0,
            }

        # Add FNs with implementation status
        for fn in fns:
            fn_id = fn["id"]
            parent_ars = fn.get("source_ars", [])
            parent = parent_ars[0] if parent_ars else None

            # Default implementation status (can be updated later based on actual code)
            implementation_status = {
                "code_generated": False,
                "tests_written": False,
                "tests_passed": False,
                "reviewed": False,
            }

            elements[fn_id] = {
                "type": "function",
                "subtype": fn["type"],
                "description": fn["description"],
                "status": "未开始",
                "parent": parent,
                "children": [],
                "implementation_status": implementation_status,
                "completion_percentage": 0.0,
            }

        # Calculate status from bottom-up (FN -> AR -> SR -> SF)
        self._calculate_status(elements)

        # Generate summary
        summary = {
            "total_sfs": len(sfs),
            "total_srs": len(srs),
            "total_ars": len(ars),
            "total_fns": len(fns),
            "overall_completion": self._calculate_overall_completion(elements, sfs),
        }

        status_tracking_doc = {
            "project_name": project_name,
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "elements": elements,
            "summary": summary,
        }

        return Artifact(
            artifact_type=ArtifactType.STATUS_TRACKING,
            content=status_tracking_doc,
            producer="architect",
            metadata={"project_name": project_name},
        )

    def _calculate_status(self, elements: dict[str, dict[str, Any]]) -> None:
        """Calculate status for all elements from bottom-up."""
        # First pass: calculate FN status based on implementation_status
        for element_id, element in elements.items():
            if element["type"] == "function":
                impl_status = element["implementation_status"]
                completed_count = sum(1 for v in impl_status.values() if v)
                total_count = len(impl_status)

                completion_pct = (completed_count / total_count * 100) if total_count > 0 else 0
                element["completion_percentage"] = completion_pct

                if completion_pct == 0:
                    element["status"] = "未开始"
                elif completion_pct == 100:
                    element["status"] = "已完成"
                else:
                    element["status"] = "进行中"

        # Second pass: calculate AR status based on children FNs
        for element_id, element in elements.items():
            if element["type"] == "architecture_requirement":
                children = element["children"]
                if children:
                    child_completions = [
                        elements[child_id]["completion_percentage"] for child_id in children if child_id in elements
                    ]
                    avg_completion = sum(child_completions) / len(child_completions) if child_completions else 0
                    element["completion_percentage"] = avg_completion

                    if avg_completion == 0:
                        element["status"] = "未开始"
                    elif avg_completion == 100:
                        element["status"] = "已完成"
                    else:
                        element["status"] = "进行中"

        # Third pass: calculate SR status based on children ARs
        for element_id, element in elements.items():
            if element["type"] == "system_requirement":
                children = element["children"]
                if children:
                    child_completions = [
                        elements[child_id]["completion_percentage"] for child_id in children if child_id in elements
                    ]
                    avg_completion = sum(child_completions) / len(child_completions) if child_completions else 0
                    element["completion_percentage"] = avg_completion

                    if avg_completion == 0:
                        element["status"] = "未开始"
                    elif avg_completion == 100:
                        element["status"] = "已完成"
                    else:
                        element["status"] = "进行中"

        # Fourth pass: calculate SF status based on children SRs
        for element_id, element in elements.items():
            if element["type"] == "system_feature":
                children = element["children"]
                if children:
                    child_completions = [
                        elements[child_id]["completion_percentage"] for child_id in children if child_id in elements
                    ]
                    avg_completion = sum(child_completions) / len(child_completions) if child_completions else 0
                    element["completion_percentage"] = avg_completion

                    if avg_completion == 0:
                        element["status"] = "未开始"
                    elif avg_completion == 100:
                        element["status"] = "已完成"
                    else:
                        element["status"] = "进行中"

    def _calculate_overall_completion(self, elements: dict[str, dict[str, Any]], sfs: list[dict[str, Any]]) -> float:
        """Calculate overall project completion based on SF completion."""
        sf_ids = [sf["id"] for sf in sfs]
        sf_completions = [elements[sf_id]["completion_percentage"] for sf_id in sf_ids if sf_id in elements]

        return sum(sf_completions) / len(sf_completions) if sf_completions else 0.0

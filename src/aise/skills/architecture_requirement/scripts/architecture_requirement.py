"""Architecture Requirement Analysis skill - decomposes SR into AR."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ....core.artifact import Artifact, ArtifactType
from ....core.skill import Skill, SkillContext


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
        llm_ars = self._decompose_with_llm(requirements, context)
        if llm_ars is not None:
            ar_list = llm_ars
        else:
            ar_list = []
            for sr in requirements:
                ars = self._decompose_sr_to_ars(sr)
                ar_list.extend(ars)

        coverage = self._calculate_coverage(requirements, ar_list)
        matrix = self._build_traceability_matrix(requirements, ar_list)

        architecture_requirements_doc = {
            "project_name": project_name,
            "overview": f"Architecture requirements with {len(ar_list)} ARs covering {len(requirements)} SRs",
            "architecture_requirements": ar_list,
            "traceability_matrix": matrix,
            "coverage_summary": coverage,
            "analysis_mode": "llm" if llm_ars is not None else "heuristic",
        }

        return Artifact(
            artifact_type=ArtifactType.ARCHITECTURE_REQUIREMENT,
            content=architecture_requirements_doc,
            producer="architect",
            metadata={"project_name": project_name, "analysis_mode": architecture_requirements_doc["analysis_mode"]},
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
        security_keywords = ["security", "authentication", "authorization"]
        if any(keyword in sr_category or keyword in sr_desc for keyword in security_keywords):
            return "api"

        # Data-related NFRs -> data layer
        data_keywords = ["data", "database", "persistence", "consistency"]
        if any(keyword in sr_category or keyword in sr_desc for keyword in data_keywords):
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

    def _decompose_with_llm(
        self,
        requirements: list[dict[str, Any]],
        context: SkillContext,
    ) -> list[dict[str, Any]] | None:
        if context.llm_client is None or not requirements:
            return None

        agent_prompt = self._load_prompt_file("../../../agents/architect_agent.md")
        skill_prompt = self._load_prompt_file("../skill.md")
        req_lines = []
        for sr in requirements[:80]:
            req_lines.append(
                f"- {sr.get('id', '')} | {sr.get('type', '')} | {sr.get('category', '')} | {sr.get('description', '')}"
            )
        system_prompt = (
            f"{agent_prompt}\n\n{skill_prompt}\n\n"
            "你是系统架构师。请把SR分解为AR。只返回JSON："
            "{"
            '"architecture_requirements":[{"source_sr":"SR-0001","target_layer":"api|business|data|integration","component_type":"service|component","description":"string","estimated_complexity":"low|medium|high"}]'
            "}"
        )
        try:
            response = context.llm_client.complete(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": "SR列表:\n" + "\n".join(req_lines)},
                ],
                response_format={"type": "json_object"},
            )
        except Exception:
            return None
        parsed = self._parse_json_response(response)
        if not isinstance(parsed, dict):
            return None
        values = parsed.get("architecture_requirements")
        if not isinstance(values, list):
            return None
        rows = self._normalise_llm_ars(values, requirements)
        return rows or None

    def _normalise_llm_ars(
        self,
        ars: list[Any],
        requirements: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        valid_layers = {"api", "business", "data", "integration"}
        valid_types = {"service", "component"}
        sr_ids = {str(sr.get("id", "")) for sr in requirements}
        counters: dict[str, int] = {}
        rows: list[dict[str, Any]] = []

        for item in ars:
            if not isinstance(item, dict):
                continue
            source_sr = str(item.get("source_sr", "")).strip()
            if source_sr not in sr_ids:
                continue
            seq = counters.get(source_sr, 0) + 1
            counters[source_sr] = seq
            sr_num = source_sr.replace("SR-", "")
            target_layer = str(item.get("target_layer", "business")).strip().lower()
            component_type = str(item.get("component_type", "component")).strip().lower()
            description = str(item.get("description", "")).strip()
            complexity = str(item.get("estimated_complexity", "medium")).strip().lower()
            if target_layer not in valid_layers:
                target_layer = "business"
            if component_type not in valid_types:
                component_type = "component"
            if complexity not in {"low", "medium", "high"}:
                complexity = "medium"
            if not description:
                description = f"{target_layer} layer requirement from {source_sr}"
            rows.append(
                {
                    "id": f"AR-SR-{sr_num}-{seq}",
                    "description": description,
                    "source_sr": source_sr,
                    "target_layer": target_layer,
                    "component_type": component_type,
                    "estimated_complexity": complexity,
                }
            )
        return rows

    def _load_prompt_file(self, relative_path: str) -> str:
        path = Path(__file__).resolve().parent / relative_path
        try:
            return path.read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def _parse_json_response(self, text: str) -> dict[str, Any] | None:
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        block = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, flags=re.DOTALL)
        if block:
            try:
                return json.loads(block.group(1))
            except json.JSONDecodeError:
                return None
        return None

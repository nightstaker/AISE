"""System design skill - produces high-level architecture."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ....core.artifact import Artifact, ArtifactType
from ....core.skill import Skill, SkillContext


class SystemDesignSkill(Skill):
    """Produce high-level system architecture with components, data flow, and technology choices."""

    @property
    def name(self) -> str:
        return "system_design"

    @property
    def description(self) -> str:
        return "Design high-level system architecture from requirements and PRD"

    def execute(self, input_data: dict[str, Any], context: SkillContext) -> Artifact:
        store = context.artifact_store
        requirements_payload = self._resolve_requirements(input_data, context)
        features = self._collect_features(store.get_content(ArtifactType.PRD, "features", []), requirements_payload)
        non_functional = self._collect_non_functional_requirements(requirements_payload)

        llm_design = self._design_with_llm(features, non_functional, context)
        return Artifact(
            artifact_type=ArtifactType.ARCHITECTURE_DESIGN,
            content=llm_design,
            producer="architect",
            metadata={"project_name": context.project_name, "analysis_mode": "llm"},
        )

    @staticmethod
    def _to_component_name(feature_name: str) -> str:
        """Convert feature name to PascalCase component name."""
        words = feature_name.split()[:3]
        return "".join(w.capitalize() for w in words)

    def _resolve_requirements(self, input_data: dict[str, Any], context: SkillContext) -> dict[str, Any]:
        payload = input_data.get("requirements")
        if isinstance(payload, dict):
            return payload
        latest = context.artifact_store.get_latest(ArtifactType.REQUIREMENTS)
        return latest.content if latest else {}

    def _collect_features(self, prd_features: Any, requirements_payload: dict[str, Any]) -> list[dict[str, str]]:
        features: list[dict[str, str]] = []
        if isinstance(prd_features, list):
            for item in prd_features:
                if isinstance(item, dict):
                    name = str(item.get("name", "")).strip()
                    desc = str(item.get("description", name)).strip()
                else:
                    name = str(item).strip()
                    desc = name
                if not name:
                    continue
                features.append({"name": name, "description": desc})

        req_items = requirements_payload.get("functional_requirements", [])
        if isinstance(req_items, list):
            for item in req_items:
                if not isinstance(item, dict):
                    continue
                desc = str(item.get("description", "")).strip()
                if not desc:
                    continue
                name = desc.split("。", 1)[0].split(".", 1)[0].strip()[:40] or "Feature"
                features.append({"name": name, "description": desc})

        if not features:
            raw_input = requirements_payload.get("raw_input", "")
            if isinstance(raw_input, str):
                for line in raw_input.splitlines():
                    desc = line.strip()
                    if desc:
                        features.append({"name": desc[:40], "description": desc})
        return features

    def _collect_non_functional_requirements(self, requirements_payload: dict[str, Any]) -> list[dict[str, str]]:
        items = requirements_payload.get("non_functional_requirements", [])
        result: list[dict[str, str]] = []
        if not isinstance(items, list):
            return result
        for idx, item in enumerate(items, start=1):
            if isinstance(item, dict):
                desc = str(item.get("description", "")).strip()
            else:
                desc = str(item).strip()
            if not desc:
                continue
            result.append({"id": f"NFR-{idx:03d}", "description": desc})
        return result

    def _design_with_llm(
        self,
        features: list[dict[str, str]],
        non_functional: list[dict[str, str]],
        context: SkillContext,
    ) -> dict[str, Any]:
        if context.llm_client is None:
            raise RuntimeError("LLM client is required for system_design")
        if not features:
            raise ValueError("No features available for system_design")

        agent_prompt = self._load_prompt_file("../../../agents/architect_agent.md")
        skill_prompt = self._load_prompt_file("../skill.md")
        feature_lines = [f"- {f.get('name', 'Feature')}: {f.get('description', '')}" for f in features[:30]]
        nfr_lines = [f"- {nfr.get('description', '')}" for nfr in non_functional[:20]]
        system_prompt = (
            f"{agent_prompt}\n\n{skill_prompt}\n\n"
            "你是软件架构师。请基于需求给出系统设计。只返回JSON："
            "{"
            '"architecture_style":"monolith|microservices|modular_monolith",'
            '"components":[{"name":"string","responsibility":"string","type":"service|infrastructure"}],'
            '"data_flows":[{"from":"string","to":"string","description":"string"}],'
            '"deployment":{"strategy":"string","environments":["string"]},'
            '"non_functional_considerations":[{"requirement":"string","approach":"string"}]'
            "}"
            "。键名必须与上述完全一致；architecture_style 枚举值必须使用 monolith|microservices|modular_monolith；"
            "不得翻译或改名；不得包裹在 data/result/output/payload 下。"
        )
        user_prompt = (
            "功能需求:\n"
            + "\n".join(feature_lines)
            + "\n\n非功能需求:\n"
            + ("\n".join(nfr_lines) if nfr_lines else "- 无")
        )

        response = context.llm_client.complete(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
        )
        parsed = self._parse_json_response(response)

        components = self._normalise_components(parsed.get("components"))
        if not components:
            raise RuntimeError("LLM response contains no valid components for system_design")

        architecture_style = str(parsed.get("architecture_style", "monolith")).strip().lower() or "monolith"
        data_flows = self._normalise_data_flows(parsed.get("data_flows"))
        deployment = parsed.get("deployment")
        if not isinstance(deployment, dict):
            deployment = {"strategy": "containerized", "environments": ["development", "staging", "production"]}
        considerations = parsed.get("non_functional_considerations")
        if not isinstance(considerations, list):
            considerations = []

        return {
            "project_name": context.project_name,
            "architecture_style": architecture_style,
            "components": components,
            "data_flows": data_flows,
            "deployment": deployment,
            "non_functional_considerations": considerations,
            "analysis_mode": "llm",
        }

    def _normalise_components(self, value: Any) -> list[dict[str, str]]:
        if not isinstance(value, list):
            return []
        rows: list[dict[str, str]] = []
        for idx, item in enumerate(value, start=1):
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            responsibility = str(item.get("responsibility", "")).strip()
            ctype = str(item.get("type", "service")).strip().lower()
            if not name:
                continue
            if ctype not in {"service", "infrastructure"}:
                ctype = "service"
            rows.append(
                {
                    "id": f"COMP-{idx:03d}",
                    "name": name,
                    "responsibility": responsibility or f"Implements {name}",
                    "type": ctype,
                }
            )
        return rows

    def _normalise_data_flows(self, value: Any) -> list[dict[str, str]]:
        if not isinstance(value, list):
            return []
        rows: list[dict[str, str]] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            source = str(item.get("from", "")).strip()
            target = str(item.get("to", "")).strip()
            desc = str(item.get("description", "")).strip()
            if source and target:
                rows.append({"from": source, "to": target, "description": desc or f"{source} -> {target}"})
        return rows

    def _load_prompt_file(self, relative_path: str) -> str:
        path = Path(__file__).resolve().parent / relative_path
        try:
            return path.read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def _parse_json_response(self, text: str) -> dict[str, Any]:
        if not text:
            raise RuntimeError("Empty LLM response for system_design")
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
        block = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, flags=re.DOTALL)
        if block:
            try:
                parsed = json.loads(block.group(1))
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass
        raise RuntimeError("LLM response is not valid JSON object for system_design")

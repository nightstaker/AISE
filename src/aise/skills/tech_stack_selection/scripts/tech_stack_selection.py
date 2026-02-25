"""Tech stack selection skill - recommends technology choices."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ....core.artifact import Artifact, ArtifactType
from ....core.skill import Skill, SkillContext
from ....utils.markdown import read_markdown


class TechStackSelectionSkill(Skill):
    """Recommend and justify technology choices based on requirements."""

    @property
    def name(self) -> str:
        return "tech_stack_selection"

    @property
    def description(self) -> str:
        return "Select and justify technology stack based on project requirements"

    def execute(self, input_data: dict[str, Any], context: SkillContext) -> Artifact:
        store = context.artifact_store
        requirements_payload = self._resolve_requirements(input_data, context)
        non_functional = requirements_payload.get("non_functional_requirements", [])
        arch_style = store.get_content(ArtifactType.ARCHITECTURE_DESIGN, "architecture_style", "monolith")

        llm_stack = self._select_with_llm(non_functional, arch_style, context)
        return Artifact(
            artifact_type=ArtifactType.TECH_STACK,
            content=llm_stack,
            producer="architect",
            metadata={"project_name": context.project_name, "analysis_mode": "llm"},
        )

    @staticmethod
    def _select_testing_tools(language: str) -> dict:
        """Select testing tools appropriate for the backend language."""
        if language == "compiled_language":
            return {
                "unit": "language_native_test_framework",
                "integration": "integration_test_harness",
                "e2e": "http_or_rpc_end_to_end_suite",
                "justification": "Prefer native testing stack for compiled runtime ecosystems",
            }
        return {
            "unit": "unit_test_framework",
            "integration": "integration_test_framework",
            "e2e": "end_to_end_test_framework",
            "justification": "Balanced unit/integration/e2e coverage for iterative delivery",
        }

    def _resolve_requirements(self, input_data: dict[str, Any], context: SkillContext) -> dict[str, Any]:
        payload = input_data.get("requirements")
        if isinstance(payload, dict):
            return payload
        latest = context.artifact_store.get_latest(ArtifactType.REQUIREMENTS)
        return latest.content if latest else {}

    def _select_with_llm(
        self,
        non_functional: Any,
        arch_style: str,
        context: SkillContext,
    ) -> dict[str, Any]:
        if context.llm_client is None:
            raise RuntimeError("LLM client is required for tech_stack_selection")
        if not isinstance(non_functional, list):
            raise ValueError("non_functional_requirements must be a list for tech_stack_selection")
        nfr_lines = []
        for item in non_functional[:20]:
            if isinstance(item, dict):
                desc = str(item.get("description", "")).strip()
            else:
                desc = str(item).strip()
            if desc:
                nfr_lines.append(f"- {desc}")
        if not nfr_lines:
            raise ValueError("No non-functional requirements available for tech_stack_selection")

        agent_prompt = self._load_prompt_file("../../../agents/architect_agent.md")
        skill_prompt = self._load_prompt_file("../skill.md")
        system_prompt = (
            f"{agent_prompt}\n\n{skill_prompt}\n\n"
            "你是系统架构师，请基于NFR和架构风格选择技术栈。只返回JSON："
            "{"
            '"backend":{"language":"string","framework":"string","justification":"string"},'
            '"database":{"type":"string","justification":"string"},'
            '"cache":{"type":"string","justification":"string"},'
            '"infrastructure":{"containerization":"string","orchestration":"string","deployment":"string","justification":"string"},'
            '"testing":{"unit":"string","integration":"string","e2e":"string","justification":"string"},'
            '"ci_cd":{"platform":"string","justification":"string"}'
            "}"
            "。键名必须与上述完全一致；不得翻译或改名；不得包裹在 data/result/output/payload 下。"
        )
        user_prompt = f"架构风格: {arch_style}\n非功能需求:\n" + "\n".join(nfr_lines)

        response = context.llm_client.complete(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
        )
        parsed = self._parse_json_response(response)

        required = ("backend", "database", "cache", "infrastructure", "testing", "ci_cd")
        if any(not isinstance(parsed.get(key), dict) for key in required):
            raise RuntimeError("LLM response missing required tech stack sections")

        parsed["analysis_mode"] = "llm"
        return parsed

    def _load_prompt_file(self, relative_path: str) -> str:
        path = Path(__file__).resolve().parent / relative_path
        return read_markdown(path, strip=True, default="")

    def _parse_json_response(self, text: str) -> dict[str, Any]:
        if not text:
            raise RuntimeError("Empty LLM response for tech_stack_selection")
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
        raise RuntimeError("LLM response is not valid JSON object for tech_stack_selection")

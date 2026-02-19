"""Tech stack selection skill - recommends technology choices."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ....core.artifact import Artifact, ArtifactType
from ....core.skill import Skill, SkillContext


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

        nfr_text = " ".join(
            str(nfr.get("description", "") if isinstance(nfr, dict) else nfr).lower() for nfr in non_functional
        )
        llm_stack = self._select_with_llm(non_functional, arch_style, context)
        if llm_stack is not None:
            return Artifact(
                artifact_type=ArtifactType.TECH_STACK,
                content=llm_stack,
                producer="architect",
                metadata={"project_name": context.project_name, "analysis_mode": "llm"},
            )

        if "performance" in nfr_text or "high throughput" in nfr_text:
            backend = {
                "language": "Go",
                "framework": "Gin",
                "justification": "High performance requirements favor Go",
            }
        elif "rapid development" in nfr_text or "prototype" in nfr_text:
            backend = {
                "language": "Python",
                "framework": "FastAPI",
                "justification": "Rapid development favors Python/FastAPI",
            }
        else:
            backend = {
                "language": "Python",
                "framework": "FastAPI",
                "justification": "General-purpose, well-supported stack",
            }

        # Select database
        if "relational" in nfr_text or "consistency" in nfr_text or "transaction" in nfr_text:
            database = {
                "type": "PostgreSQL",
                "justification": "ACID compliance for data consistency",
            }
        elif "document" in nfr_text or "flexible schema" in nfr_text:
            database = {
                "type": "MongoDB",
                "justification": "Flexible schema for evolving data models",
            }
        else:
            database = {
                "type": "PostgreSQL",
                "justification": "Reliable default for most workloads",
            }

        # Infrastructure
        if arch_style == "microservices":
            infrastructure = {
                "containerization": "Docker",
                "orchestration": "Kubernetes",
                "service_mesh": "Istio",
                "justification": "Microservices require container orchestration",
            }
        else:
            infrastructure = {
                "containerization": "Docker",
                "deployment": "Docker Compose",
                "justification": "Simple containerized deployment for monolith",
            }

        stack = {
            "backend": backend,
            "database": database,
            "cache": {
                "type": "Redis",
                "justification": "Industry-standard caching and session store",
            },
            "infrastructure": infrastructure,
            "testing": self._select_testing_tools(backend["language"]),
            "ci_cd": {
                "platform": "GitHub Actions",
                "justification": "Integrated with source control",
            },
            "analysis_mode": "heuristic",
        }

        return Artifact(
            artifact_type=ArtifactType.TECH_STACK,
            content=stack,
            producer="architect",
            metadata={"project_name": context.project_name, "analysis_mode": "heuristic"},
        )

    @staticmethod
    def _select_testing_tools(language: str) -> dict:
        """Select testing tools appropriate for the backend language."""
        if language == "Go":
            return {
                "unit": "go test",
                "integration": "testify",
                "e2e": "go test + net/http/httptest",
                "justification": "Go-native testing tools for idiomatic test suites",
            }
        # Default to Python ecosystem
        return {
            "unit": "pytest",
            "integration": "pytest + httpx",
            "e2e": "Playwright",
            "justification": "Comprehensive Python testing ecosystem",
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
    ) -> dict[str, Any] | None:
        if context.llm_client is None or not isinstance(non_functional, list):
            return None
        nfr_lines = []
        for item in non_functional[:20]:
            if isinstance(item, dict):
                desc = str(item.get("description", "")).strip()
            else:
                desc = str(item).strip()
            if desc:
                nfr_lines.append(f"- {desc}")
        if not nfr_lines:
            return None

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
        )
        user_prompt = f"架构风格: {arch_style}\n非功能需求:\n" + "\n".join(nfr_lines)

        try:
            response = context.llm_client.complete(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
            )
        except Exception:
            return None
        parsed = self._parse_json_response(response)
        if not isinstance(parsed, dict):
            return None

        required = ("backend", "database", "cache", "infrastructure", "testing", "ci_cd")
        if any(not isinstance(parsed.get(key), dict) for key in required):
            return None

        parsed["analysis_mode"] = "llm"
        return parsed

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

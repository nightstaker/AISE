"""Requirement analysis skill - parses raw input into structured requirements."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ....core.artifact import Artifact, ArtifactType
from ....core.skill import Skill, SkillContext


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
        requirements_doc_path = self._resolve_requirements_doc_path(context)
        self._write_requirements_doc(requirements_doc_path, raw, status="Initialized")

        self._write_requirements_doc(requirements_doc_path, raw, status="Analyzing")
        parsed = self._analyze_with_llm(raw, context)
        if parsed is not None:
            artifact = Artifact(
                artifact_type=ArtifactType.REQUIREMENTS,
                content={
                    "functional_requirements": self._normalise_requirements(
                        parsed.get("functional_requirements", []),
                        prefix="FR",
                        default_priority="medium",
                    ),
                    "non_functional_requirements": self._normalise_requirements(
                        parsed.get("non_functional_requirements", []),
                        prefix="NFR",
                        default_priority="high",
                    ),
                    "constraints": self._normalise_requirements(
                        parsed.get("constraints", []),
                        prefix="CON",
                    ),
                    "raw_input": raw,
                    "analysis_mode": "llm",
                    "llm_summary": parsed.get("summary", ""),
                    "search_evidence": parsed.get("search_evidence", []),
                    "assumptions": parsed.get("assumptions", []),
                    "open_questions": parsed.get("open_questions", []),
                },
                producer="product_manager",
                metadata={"project_name": context.project_name},
            )
            artifact.content["requirement_details"] = self._build_requirement_details(artifact.content, context)
            self._write_requirements_doc(requirements_doc_path, raw, status="Completed", content=artifact.content)
            return artifact

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

        artifact = Artifact(
            artifact_type=ArtifactType.REQUIREMENTS,
            content={
                "functional_requirements": functional,
                "non_functional_requirements": non_functional,
                "constraints": constraints,
                "raw_input": raw,
                "analysis_mode": "heuristic",
            },
            producer="product_manager",
            metadata={"project_name": context.project_name},
        )
        artifact.content["requirement_details"] = self._build_requirement_details(artifact.content, context)
        self._write_requirements_doc(requirements_doc_path, raw, status="Completed", content=artifact.content)
        return artifact

    def _analyze_with_llm(self, raw: Any, context: SkillContext) -> dict[str, Any] | None:
        if context.llm_client is None:
            return None

        agent_prompt = self._load_prompt_file("../../../agents/product_manager_agent.md")
        skill_prompt = self._load_prompt_file("../skill.md")

        system_prompt = (
            f"{agent_prompt}\n\n{skill_prompt}\n\n"
            "你是 Product Manager。先使用搜索工具进行必要的事实核验，再输出需求分析结果。"
            "你必须只返回 JSON，结构如下："
            "{"
            '"summary": "string",'
            '"functional_requirements": [{"description":"string","priority":"low|medium|high"}],'
            '"non_functional_requirements": [{"description":"string","priority":"low|medium|high"}],'
            '"constraints": [{"description":"string"}],'
            '"assumptions": ["string"],'
            '"open_questions": ["string"],'
            '"search_evidence": [{"title":"string","url":"string","finding":"string"}]'
            "}"
        )
        user_prompt = f"原始需求如下，请分析并结构化：\n{raw}"

        try:
            response = context.llm_client.complete(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                tools=[{"type": "web_search_preview"}],
                response_format={"type": "json_object"},
            )
        except Exception:
            return None
        if not response:
            return None

        data = self._parse_json_response(response)
        if data is None or not isinstance(data, dict):
            return None
        return data

    def _load_prompt_file(self, relative_path: str) -> str:
        path = Path(__file__).resolve().parent / relative_path
        try:
            return path.read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def _parse_json_response(self, text: str) -> dict[str, Any] | None:
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

    def _normalise_requirements(
        self,
        values: Any,
        *,
        prefix: str,
        default_priority: str | None = None,
    ) -> list[dict[str, str]]:
        if not isinstance(values, list):
            return []
        output: list[dict[str, str]] = []
        for index, item in enumerate(values, start=1):
            if isinstance(item, dict):
                description = str(item.get("description", "")).strip()
                priority = str(item.get("priority", default_priority or "")).strip()
            else:
                description = str(item).strip()
                priority = default_priority or ""
            if not description:
                continue
            row: dict[str, str] = {"id": f"{prefix}-{index:03d}", "description": description}
            if priority:
                row["priority"] = priority
            output.append(row)
        return output

    def _resolve_requirements_doc_path(self, context: SkillContext) -> Path | None:
        project_root = context.parameters.get("project_root")
        if not isinstance(project_root, str) or not project_root.strip():
            return None
        return Path(project_root) / "docs" / "system-requirements.md"

    def _write_requirements_doc(
        self,
        path: Path | None,
        raw: Any,
        *,
        status: str,
        content: dict[str, Any] | None = None,
    ) -> None:
        if path is None:
            return

        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            "# System Requirements",
            "",
            f"Status: {status}",
            "",
            "## Raw Requirements",
            "",
            "```",
            str(raw),
            "```",
            "",
        ]
        if content:
            mode = str(content.get("analysis_mode", "unknown"))
            lines.extend(
                [
                    "## Analysis Summary",
                    "",
                    f"- analysis_mode: {mode}",
                    f"- functional_requirements: {len(content.get('functional_requirements', []))}",
                    f"- non_functional_requirements: {len(content.get('non_functional_requirements', []))}",
                    f"- constraints: {len(content.get('constraints', []))}",
                    "",
                ]
            )

            lines.extend(["## Functional Requirements", ""])
            for item in content.get("functional_requirements", []):
                if isinstance(item, dict):
                    lines.append(f"- {item.get('id', '')}: {item.get('description', '')}")
            lines.append("")

            lines.extend(["## Non-Functional Requirements", ""])
            for item in content.get("non_functional_requirements", []):
                if isinstance(item, dict):
                    lines.append(f"- {item.get('id', '')}: {item.get('description', '')}")
            lines.append("")

            lines.extend(["## Constraints", ""])
            for item in content.get("constraints", []):
                if isinstance(item, dict):
                    lines.append(f"- {item.get('id', '')}: {item.get('description', '')}")
            lines.append("")

            if content.get("llm_summary"):
                lines.extend(["## LLM Summary", "", str(content.get("llm_summary")), ""])

            lines.extend(["## Detailed Requirement Specifications", ""])
            for item in content.get("functional_requirements", []):
                if isinstance(item, dict):
                    lines.extend(
                        self._format_requirement_detail(
                            item,
                            req_type="functional",
                            detail=self._get_requirement_detail(content, str(item.get("id", ""))),
                        )
                    )
            for item in content.get("non_functional_requirements", []):
                if isinstance(item, dict):
                    lines.extend(
                        self._format_requirement_detail(
                            item,
                            req_type="non_functional",
                            detail=self._get_requirement_detail(content, str(item.get("id", ""))),
                        )
                    )
            for item in content.get("constraints", []):
                if isinstance(item, dict):
                    lines.extend(
                        self._format_requirement_detail(
                            item,
                            req_type="constraint",
                            detail=self._get_requirement_detail(content, str(item.get("id", ""))),
                        )
                    )

        path.write_text("\n".join(lines), encoding="utf-8")

    def _format_requirement_detail(
        self,
        req: dict[str, Any],
        *,
        req_type: str,
        detail: dict[str, str] | None = None,
    ) -> list[str]:
        req_id = str(req.get("id", "REQ-UNKNOWN"))
        description = str(req.get("description", "")).strip()
        priority = str(req.get("priority", "n/a"))
        detail = detail or {}

        normal_scenario = detail.get("normal_scenario") or self._normal_scenario_text(description, req_type)
        exception_scenario = detail.get("exception_scenario") or self._exception_scenario_text(description, req_type)
        specification = detail.get("specification") or self._specification_text(description, req_type)
        performance = detail.get("performance") or self._performance_text(description, req_type)

        return [
            f"### {req_id}",
            "",
            f"- Requirement Type: {req_type}",
            f"- Priority: {priority}",
            f"- Description: {description}",
            "",
            "#### Normal Scenario",
            normal_scenario,
            "",
            "#### Exception Scenario",
            exception_scenario,
            "",
            "#### Specification",
            specification,
            "",
            "#### Performance",
            performance,
            "",
        ]

    def _normal_scenario_text(self, description: str, req_type: str) -> str:
        if req_type == "constraint":
            return f"System execution remains within constraints while implementing: {description}"
        return f"System handles '{description}' successfully under expected inputs and stable dependencies."

    def _exception_scenario_text(self, description: str, req_type: str) -> str:
        if req_type == "non_functional":
            return (
                f"When '{description}' risks are detected, system should degrade gracefully, "
                "emit observability signals, and trigger fallback/retry policies."
            )
        if req_type == "constraint":
            return f"If '{description}' is violated, system blocks release and reports non-compliance explicitly."
        return (
            f"If '{description}' fails due to invalid input or downstream failure, "
            "system returns clear error and keeps data consistent."
        )

    def _specification_text(self, description: str, req_type: str) -> str:
        if req_type == "functional":
            return (
                "Define API/UI contract, input/output schema, validation rules, "
                f"and state transitions for: {description}"
            )
        if req_type == "non_functional":
            return f"Define measurable SLO/SLA, monitoring metrics, and verification strategy for: {description}"
        return f"Define enforceable design/implementation boundary and compliance checks for: {description}"

    def _performance_text(self, description: str, req_type: str) -> str:
        desc_lower = description.lower()
        metric_markers = ("ms", "second", "seconds", "qps", "rps", "throughput", "latency", "p95", "p99")
        if any(marker in desc_lower for marker in metric_markers):
            return f"Performance target is requirement-defined: {description}"
        if req_type == "functional":
            return (
                "Recommended baseline: p95 latency < 300ms, error rate < 1%, and stable throughput under expected load."
            )
        if req_type == "non_functional":
            return "Define explicit SLO values (latency/throughput/error budget) and validate by load testing."
        return "Performance impact must remain within project baseline and not violate existing SLO."

    def _get_requirement_detail(self, content: dict[str, Any], req_id: str) -> dict[str, str] | None:
        details = content.get("requirement_details", {})
        if not isinstance(details, dict):
            return None
        item = details.get(req_id)
        if not isinstance(item, dict):
            return None
        return {k: str(v) for k, v in item.items() if isinstance(v, str)}

    def _build_requirement_details(self, content: dict[str, Any], context: SkillContext) -> dict[str, dict[str, str]]:
        base: dict[str, dict[str, str]] = {}
        reqs: list[tuple[str, str, str]] = []
        for req_type, key in (
            ("functional", "functional_requirements"),
            ("non_functional", "non_functional_requirements"),
            ("constraint", "constraints"),
        ):
            values = content.get(key, [])
            if not isinstance(values, list):
                continue
            for item in values:
                if not isinstance(item, dict):
                    continue
                req_id = str(item.get("id", "")).strip()
                description = str(item.get("description", "")).strip()
                if not req_id or not description:
                    continue
                reqs.append((req_id, req_type, description))
                base[req_id] = {
                    "normal_scenario": self._normal_scenario_text(description, req_type),
                    "exception_scenario": self._exception_scenario_text(description, req_type),
                    "specification": self._specification_text(description, req_type),
                    "performance": self._performance_text(description, req_type),
                }

        refined = self._refine_requirement_details_with_llm(reqs, context)
        for req_id, item in refined.items():
            if req_id in base:
                base[req_id].update(item)
        return base

    def _refine_requirement_details_with_llm(
        self,
        reqs: list[tuple[str, str, str]],
        context: SkillContext,
    ) -> dict[str, dict[str, str]]:
        if not reqs or context.llm_client is None:
            return {}

        req_lines = [f"- {req_id} | {req_type} | {desc}" for req_id, req_type, desc in reqs]
        prompt = (
            "你是资深产品经理。请基于以下需求，细化每个需求的说明。"
            "仅返回JSON对象，键是需求ID，值是对象，字段必须包含："
            "normal_scenario, exception_scenario, specification, performance。"
        )
        try:
            response = context.llm_client.complete(
                [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": "需求列表：\n" + "\n".join(req_lines)},
                ],
                response_format={"type": "json_object"},
            )
        except Exception:
            return {}
        if not response:
            return {}

        parsed = self._parse_json_response(response)
        if not isinstance(parsed, dict):
            return {}

        refined: dict[str, dict[str, str]] = {}
        for req_id, detail in parsed.items():
            if not isinstance(req_id, str) or not isinstance(detail, dict):
                continue
            row: dict[str, str] = {}
            for key in ("normal_scenario", "exception_scenario", "specification", "performance"):
                value = detail.get(key)
                if isinstance(value, str) and value.strip():
                    row[key] = value.strip()
            if row:
                refined[req_id] = row
        return refined

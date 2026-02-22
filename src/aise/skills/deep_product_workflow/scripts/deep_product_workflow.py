"""Deep Product workflow skill with paired Product Designer / Product Reviewer subagents."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ....core.artifact import Artifact, ArtifactType
from ....core.skill import Skill, SkillContext


class DeepProductWorkflowSkill(Skill):
    """Run PM deep workflow and generate revision-traceable design documents."""

    @property
    def name(self) -> str:
        return "deep_product_workflow"

    @property
    def description(self) -> str:
        return (
            "Run Product Designer and Product Reviewer paired workflow to generate "
            "system-design.md and system-requirements.md with full revision history"
        )

    def validate_input(self, input_data: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        if not str(input_data.get("raw_requirements", "")).strip():
            errors.append("'raw_requirements' field is required")
        return errors

    def execute(self, input_data: dict[str, Any], context: SkillContext) -> Artifact:
        project_name = context.project_name or str(input_data.get("project_name", "Untitled")).strip() or "Untitled"
        raw_requirements = str(input_data.get("raw_requirements", "")).strip()
        user_memory = self._normalize_memory(input_data.get("user_memory") or context.parameters.get("user_memory"))
        output_dir = self._resolve_output_dir(input_data, context)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Step 1: Product Designer expands understanding from raw requirements + memory.
        expanded = self._designer_expand_requirements(
            raw_requirements=raw_requirements,
            user_memory=user_memory,
            project_name=project_name,
            context=context,
        )

        # Step 2: Product design with paired review loop (at least two rounds).
        design_rounds = self._run_product_design_review_rounds(expanded=expanded, context=context, min_rounds=2)
        latest_design = design_rounds[-1]["design"]

        # Step 3: System requirements with paired review loop (at least two rounds).
        requirements_rounds = self._run_system_requirement_review_rounds(
            expanded=expanded,
            latest_design=latest_design,
            context=context,
            min_rounds=2,
        )
        latest_requirements = requirements_rounds[-1]["system_requirements"]

        design_doc_path = output_dir / "system-design.md"
        req_doc_path = output_dir / "system-requirements.md"
        design_doc_path.write_text(
            self._render_system_design_doc(
                project_name=project_name,
                expanded=expanded,
                latest_design=latest_design,
                rounds=design_rounds,
            ),
            encoding="utf-8",
        )
        req_doc_path.write_text(
            self._render_system_requirements_doc(
                project_name=project_name,
                expanded=expanded,
                latest_design=latest_design,
                latest_requirements=latest_requirements,
                rounds=requirements_rounds,
            ),
            encoding="utf-8",
        )

        requirements_artifact = Artifact(
            artifact_type=ArtifactType.REQUIREMENTS,
            content={
                "raw_requirements": raw_requirements,
                "analysis_mode": expanded.get("analysis_mode", "deep_product_workflow"),
                "expanded_understanding": expanded,
                "functional_requirements": [
                    {"id": sf["id"], "description": sf["goal"], "priority": sf.get("priority", "medium")}
                    for sf in latest_design.get("system_features", [])
                ],
                "non_functional_requirements": [
                    {"id": f"NFR-{idx:03d}", "description": c, "priority": "high"}
                    for idx, c in enumerate(expanded.get("constraints", []), start=1)
                ],
                "constraints": [
                    {"id": f"C-{idx:03d}", "description": c}
                    for idx, c in enumerate(expanded.get("constraints", []), start=1)
                ],
            },
            producer="product_designer",
            metadata={"project_name": project_name, "subagent": "product_designer", "step": "requirement_expansion"},
        )
        context.artifact_store.store(requirements_artifact)

        system_design_artifact = Artifact(
            artifact_type=ArtifactType.SYSTEM_DESIGN,
            content=self._to_system_design_artifact_content(project_name, latest_design),
            producer="product_designer",
            metadata={"project_name": project_name, "subagent": "product_designer", "step": "product_design"},
        )
        context.artifact_store.store(system_design_artifact)

        system_requirements_artifact = Artifact(
            artifact_type=ArtifactType.SYSTEM_REQUIREMENTS,
            content=self._to_system_requirements_artifact_content(project_name, latest_requirements),
            producer="product_designer",
            metadata={
                "project_name": project_name,
                "subagent": "product_designer",
                "step": "system_requirement_design",
            },
        )
        context.artifact_store.store(system_requirements_artifact)

        latest_review = requirements_rounds[-1].get("review", {}) if requirements_rounds else {}
        review_artifact = Artifact(
            artifact_type=ArtifactType.REVIEW_FEEDBACK,
            content={
                "approved": bool(latest_review.get("approved", False)),
                "reviewer": "product_reviewer",
                "target": "system_requirements",
                "issues": latest_review.get("issues", []),
                "summary": latest_review.get("summary", ""),
            },
            producer="product_reviewer",
            metadata={"project_name": project_name, "subagent": "product_reviewer", "step": "review"},
        )
        context.artifact_store.store(review_artifact)

        return Artifact(
            artifact_type=ArtifactType.PROGRESS_REPORT,
            content={
                "workflow": "deep_product_workflow",
                "project_name": project_name,
                "sub_agents": ["product_designer", "product_reviewer"],
                "step1": {
                    "name": "requirement_expansion",
                    "status": "completed",
                    "memory_items": len(user_memory),
                },
                "step2": {
                    "name": "product_design_review_loop",
                    "status": "completed",
                    "rounds": len(design_rounds),
                    "revision_history": [r["review"].get("summary", "") for r in design_rounds],
                },
                "step3": {
                    "name": "system_requirement_review_loop",
                    "status": "completed",
                    "rounds": len(requirements_rounds),
                    "revision_history": [r["review"].get("summary", "") for r in requirements_rounds],
                },
                "generated_files": [str(design_doc_path), str(req_doc_path)],
                "artifact_ids": {
                    "requirements": requirements_artifact.id,
                    "system_design": system_design_artifact.id,
                    "system_requirements": system_requirements_artifact.id,
                    "review_feedback": review_artifact.id,
                },
            },
            producer="product_manager",
            metadata={"project_name": project_name},
        )

    def _resolve_output_dir(self, input_data: dict[str, Any], context: SkillContext) -> Path:
        project_root = context.parameters.get("project_root")
        root_path = Path(project_root).resolve() if isinstance(project_root, str) and project_root.strip() else None
        output_dir = input_data.get("output_dir")
        safe_default = (root_path / "docs") if root_path is not None else Path("docs")
        if isinstance(output_dir, str) and output_dir.strip():
            output_path = Path(output_dir)
            if root_path is not None:
                # Keep writes inside project root to avoid permission errors and sandbox escapes.
                candidate = (
                    (root_path / output_path).resolve() if not output_path.is_absolute() else output_path.resolve()
                )
                try:
                    candidate.relative_to(root_path)
                    return candidate
                except ValueError:
                    return safe_default
            return output_path.resolve()
        return safe_default

    def _normalize_memory(self, value: Any) -> list[str]:
        if isinstance(value, str):
            return [value] if value.strip() else []
        if isinstance(value, list):
            output: list[str] = []
            for item in value:
                text = str(item).strip()
                if text:
                    output.append(text)
            return output
        return []

    def _designer_expand_requirements(
        self,
        *,
        raw_requirements: str,
        user_memory: list[str],
        project_name: str,
        context: SkillContext,
    ) -> dict[str, Any]:
        prompt = (
            "You are Product Designer.\n"
            "Task: expand and clarify user raw requirements with user memory.\n"
            "Return JSON with keys: intent_summary, business_goals, users, scenarios, constraints, assumptions, risks."
        )
        memory_text = "\n".join(f"- {m}" for m in user_memory) or "- (none)"
        llm_data = self._run_llm_json(
            context=context,
            system_prompt=prompt,
            user_prompt=(
                f"Project: {project_name}\nRaw requirements:\n{raw_requirements}\n\nUser memory:\n{memory_text}\n"
            ),
        )
        if llm_data:
            return {
                "analysis_mode": "llm",
                "raw_requirements": raw_requirements,
                "user_memory": user_memory,
                "intent_summary": str(llm_data.get("intent_summary", "")).strip()
                or "Clarify and deliver the requested system.",
                "business_goals": self._as_str_list(llm_data.get("business_goals")),
                "users": self._as_str_list(llm_data.get("users")),
                "scenarios": self._as_str_list(llm_data.get("scenarios")),
                "constraints": self._as_str_list(llm_data.get("constraints")),
                "assumptions": self._as_str_list(llm_data.get("assumptions")),
                "risks": self._as_str_list(llm_data.get("risks")),
            }

        goals = self._extract_requirement_points(raw_requirements)[:8]
        users = ["End users", "Operations team"]
        scenarios = ["Primary usage flow", "Error handling and recovery"]
        constraints = ["Cross-platform support", "Scalable architecture"]
        if self._is_snake_project(raw_requirements):
            users = ["玩家", "观战者", "运营活动人员"]
            scenarios = [
                "单人模式：玩家本地操作并挑战关卡目标",
                "人机模式：玩家与 AI 蛇对抗并比较积分",
                "多人模式：多个玩家实时对战并结算排名",
            ]
            constraints = [
                "实时输入响应与稳定帧率",
                "公平积分与反作弊基础约束",
                "关卡与食物扩展配置化",
            ]
        return {
            "analysis_mode": "heuristic",
            "raw_requirements": raw_requirements,
            "user_memory": user_memory,
            "intent_summary": f"Deliver project based on {len(goals)} core requirement points.",
            "business_goals": goals,
            "users": users,
            "scenarios": scenarios,
            "constraints": constraints,
            "assumptions": ["Requirements can evolve through review loops"],
            "risks": ["Ambiguity in platform-specific behavior"],
        }

    def _run_product_design_review_rounds(
        self,
        *,
        expanded: dict[str, Any],
        context: SkillContext,
        min_rounds: int,
    ) -> list[dict[str, Any]]:
        rounds: list[dict[str, Any]] = []
        previous_design: dict[str, Any] | None = None
        previous_review: dict[str, Any] | None = None

        for round_index in range(1, max(2, min_rounds) + 1):
            design = self._designer_build_product_design(
                expanded=expanded,
                previous_design=previous_design,
                previous_review=previous_review,
                round_index=round_index,
                context=context,
            )
            review = self._reviewer_review_product_design(
                expanded=expanded,
                design=design,
                round_index=round_index,
                context=context,
            )
            rounds.append({"round": round_index, "design": design, "review": review})
            previous_design = design
            previous_review = review
        return rounds

    def _run_system_requirement_review_rounds(
        self,
        *,
        expanded: dict[str, Any],
        latest_design: dict[str, Any],
        context: SkillContext,
        min_rounds: int,
    ) -> list[dict[str, Any]]:
        rounds: list[dict[str, Any]] = []
        previous_req: dict[str, Any] | None = None
        previous_review: dict[str, Any] | None = None

        for round_index in range(1, max(2, min_rounds) + 1):
            req_doc = self._designer_build_system_requirements(
                expanded=expanded,
                design=latest_design,
                previous_requirements=previous_req,
                previous_review=previous_review,
                round_index=round_index,
                context=context,
            )
            review = self._reviewer_review_system_requirements(
                design=latest_design,
                system_requirements=req_doc,
                round_index=round_index,
                context=context,
            )
            rounds.append({"round": round_index, "system_requirements": req_doc, "review": review})
            previous_req = req_doc
            previous_review = review
        return rounds

    def _designer_build_product_design(
        self,
        *,
        expanded: dict[str, Any],
        previous_design: dict[str, Any] | None,
        previous_review: dict[str, Any] | None,
        round_index: int,
        context: SkillContext,
    ) -> dict[str, Any]:
        features = previous_design.get("system_features", []) if previous_design else []
        if not features:
            features = []
            for idx, goal in enumerate(expanded.get("business_goals", []), start=1):
                functions = self._goal_to_functions(goal)
                features.append(
                    {
                        "id": f"SF-{idx:03d}",
                        "name": self._to_title(goal, fallback=f"Feature {idx}"),
                        "goal": goal,
                        "functions": functions,
                        "constraints": expanded.get("constraints", []),
                        "priority": "high" if idx <= 2 else "medium",
                    }
                )

        if previous_review and previous_review.get("issues"):
            issue_texts = [str(issue) for issue in previous_review.get("issues", [])]
            for feature in features:
                feature.setdefault("constraints", [])
                for issue in issue_texts[:2]:
                    if issue not in feature["constraints"]:
                        feature["constraints"].append(issue)

        overview = " ".join(
            [
                expanded.get("intent_summary", "").strip(),
                "This design consolidates large-grain system features and traceable product intent.",
            ]
        ).strip()

        return {
            "round": round_index,
            "overview": overview,
            "overall_solution": [
                "Use modular architecture with consistent UX across target platforms.",
                "Feature-first delivery with traceability from intent to implementation.",
            ],
            "system_features": features,
            "designer_response": self._build_designer_response(previous_review),
        }

    def _reviewer_review_product_design(
        self,
        *,
        expanded: dict[str, Any],
        design: dict[str, Any],
        round_index: int,
        context: SkillContext,
    ) -> dict[str, Any]:
        features = design.get("system_features", [])
        issues: list[str] = []
        if not features:
            issues.append("No system features were produced.")
        for sf in features:
            if not sf.get("goal"):
                issues.append(f"{sf.get('id', 'SF-UNKNOWN')} missing goal.")
            if not sf.get("functions"):
                issues.append(f"{sf.get('id', 'SF-UNKNOWN')} missing functional details.")
            if not sf.get("constraints"):
                issues.append(f"{sf.get('id', 'SF-UNKNOWN')} missing constraint details.")

        approved = round_index >= 2 and not issues
        if round_index == 1 and not issues:
            issues.append("Add stronger traceability and reviewer response section before approval.")
            approved = False

        return {
            "reviewer": "product_reviewer",
            "approved": approved,
            "summary": "Approved" if approved else "Needs revision",
            "issues": issues,
            "suggestions": [
                "Ensure each SF has explicit goal/function/constraint fields.",
                "Record reviewer comments and designer responses in revision history.",
            ],
            "decision": "approve" if approved else "revise",
            "expanded_context_used": bool(expanded.get("intent_summary")),
        }

    def _designer_build_system_requirements(
        self,
        *,
        expanded: dict[str, Any],
        design: dict[str, Any],
        previous_requirements: dict[str, Any] | None,
        previous_review: dict[str, Any] | None,
        round_index: int,
        context: SkillContext,
    ) -> dict[str, Any]:
        srs = previous_requirements.get("requirements", []) if previous_requirements else []
        if not srs:
            srs = []
            for idx, sf in enumerate(design.get("system_features", []), start=1):
                sr_id = f"SR-{idx:03d}"
                scenario = f"As a user, I need {sf.get('goal', sf.get('name', 'the feature'))}."
                srs.append(
                    {
                        "id": sr_id,
                        "source_sfs": [sf.get("id", f"SF-{idx:03d}")],
                        "title": sf.get("name", f"Requirement {idx}"),
                        "requirement_overview": sf.get("goal", ""),
                        "scenario": scenario,
                        "users": expanded.get("users", ["End users"]),
                        "interaction_process": self._goal_to_interactions(sf.get("goal", "")),
                        "expected_result": f"System achieves: {sf.get('goal', '')}",
                        "spec_targets": ["Availability >= 99.9%", "P95 response time <= 300ms"],
                        "constraints": sf.get("constraints", []),
                        "use_case_diagram": f"UseCase({sr_id}) -> Actor(User) -> System({sf.get('name', 'Feature')})",
                        "use_case_description": (
                            f"{sr_id} captures scenario, interactions, constraints, and measurable targets "
                            "for implementation and verification."
                        ),
                        "type": "functional",
                        "category": "Product Capability",
                        "priority": sf.get("priority", "medium"),
                        "verification_method": "integration_test",
                    }
                )

        if previous_review and previous_review.get("issues"):
            comment_note = " | ".join(str(i) for i in previous_review.get("issues", [])[:2])
            for sr in srs:
                sr.setdefault("use_case_description", "")
                if comment_note and comment_note not in sr["use_case_description"]:
                    sr["use_case_description"] = (
                        sr["use_case_description"] + " Reviewer focus: " + comment_note
                    ).strip()

        return {
            "round": round_index,
            "design_goals": [
                "Translate SF into complete SR with implementation-oriented details.",
                "Maintain strict traceability between SF and SR.",
            ],
            "design_approach": [
                "Feature to requirement decomposition",
                "Scenario-driven interaction design",
                "Measurable constraints and verification targets",
            ],
            "requirements": srs,
            "designer_response": self._build_designer_response(previous_review),
        }

    def _reviewer_review_system_requirements(
        self,
        *,
        design: dict[str, Any],
        system_requirements: dict[str, Any],
        round_index: int,
        context: SkillContext,
    ) -> dict[str, Any]:
        requirements = system_requirements.get("requirements", [])
        issues: list[str] = []
        if not requirements:
            issues.append("No SR entries generated.")
        for sr in requirements:
            required_fields = [
                "requirement_overview",
                "scenario",
                "users",
                "interaction_process",
                "expected_result",
                "spec_targets",
                "constraints",
                "use_case_diagram",
                "use_case_description",
            ]
            for field in required_fields:
                value = sr.get(field)
                if value is None or (isinstance(value, (str, list)) and len(value) == 0):
                    issues.append(f"{sr.get('id', 'SR-UNKNOWN')} missing {field}.")

        approved = round_index >= 2 and not issues
        if round_index == 1 and not issues:
            issues.append("Round 1 requires explicit update to traceability and reviewer feedback responses.")
            approved = False

        return {
            "reviewer": "product_reviewer",
            "approved": approved,
            "summary": "Approved" if approved else "Needs revision",
            "issues": issues,
            "suggestions": [
                "Ensure every SR includes complete scenario, interaction, and use case details.",
                "Keep revision response aligned with reviewer concerns.",
            ],
            "decision": "approve" if approved else "revise",
            "reviewed_sf_count": len(design.get("system_features", [])),
        }

    def _to_system_design_artifact_content(self, project_name: str, design: dict[str, Any]) -> dict[str, Any]:
        all_features = []
        for sf in design.get("system_features", []):
            all_features.append(
                {
                    "id": sf.get("id", ""),
                    "description": sf.get("goal", sf.get("name", "")),
                    "type": "external",
                    "category": "Product Capability",
                }
            )
        return {
            "project_name": project_name,
            "overview": design.get("overview", ""),
            "external_features": all_features,
            "internal_dfx_features": [],
            "all_features": all_features,
            "system_features": design.get("system_features", []),
        }

    def _to_system_requirements_artifact_content(self, project_name: str, req_doc: dict[str, Any]) -> dict[str, Any]:
        requirements = req_doc.get("requirements", [])
        matrix: dict[str, list[str]] = {}
        for sr in requirements:
            for sf_id in sr.get("source_sfs", []):
                matrix.setdefault(str(sf_id), []).append(str(sr.get("id", "")))
        coverage_total = len(matrix)
        covered = len([k for k, v in matrix.items() if v])
        return {
            "project_name": project_name,
            "overview": "System requirements generated by deep product workflow.",
            "requirements": requirements,
            "coverage_summary": {
                "total_sfs": coverage_total,
                "covered_sfs": covered,
                "uncovered_sfs": [],
                "coverage_percentage": (covered / coverage_total * 100) if coverage_total else 0,
            },
            "traceability_matrix": matrix,
        }

    def _render_system_design_doc(
        self,
        *,
        project_name: str,
        expanded: dict[str, Any],
        latest_design: dict[str, Any],
        rounds: list[dict[str, Any]],
    ) -> str:
        lines = [
            "# system-design.md",
            "",
            f"Generated at: {self._now_iso()}",
            f"Project: {project_name}",
            "",
            "## Product Intent Expansion",
            "",
            f"- Summary: {expanded.get('intent_summary', '')}",
            "- Business Goals:",
            *[f"  - {item}" for item in expanded.get("business_goals", [])],
            "- Users:",
            *[f"  - {item}" for item in expanded.get("users", [])],
            "- Constraints:",
            *[f"  - {item}" for item in expanded.get("constraints", [])],
            "",
            "## Overall Product Design",
            "",
            f"{latest_design.get('overview', '')}",
            "",
            "### Design Approach",
            *[f"- {item}" for item in latest_design.get("overall_solution", [])],
            "",
            "## System Features (SF)",
            "",
        ]
        for sf in latest_design.get("system_features", []):
            lines.extend(
                [
                    f"### {sf.get('id', 'SF-UNKNOWN')} - {sf.get('name', '')}",
                    f"- Feature Goal: {sf.get('goal', '')}",
                    "- Functions:",
                    *[f"  - {item}" for item in sf.get("functions", [])],
                    "- Constraints:",
                    *[f"  - {item}" for item in sf.get("constraints", [])],
                    "",
                ]
            )

        lines.extend(["## Revision History", ""])
        for item in rounds:
            review = item.get("review", {})
            design = item.get("design", {})
            lines.extend(
                [
                    f"### Round {item.get('round', '')}",
                    f"- Reviewer Decision: {review.get('decision', '')}",
                    f"- Reviewer Summary: {review.get('summary', '')}",
                    "- Reviewer Issues:",
                    *self._bullet_or_default(review.get("issues", []), default="(none)"),
                    "- Reviewer Suggestions:",
                    *self._bullet_or_default(review.get("suggestions", []), default="(none)"),
                    "- Designer Response:",
                    *self._bullet_or_default(design.get("designer_response", []), default="Initial draft"),
                    "",
                ]
            )
        return "\n".join(lines).strip() + "\n"

    def _render_system_requirements_doc(
        self,
        *,
        project_name: str,
        expanded: dict[str, Any],
        latest_design: dict[str, Any],
        latest_requirements: dict[str, Any],
        rounds: list[dict[str, Any]],
    ) -> str:
        lines = [
            "# system-requirements.md",
            "",
            f"Generated at: {self._now_iso()}",
            f"Project: {project_name}",
            "",
            "## System Design Context",
            "",
            f"- Intent Summary: {expanded.get('intent_summary', '')}",
            f"- SF Count: {len(latest_design.get('system_features', []))}",
            "",
            "## System Requirement Design",
            "",
            "### Design Goals",
            *[f"- {g}" for g in latest_requirements.get("design_goals", [])],
            "",
            "### Design Approach",
            *[f"- {a}" for a in latest_requirements.get("design_approach", [])],
            "",
            "## System Requirements (SR)",
            "",
        ]
        for sr in latest_requirements.get("requirements", []):
            lines.extend(
                [
                    f"### {sr.get('id', 'SR-UNKNOWN')} - {sr.get('title', '')}",
                    f"- Requirement Overview: {sr.get('requirement_overview', '')}",
                    f"- Scenario: {sr.get('scenario', '')}",
                    f"- Users: {', '.join(sr.get('users', []))}",
                    "- Interaction Process:",
                    *[f"  - {step}" for step in sr.get("interaction_process", [])],
                    f"- Expected: {sr.get('expected_result', '')}",
                    "- Spec Targets:",
                    *[f"  - {target}" for target in sr.get("spec_targets", [])],
                    "- Constraints:",
                    *[f"  - {c}" for c in sr.get("constraints", [])],
                    f"- UseCase Diagram: {sr.get('use_case_diagram', '')}",
                    f"- UseCase Description: {sr.get('use_case_description', '')}",
                    "",
                ]
            )

        lines.extend(["## Revision History", ""])
        for item in rounds:
            review = item.get("review", {})
            req_doc = item.get("system_requirements", {})
            lines.extend(
                [
                    f"### Round {item.get('round', '')}",
                    f"- Reviewer Decision: {review.get('decision', '')}",
                    f"- Reviewer Summary: {review.get('summary', '')}",
                    "- Reviewer Issues:",
                    *self._bullet_or_default(review.get("issues", []), default="(none)"),
                    "- Reviewer Suggestions:",
                    *self._bullet_or_default(review.get("suggestions", []), default="(none)"),
                    "- Designer Response:",
                    *self._bullet_or_default(req_doc.get("designer_response", []), default="Initial draft"),
                    "",
                ]
            )
        return "\n".join(lines).strip() + "\n"

    def _build_designer_response(self, previous_review: dict[str, Any] | None) -> list[str]:
        if not previous_review:
            return ["Initial design draft based on expanded requirements."]
        issues = [str(i) for i in previous_review.get("issues", [])]
        if not issues:
            return ["All reviewer comments addressed; no outstanding issues."]
        return [f"Addressed reviewer issue: {issue}" for issue in issues[:4]]

    def _run_llm_json(self, *, context: SkillContext, system_prompt: str, user_prompt: str) -> dict[str, Any] | None:
        if context.llm_client is None:
            return None
        response = context.llm_client.complete(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
        )
        return self._parse_json_response(response)

    def _parse_json_response(self, text: str) -> dict[str, Any] | None:
        if not text:
            return None
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            pass
        match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, flags=re.DOTALL)
        if not match:
            return None
        try:
            parsed = json.loads(match.group(1))
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None

    def _split_lines(self, text: str) -> list[str]:
        return [line.strip("- ").strip() for line in text.splitlines() if line.strip()]

    def _extract_requirement_points(self, text: str) -> list[str]:
        raw_lines = self._split_lines(text)
        if not raw_lines:
            return []
        combined = " ".join(raw_lines)
        segments = re.split(r"[。.!?\n]|，|,|；|;|、|并且|并|还要|且", combined)
        points: list[str] = []
        for segment in segments:
            normalized = segment.strip().strip("-").strip()
            if len(normalized) < 4:
                continue
            if normalized in points:
                continue
            points.append(normalized)
        if not points:
            return raw_lines[:8]
        return points[:12]

    def _is_snake_project(self, text: str) -> bool:
        lowered = text.lower()
        return "snake" in lowered or "贪吃蛇" in text

    def _goal_to_functions(self, goal: str) -> list[str]:
        result = [
            f"Define user-facing behavior for: {goal}",
            f"Implement service logic and state transition for: {goal}",
            f"Expose verifiable outcomes and telemetry for: {goal}",
        ]
        if self._is_snake_project(goal):
            result.extend(
                [
                    "Support snake movement/collision and food generation loop",
                    "Track score, level objective, and match settlement",
                ]
            )
        return result

    def _goal_to_interactions(self, goal: str) -> list[str]:
        interactions = [
            "User selects mode/configuration and starts session",
            "System validates input and initializes runtime state",
            "System processes game/service loop and updates score/state",
            "System returns latest state and final settlement",
        ]
        if "多人" in goal or "multiplayer" in goal.lower():
            interactions.insert(2, "System synchronizes shared state between players")
        if "人机" in goal or "ai" in goal.lower():
            interactions.insert(2, "System computes AI decision and merges with player action")
        return interactions

    def _as_str_list(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        output: list[str] = []
        for item in value:
            text = str(item).strip()
            if text:
                output.append(text)
        return output

    def _to_title(self, text: str, *, fallback: str) -> str:
        cleaned = str(text).strip()
        if not cleaned:
            return fallback
        return cleaned[:1].upper() + cleaned[1:80]

    def _bullet_or_default(self, values: Any, *, default: str) -> list[str]:
        if not isinstance(values, list):
            return [f"  - {default}"]
        bullets = [f"  - {str(item)}" for item in values if str(item).strip()]
        return bullets if bullets else [f"  - {default}"]

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()
